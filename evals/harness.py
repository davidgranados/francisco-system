"""Run eval cases against a model through the real bot, and score them deterministically.

Each run gets a fresh database cloned from a migrated template, builds its fixture through
the services, drives ChatBot turn by turn the way Telegram does (buttons included), and is
scored on three things: the tool calls each turn made, the database state at the end, and
the words the replies must contain.
"""

import asyncio
import statistics
import time
import unicodedata
import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import asyncpg
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from app.agent.loop import Agent, AnthropicLike
from app.agent.telegram import ChatBot, button_data
from app.agent.tools import ToolKind, find_tool
from app.config import frozen_today, settings, today
from app.domain.types import Fund, MovementKind, TransferKind
from app.models import (
    Contribution,
    ConversationMessage,
    EggMovement,
    ExchangeRate,
    Expense,
    FundTransfer,
    InventoryCount,
    PendingAction,
    Purchase,
    Sale,
    Settlement,
)
from app.services import inventory, rates
from app.services.ledger import boxes_with_eggs
from evals.cases import LIST_KEYS, Case, Mention, Turn
from evals.fixtures import FIXTURES, PARTNERS

ROOT = Path(__file__).resolve().parents[1]
CHAT_ID = 4242

# USD per million tokens: input, output, 5-minute cache write, cache read (prompt <= 100K).
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.10),
}
HAIKU_LONG_PROMPT = (100_000, (0.50, 2.50, 0.625, 0.05))
LOSS_NAMES = {
    MovementKind.BROKEN: "rotos",
    MovementKind.GIFT: "regalados",
    MovementKind.SHRINKAGE: "merma",
}


# --- Recording the API -------------------------------------------------------------------


@dataclass
class ApiCall:
    latency_s: float
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    stop_reason: str | None = None
    error: str | None = None


