"""Money moved between funds, or out to a partner, through the service and the bot's tool."""

import json
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.agent import tools
from app.agent.tools import dispatch, resolve_pending
from app.db import SessionLocal
from app.domain.errors import DomainError
from app.domain.types import Fund, PaymentMethod, TransferKind
from app.models import FundTransfer
from app.services import (
    contributions,
    expenses,
    funds,
    purchases,
    rates,
    reports,
    sales,
    settlements,
    transfers,
)
from tests.conftest import Call
from tests.test_tools import SPEAKER

DAY = date(2026, 10, 14)


@pytest.fixture(autouse=True)
async def rate(call: Call, two_partners: None) -> None:
    await call(rates.set_rate, rates.SetRateInput(day=DAY, rate=D("877.90")))


async def _contribute(call: Call, amount: str, day: date = DAY, partner: str = "Socio A") -> None:
    await call(
        contributions.record_contribution,
        contributions.ContributionInput(partner=partner, amount_usd=D(amount), day=day),
    )


def _purchase(cost: str) -> purchases.PurchaseInput:
    return purchases.PurchaseInput(
        day=DAY, box_count=1, cost_per_box_usd=D(cost), payment_method=PaymentMethod.CASH_USD
    )


def _between(source: Fund, to: Fund, amount: str, day: date = DAY) -> transfers.TransferInput:
    return transfers.TransferInput(
        kind=TransferKind.BETWEEN_FUNDS, from_fund=source, to_fund=to, amount_usd=D(amount), day=day
    )


def _give_back(amount: str, partner: str = "Socio A") -> transfers.TransferInput:
    return transfers.TransferInput(
        kind=TransferKind.CONTRIBUTION_RETURN,
        from_fund=Fund.CAPITAL,
        partner=partner,
        amount_usd=D(amount),
        day=DAY,
    )


async def _with_savings(call: Call) -> None:
    """A cierre with a 10 % reserve: capital $ 65,00, caja chica $ 0,00, ahorros $ 1,16."""
    await _contribute(call, "123.00")
    for cost in ("60.00", "63.00"):
        await call(purchases.register_purchase, _purchase(cost))
    await call(
        sales.record_sale,
        sales.SaleInput(day=DAY, cartons=12, payment_method=PaymentMethod.CASH_USD),
    )
    await call(
        expenses.record_expense,
        expenses.ExpenseInput(day=DAY, concept="Bolsas", amount_usd=D("0.40")),
    )
    await call(
        settlements.execute_settlement,
        settlements.SettlementInput(day=DAY, reserve_percent=D("0.10"), reinvest_usd=D("2.00")),
    )


async def _held(call: Call) -> tuple[D, D, D]:
    held = await call(funds.balances)
    return held.capital_usd, held.petty_cash_usd, held.savings_usd


async def test_moving_the_savings_to_the_capital_lets_a_refused_purchase_through(
    call: Call,
) -> None:
    await _with_savings(call)
    assert await _held(call) == (D("65.00"), D("0.00"), D("1.16"))
    with pytest.raises(DomainError, match="Falta un aporte de \\$ 1,00"):
        await call(purchases.register_purchase, _purchase("66.00"))

    await call(transfers.move_money, _between(Fund.SAVINGS, Fund.CAPITAL, "1.16"))
    await call(purchases.register_purchase, _purchase("66.00"))

    assert await _held(call) == (D("0.16"), D("0.00"), D("0.00"))


async def test_a_move_the_fund_cannot_cover_is_refused_and_nothing_is_stored(call: Call) -> None:
    await _with_savings(call)

    with pytest.raises(DomainError) as refused:
        await call(transfers.move_money, _between(Fund.SAVINGS, Fund.CAPITAL, "5.00"))

    assert refused.value.message == (
        "La caja de ahorros tiene $ 1,16 y el movimiento es de $ 5,00. Faltan $ 3,84."
    )
    assert await call(transfers.list_transfers) == []
    assert await _held(call) == (D("65.00"), D("0.00"), D("1.16"))


async def test_a_backdated_move_that_leaves_a_later_day_negative_is_refused(call: Call) -> None:
    await _contribute(call, "100.00", day=DAY - timedelta(days=1))
    await call(purchases.register_purchase, _purchase("100.00"))
    await _contribute(call, "30.00", day=DAY + timedelta(days=1))

    with pytest.raises(DomainError, match="quedaría en negativo el 14/10/2026"):
        await call(
            transfers.move_money,
            _between(Fund.CAPITAL, Fund.SAVINGS, "30.00", day=DAY - timedelta(days=1)),
        )