class _RecordingMessages:
    def __init__(self, inner: Any, calls: list[ApiCall]) -> None:
        self.inner = inner
        self.calls = calls

    async def create(self, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            response = await self.inner.create(**kwargs)
        except Exception as error:
            self.calls.append(ApiCall(time.perf_counter() - start, error=repr(error)))
            raise
        usage = response.usage
        self.calls.append(
            ApiCall(
                latency_s=time.perf_counter() - start,
                input_tokens=usage.input_tokens or 0,
                output_tokens=usage.output_tokens or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                stop_reason=response.stop_reason,
            )
        )
        return response


class RecordingClient:
    """Wraps a client to keep usage, latency and errors of every request of one run."""

    def __init__(self, inner: AnthropicLike) -> None:
        self.inner = inner
        self.calls: list[ApiCall] = []
        self.messages = _RecordingMessages(inner.messages, self.calls)

    def begin_turn(self, index: int) -> None:
        hook = getattr(self.inner, "begin_turn", None)
        if hook is not None:
            hook(index)


def request_cost(model: str, call: ApiCall) -> float:
    prices = PRICES.get(model)
    if prices is None:
        return 0.0
    prompt = call.input_tokens + call.cache_read_tokens + call.cache_write_tokens
    if model == "claude-haiku-5-5" and prompt > HAIKU_LONG_PROMPT[0]:
        prices = HAIKU_LONG_PROMPT[1]
    rate_in, rate_out, rate_write, rate_read = prices
    return (
        call.input_tokens * rate_in
        + call.output_tokens * rate_out
        + call.cache_write_tokens * rate_write
        + call.cache_read_tokens * rate_read
    ) / 1_000_000


# --- Databases -----------------------------------------------------------------------------


class EvalDatabases:
    """A migrated template database, cloned into a fresh database for every run."""

    def __init__(self, url: str) -> None:
        self.url = make_url(url)
        assert self.url.database
        self.template = f"{self.url.database}_plantilla"
        self._create_lock = asyncio.Lock()

    async def _admin(self) -> asyncpg.Connection:
        return await asyncpg.connect(
            host=self.url.host,
            port=self.url.port,
            user=self.url.username,
            password=self.url.password,
            database="postgres",
        )

    def _url_of(self, name: str) -> str:
        return self.url.set(database=name).render_as_string(hide_password=False)

    async def prepare(self) -> None:
        admin = await self._admin()
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{self.template}" WITH (FORCE)')
            await admin.execute(f'CREATE DATABASE "{self.template}"')
        finally:
            await admin.close()
        await asyncio.to_thread(_migrate, self._url_of(self.template))

    @asynccontextmanager
    async def fresh(self) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
        name = f"{self.url.database}_{uuid.uuid4().hex[:10]}"
        async with self._create_lock:
            admin = await self._admin()
            try:
                await admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{self.template}"')
            finally:
                await admin.close()
        engine = create_async_engine(self._url_of(name))
        try:
            yield async_sessionmaker(engine, expire_on_commit=False)
        finally:
            await engine.dispose()
            admin = await self._admin()
            try:
                await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            finally:
                await admin.close()


def _migrate(url: str) -> None:
    """alembic/env.py reads settings.database_url, so point it at the template meanwhile."""
    previous = settings.database_url
    settings.database_url = url
    try:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["configure_logger"] = False
        command.upgrade(config, "head")
    finally:
        settings.database_url = previous


async def _no_bcv_rate() -> Decimal:
    raise rates.RateUnavailable("the evals never call the BCV API")


# --- State ---------------------------------------------------------------------------------

FUND_NAMES = {Fund.CAPITAL: "capital", Fund.PETTY_CASH: "caja_chica", Fund.SAVINGS: "ahorros"}
MOVE_NAMES = {
    TransferKind.BETWEEN_FUNDS: "traspaso",
    TransferKind.CONTRIBUTION_RETURN: "devolver_aporte",
    TransferKind.PROFIT_WITHDRAWAL: "retirar_utilidades",
}


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


async def snapshot(factory: async_sessionmaker[AsyncSession]) -> dict[str, Any]:
    """Every row the cases can talk about, keyed by id, plus the totals they check."""
    async with factory() as s:
        sales = await s.scalars(select(Sale).order_by(Sale.id))
        purchases = await s.scalars(select(Purchase).order_by(Purchase.id))
        expenses = await s.scalars(select(Expense).order_by(Expense.id))
        losses = await s.scalars(
            select(EggMovement)
            .where(EggMovement.kind != MovementKind.SALE)
            .order_by(EggMovement.id)
        )
        counts = await s.scalars(select(InventoryCount).order_by(InventoryCount.id))
        contributions = await s.scalars(select(Contribution).order_by(Contribution.id))
        settlements = await s.scalars(select(Settlement).order_by(Settlement.id))
        moves = await s.scalars(select(FundTransfer).order_by(FundTransfer.id))
        rate = await s.scalar(select(ExchangeRate).where(ExchangeRate.day == today()))
        holdings = await boxes_with_eggs(s)
        open_actions = await s.scalar(
            select(func.count())
            .select_from(PendingAction)
            .where(PendingAction.resolved_at.is_(None), PendingAction.expires_at > func.now())
        )
        stock = await inventory.stock(s)
        state: dict[str, Any] = {
            "ventas": {
                sale.id: {
                    "fecha": sale.day.isoformat(),
                    "cajas": sale.boxes,
                    "cartones": sale.cartons,
                    "medios": sale.halves,
                    "sueltos": sale.units,
                    "monto_usd": _money(sale.amount_usd),
                    "monto_bs": _money(sale.amount_bs),
                    "forma_pago": sale.payment_method.value,
                    "cliente": sale.customer,
                    "anulada": sale.voided,
                }
                for sale in sales
            },
            "compras": {
                p.id: {
                    "fecha": p.day.isoformat(),
                    "cajas": p.box_count,
                    "costo_por_caja_usd": _money(p.cost_per_box_usd),
                    "total_usd": _money(p.total_usd),
                    "forma_pago": p.payment_method.value,
                    "anulada": p.voided,
                }
                for p in purchases
            },
            "gastos": {
                e.id: {
                    "fecha": e.day.isoformat(),
                    "concepto": e.concept,
                    "monto_usd": _money(e.amount_usd),
                    "monto_bs": _money(e.amount_bs),
                    "pagado_por": e.paid_by_partner.name if e.paid_by_partner else "negocio",
                    "devuelto": e.reimbursed_on is not None,
                }
                for e in expenses
            },
            "mermas": {m.id: {"tipo": LOSS_NAMES[m.kind], "huevos": m.eggs} for m in losses},
            "conteos": {
                c.id: {"contados": c.counted_eggs, "diferencia": c.difference} for c in counts
            },
            "aportes": {
                c.id: {"socio": c.partner.name, "monto_usd": _money(c.amount_usd)}
                for c in contributions
            },
            "movimientos": {
                m.id: {
                    "tipo": MOVE_NAMES[m.kind],
                    "desde": FUND_NAMES[m.from_fund],
                    "hacia": FUND_NAMES[m.to_fund] if m.to_fund else "socio",
                    "socio": m.partner.name if m.partner else None,
                    "monto_usd": _money(m.amount_usd),
                    "anulada": m.voided,
                }
                for m in moves
            },
            "cierres": {},
            "huevos": stock.total_eggs,
            "tasa_hoy": _money(rate.rate) if rate else None,
            "precios_caja_abierta": None,
            "pendientes_abiertos": open_actions or 0,
        }
        for settlement in settlements:
            await s.refresh(settlement, ["shares"])
            state["cierres"][settlement.id] = {
                "ganancia_cajas_usd": _money(settlement.box_profit_usd),
                "gastos_usd": _money(settlement.expenses_usd),
                "reserva_usd": _money(settlement.reserve_usd),
                "reinversion_usd": _money(settlement.reinvest_usd),
                "ganancia_neta_usd": _money(settlement.net_profit_usd),
                "partes": {
                    share.partner.name: _money(share.amount_usd) for share in settlement.shares
                },
            }
        if holdings:
            box = holdings[0][0]
            state["precios_caja_abierta"] = {
                "caja": _money(box.box_price),
                "carton": _money(box.carton_price),
                "medio": _money(box.half_price),
                "unidad": _money(box.unit_price),
            }
    return state


def changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """What a run did: new rows, rows voided or reimbursed, and the totals after it."""

    def new(table: str) -> list[dict[str, Any]]:
        return [row for key, row in after[table].items() if key not in before[table]]

    losses: dict[str, int] = {}
    for row in new("mermas"):
        losses[row["tipo"]] = losses.get(row["tipo"], 0) + row["huevos"]
    voided = [
        {"tipo": kind, "id": key}
        for table, kind in (
            ("ventas", "venta"),
            ("compras", "compra"),
            ("movimientos", "movimiento_dinero"),
        )
        for key, row in after[table].items()
        if row["anulada"] and not before[table].get(key, {}).get("anulada", False)
    ]
    return {
        "ventas_nuevas": new("ventas"),
        "compras_nuevas": new("compras"),
        "gastos_nuevos": new("gastos"),
        "mermas_nuevas": [{"tipo": kind, "huevos": eggs} for kind, eggs in losses.items()],
        "conteos_nuevos": new("conteos"),
        "aportes_nuevos": new("aportes"),
        "cierres_nuevos": new("cierres"),
        "movimientos_nuevos": new("movimientos"),
        "anuladas": voided,
        "gastos_devueltos": [
            key
            for key, row in after["gastos"].items()
            if row["devuelto"] and not before["gastos"].get(key, {}).get("devuelto", False)
        ],
        **{key: after[key] for key in ("huevos", "tasa_hoy", "precios_caja_abierta")},
        "pendientes_abiertos": after["pendientes_abiertos"],
    }


# --- Matching ------------------------------------------------------------------------------


def normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text.lower())
    return " ".join("".join(c for c in stripped if not unicodedata.combining(c)).split())


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str | Decimal):
        return None
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        return None


def matches(expected: Any, actual: Any) -> bool:
    """Lists are alternatives, dicts match a subset of keys, "~text" matches a substring."""
    if isinstance(expected, list):
        return any(matches(option, actual) for option in expected)
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and matches(value, actual[key]) for key, value in expected.items()
        )
    if expected is None or actual is None:
        return expected is actual
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(expected) is type(actual) and expected == actual
    if isinstance(expected, str) and expected.startswith("~"):
        return normalize(expected[1:]) in normalize(str(actual))
    left, right = _decimal(expected), _decimal(actual)
    if left is not None and right is not None:
        return left == right
    return normalize(str(expected)) == normalize(str(actual))


def _assign(expected: list[Any], actual: list[Any]) -> bool:
    """True when every expected row matches its own actual row, with none left over."""
    if len(expected) != len(actual):
        return False
    if not expected:
        return True
    first, rest = expected[0], expected[1:]
    return any(
        matches(first, row) and _assign(rest, actual[:i] + actual[i + 1 :])
        for i, row in enumerate(actual)
    )


def score_state(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    failures = []
    for key in LIST_KEYS:
        wanted = expected.get(key, [])
        if not _assign(wanted, actual[key]):
            failures.append(f"estado {key}: se esperaba {wanted}, quedó {actual[key]}")
    for key, wanted in expected.items():
        if key not in LIST_KEYS and not matches(wanted, actual[key]):
            failures.append(f"estado {key}: se esperaba {wanted}, quedó {actual[key]}")
    return failures


# --- Turns ---------------------------------------------------------------------------------


@dataclass
class CallRecord:
    name: str
    args: dict[str, Any]
    ok: bool
    result: str


@dataclass
class TurnRecord:
    said: str
    speaker: str
    replies: list[str]
    pending_id: int | None
    calls: list[CallRecord]
    latency_s: float
    requests: int
    failures: list[str] = field(default_factory=list)

    @property
    def reply(self) -> str:
        return "\n".join(self.replies)


def _canonical(name: str) -> str:
    tool = find_tool(name)
    return tool.name if tool else name


def _resolved_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """The arguments as the tool saw them, defaults included (fecha becomes the day)."""
    tool = find_tool(name)
    if tool is None:
        return args
    try:
        return tool.input_model.model_validate(args).model_dump(mode="json")
    except ValidationError:
        return args


def _is_write(name: str) -> bool:
    tool = find_tool(name)
    return tool is not None and tool.kind != ToolKind.READ


def _mentioned(mention: Mention, text: str) -> bool:
    options = [mention] if isinstance(mention, str) else mention
    return any(normalize(option) in normalize(text) for option in options)


def score_turn(spec: Turn, record: TurnRecord) -> list[str]:
    failures: list[str] = []
    unmatched = [call for call in record.calls if call.ok]
    for expected in spec.llamadas:
        found = next(
            (
                call
                for call in unmatched
                if call.name == expected.herramienta and matches(expected.args, call.args)
            ),
            None,
        )
        if found is None:
            failures.append(f"faltó {expected.herramienta} {expected.args}")
        else:
            unmatched.remove(found)
    for call in record.calls:
        if call.ok and call.name in spec.prohibidas:
            failures.append(f"llamó {call.name}, que estaba prohibida en este turno")
    if not spec.permitir_escrituras_extra:
        failures += [
            f"escritura de más: {call.name} {call.args}"
            for call in unmatched
            if _is_write(call.name) and call.name not in spec.prohibidas
        ]
    failures += [
        f"la respuesta no menciona {mention!r}"
        for mention in spec.menciona
        if not _mentioned(mention, record.reply)
    ]
    if spec.pendiente is True and record.pending_id is None:
        failures.append("la respuesta no trae los botones Confirmar/Cancelar")
    if spec.pendiente is False and record.pending_id is not None:
        failures.append("la respuesta trae botones que no debía")
    return failures


def calls_in(rows: Iterable[ConversationMessage]) -> list[CallRecord]:
    """Tool calls and their results, read back from the history the bot stored."""
    uses: dict[str, tuple[str, dict[str, Any]]] = {}
    calls: list[CallRecord] = []
    for row in rows:
        if not isinstance(row.content, list):
            continue
        for block in row.content:
            if block.get("type") == "tool_use":
                uses[block["id"]] = (_canonical(block["name"]), block.get("input") or {})
            elif block.get("type") == "tool_result" and block.get("tool_use_id") in uses:
                name, args = uses[block["tool_use_id"]]
                content = block.get("content")
                calls.append(
                    CallRecord(
                        name=name,
                        args=_resolved_args(name, args),
                        ok=not block.get("is_error", False),
                        result=content if isinstance(content, str) else str(content),
                    )
                )
    return calls


# --- Runs ----------------------------------------------------------------------------------


@dataclass
class RunResult:
    case_id: str
    category: str
    model: str
    repeat: int
    passed: bool
    failures: list[str]
    turns: list[TurnRecord]
    api_calls: list[ApiCall]
    cost_usd: float
    state: dict[str, Any]
    transcript: list[dict[str, Any]]

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


ClientFactory = Callable[[Case], AnthropicLike]


@dataclass
class _Inbox:
    """What the bot sent back in one turn, the way Telegram would show it."""

    replies: list[str] = field(default_factory=list)
    pending_ids: list[int] = field(default_factory=list)

    async def receive(self, text: str, action_id: int | None) -> None:
        self.replies.append(text)
        if action_id is not None:
            self.pending_ids.append(action_id)


async def _history_after(
    factory: async_sessionmaker[AsyncSession], last_id: int
) -> list[ConversationMessage]:
    async with factory() as session:
        rows = await session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.chat_id == CHAT_ID, ConversationMessage.id > last_id)
            .order_by(ConversationMessage.id)
        )
        return list(rows)