async def test_giving_back_part_of_an_aporte_lowers_the_capital_and_what_the_partner_put_in(
    call: Call,
) -> None:
    await _contribute(call, "100.00")
    await _contribute(call, "50.00", partner="Socio B")

    await call(transfers.move_money, _give_back("40.00"))

    held = await call(funds.balances)
    assert held.capital_usd == D("110.00")
    assert [(c.partner, c.amount_usd) for c in held.contributed_by_partner] == [
        ("Socio A", D("60.00")),
        ("Socio B", D("50.00")),
    ]
    with pytest.raises(DomainError, match="se le pueden devolver hasta \\$ 60,00"):
        await call(transfers.move_money, _give_back("60.01"))
    with pytest.raises(ValidationError, match="solo desde el capital"):
        transfers.TransferInput(
            kind=TransferKind.CONTRIBUTION_RETURN,
            from_fund=Fund.SAVINGS,
            partner="Socio A",
            amount_usd=D("1.00"),
        )


async def test_a_voided_move_gives_the_money_back_unless_it_was_spent(call: Call) -> None:
    await _with_savings(call)
    moved = await call(transfers.move_money, _between(Fund.SAVINGS, Fund.CAPITAL, "1.16"))
    withdrawal = await call(
        transfers.move_money,
        transfers.TransferInput(
            kind=TransferKind.PROFIT_WITHDRAWAL,
            from_fund=Fund.CAPITAL,
            partner="Socio B",
            amount_usd=D("65.50"),
            day=DAY,
        ),
    )

    with pytest.raises(DomainError, match=r"El capital tiene \$ 0,66 .* Faltan \$ 0,50"):
        await call(transfers.void_transfer, moved.id, purchases.VoidInput(reason="error"))
    await call(transfers.void_transfer, withdrawal.id, purchases.VoidInput(reason="error"))
    await call(transfers.void_transfer, moved.id, purchases.VoidInput(reason="error"))

    assert await _held(call) == (D("65.00"), D("0.00"), D("1.16"))


async def test_the_cash_flow_shows_a_move_leaving_one_fund_and_entering_the_other(
    call: Call,
) -> None:
    await _with_savings(call)
    before = await _held(call)

    await call(transfers.move_money, _between(Fund.SAVINGS, Fund.CAPITAL, "1.00"))
    flow = await call(reports.cash_flow, DAY, DAY)

    assert flow.savings.by_kind[funds.Kind.BETWEEN_FUNDS] == D("-1.00")
    assert flow.capital.by_kind[funds.Kind.BETWEEN_FUNDS] == D("1.00")
    assert sum(await _held(call)) == sum(before)


async def test_mover_dinero_shows_a_preview_and_moves_only_on_confirmar(call: Call) -> None:
    await _contribute(call, "100.00")
    arguments = {
        "que": "devolver_aporte",
        "desde": "capital",
        "hacia": "socio",
        "socio": "yo",
        "monto_usd": "40",
        "fecha": DAY.isoformat(),
    }

    prepared = await dispatch("mover_dinero", arguments, SessionLocal, SPEAKER)

    assert prepared.pending_id is not None, prepared.content
    preview = json.loads(prepared.content)["vista_previa"]
    assert (preview["partner"], preview["amount_usd"]) == ("Socio A", "40.00")
    assert await call(transfers.list_transfers) == []
    done = await resolve_pending(SessionLocal, prepared.pending_id, SPEAKER, confirm=True)
    assert done.outcome == tools.pending.Outcome.CONFIRMED
    assert (await call(funds.balances)).capital_usd == D("60.00")


async def test_mover_dinero_refuses_a_move_whose_shape_is_impossible(call: Call) -> None:
    await _contribute(call, "100.00")
    base = {"socio": "", "monto_usd": "10", "fecha": DAY.isoformat()}

    to_partner = await dispatch(
        "mover_dinero",
        {**base, "que": "traspaso", "desde": "capital", "hacia": "socio"},
        SessionLocal,
        SPEAKER,
    )
    from_savings = await dispatch(
        "mover_dinero",
        {**base, "que": "devolver_aporte", "desde": "ahorros", "hacia": "socio", "socio": "yo"},
        SessionLocal,
        SPEAKER,
    )

    assert (to_partner.is_error, to_partner.pending_id) == (True, None)
    assert "hacia es capital, caja_chica o ahorros" in to_partner.content
    assert "solo desde el capital" in from_savings.content


@pytest.mark.parametrize(
    ("kind", "source", "to", "partner"),
    [
        (TransferKind.BETWEEN_FUNDS, Fund.CAPITAL, Fund.CAPITAL, None),
        (TransferKind.BETWEEN_FUNDS, Fund.CAPITAL, Fund.SAVINGS, 1),
        (TransferKind.CONTRIBUTION_RETURN, Fund.SAVINGS, None, 1),
        (TransferKind.PROFIT_WITHDRAWAL, Fund.SAVINGS, None, None),
    ],
)
async def test_the_database_refuses_a_move_with_an_impossible_shape(
    kind: TransferKind, source: Fund, to: Fund | None, partner: int | None
) -> None:
    async with SessionLocal() as session, session.begin():
        session.add(
            FundTransfer(
                day=DAY,
                kind=kind,
                from_fund=source,
                to_fund=to,
                partner_id=partner,
                amount_usd=D("1.00"),
            )
        )
        with pytest.raises(IntegrityError, match="ck_fund_transfers_shape"):
            await session.flush()