async def run_case(
    case: Case,
    model: str,
    repeat: int,
    client: AnthropicLike,
    options: dict[str, Any],
    databases: EvalDatabases,
) -> RunResult:
    fixture = FIXTURES[case.fixture]
    recorder = RecordingClient(client)
    with frozen_today(fixture.today):
        async with databases.fresh() as factory:
            await fixture.build(factory)
            before = await snapshot(factory)
            bot = ChatBot(Agent(recorder, model, factory, options), factory)
            turns: list[TurnRecord] = []
            transcript: list[dict[str, Any]] = []
            last_row, last_pending = 0, None
            for index, spec in enumerate(case.turnos):
                recorder.begin_turn(index)
                inbox = _Inbox()
                reply = inbox.receive
                telegram_id = PARTNERS[spec.como]
                requests_before = len(recorder.calls)
                start = time.perf_counter()
                if spec.socio is not None:
                    said = spec.socio
                    await bot.handle_text(telegram_id, CHAT_ID, spec.socio, reply)
                elif last_pending is None:
                    said = f"[botón {spec.boton}]"
                    inbox.replies.append("(no había botones que tocar)")
                else:
                    said = f"[botón {spec.boton}]"
                    data = button_data(spec.boton == "confirmar", last_pending)
                    await bot.handle_button(telegram_id, CHAT_ID, data, reply)
                latency = time.perf_counter() - start
                rows = await _history_after(factory, last_row)
                last_row = rows[-1].id if rows else last_row
                transcript += [{"role": r.role, "content": r.content} for r in rows]
                record = TurnRecord(
                    said=said,
                    speaker=spec.como,
                    replies=inbox.replies,
                    pending_id=inbox.pending_ids[-1] if inbox.pending_ids else None,
                    calls=calls_in(rows),
                    latency_s=latency,
                    requests=len(recorder.calls) - requests_before,
                )
                record.failures = score_turn(spec, record)
                last_pending = record.pending_id or last_pending
                turns.append(record)
            after = await snapshot(factory)
    state = changes(before, after)
    failures = [f"turno {i}: {f}" for i, t in enumerate(turns, 1) for f in t.failures]
    failures += score_state(case.estado, state)
    failures += [f"error de la API: {c.error}" for c in recorder.calls if c.error]
    return RunResult(
        case_id=case.id,
        category=case.categoria,
        model=model,
        repeat=repeat,
        passed=not failures,
        failures=failures,
        turns=turns,
        api_calls=recorder.calls,
        cost_usd=sum(request_cost(model, call) for call in recorder.calls),
        state=state,
        transcript=transcript,
    )


async def run_all(
    cases: list[Case],
    models: list[str],
    repeats: int,
    client_for: ClientFactory,
    options_for: Callable[[str], dict[str, Any]],
    databases: EvalDatabases,
    concurrency: int = 4,
    on_result: Callable[[RunResult], None] | None = None,
) -> list[RunResult]:
    rates.fetch_bcv_rate = _no_bcv_rate  # type: ignore[assignment]
    await databases.prepare()
    gate = asyncio.Semaphore(concurrency)

    async def one(case: Case, model: str, repeat: int) -> RunResult:
        async with gate:
            result = await run_case(
                case, model, repeat, client_for(case), options_for(model), databases
            )
        if on_result is not None:
            on_result(result)
        return result

    jobs = [one(c, m, r) for m in models for c in cases for r in range(1, repeats + 1)]
    return list(await asyncio.gather(*jobs))


# --- Summary -------------------------------------------------------------------------------


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


def summarize(results: list[RunResult]) -> dict[str, dict[str, Any]]:
    """Per model: pass rates overall and by category, tokens, cost and turn latency."""
    summary: dict[str, dict[str, Any]] = {}
    for model in dict.fromkeys(result.model for result in results):
        runs = [r for r in results if r.model == model]
        categories: dict[str, list[bool]] = {}
        for run in runs:
            categories.setdefault(run.category, []).append(run.passed)
        latencies = [t.latency_s for r in runs for t in r.turns if t.requests]

        def mean(values: Iterable[float]) -> float:
            items = list(values)
            return statistics.fmean(items) if items else 0.0

        summary[model] = {
            "runs": len(runs),
            "passed": sum(r.passed for r in runs),
            "pass_rate": sum(r.passed for r in runs) / len(runs),
            "by_category": {
                name: sum(passed) / len(passed) for name, passed in sorted(categories.items())
            },
            "mean_input_tokens": mean(sum(c.input_tokens for c in r.api_calls) for r in runs),
            "mean_output_tokens": mean(sum(c.output_tokens for c in r.api_calls) for r in runs),
            "mean_cache_read_tokens": mean(
                sum(c.cache_read_tokens for c in r.api_calls) for r in runs
            ),
            "mean_cache_write_tokens": mean(
                sum(c.cache_write_tokens for c in r.api_calls) for r in runs
            ),
            "mean_requests": mean(len(r.api_calls) for r in runs),
            "mean_cost_usd": mean(r.cost_usd for r in runs),
            "p50_turn_latency_s": _percentile(latencies, 0.50),
            "p95_turn_latency_s": _percentile(latencies, 0.95),
            "failed_cases": sorted({r.case_id for r in runs if not r.passed}),
        }
    return summary


def report_table(summary: dict[str, dict[str, Any]]) -> str:
    models = list(summary)
    rows = [
        ("pasaron", lambda s: f"{s['passed']}/{s['runs']} ({s['pass_rate']:.0%})"),
        ("tokens entrada (media)", lambda s: f"{s['mean_input_tokens']:.0f}"),
        ("tokens salida (media)", lambda s: f"{s['mean_output_tokens']:.0f}"),
        ("tokens cache leídos (media)", lambda s: f"{s['mean_cache_read_tokens']:.0f}"),
        ("tokens cache escritos (media)", lambda s: f"{s['mean_cache_write_tokens']:.0f}"),
        ("requests por conversación", lambda s: f"{s['mean_requests']:.1f}"),
        ("USD por conversación", lambda s: f"{s['mean_cost_usd']:.5f}"),
        ("latencia por turno con modelo p50 (s)", lambda s: f"{s['p50_turn_latency_s']:.2f}"),
        ("latencia por turno con modelo p95 (s)", lambda s: f"{s['p95_turn_latency_s']:.2f}"),
    ]
    categories = sorted({c for s in summary.values() for c in s["by_category"]})
    for category in categories:
        rows.append(
            (
                f"  {category}",
                lambda s, c=category: (
                    f"{s['by_category'].get(c, 0):.0%}" if c in s["by_category"] else "-"
                ),
            )
        )
    width = max(len(name) for name, _ in rows) + 2
    columns = [max(18, len(m) + 2) for m in models]
    lines = ["".ljust(width) + "".join(m.ljust(w) for m, w in zip(models, columns, strict=True))]
    for name, cell in rows:
        values = "".join(cell(summary[m]).ljust(w) for m, w in zip(models, columns, strict=True))
        lines.append(name.ljust(width) + values)
    return "\n".join(lines)


def started_at() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
