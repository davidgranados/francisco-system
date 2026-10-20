# Code Is Written in English; Spanish Only in What a Person or the Bot's Model Reads

## Rule

Every identifier in this repository is English: modules, packages, classes,
functions, methods, variables, SQLAlchemy columns and tables, Alembic revisions,
Pydantic fields of the services, fixtures, test names, docstrings and comments.

Spanish belongs where a person reads it, because the partners are
Venezuelan and talk to the system in Spanish:

- the bot's replies and the system prompt in `app/agent/`;
- the API's error messages (`DomainError` messages, `HTTPException` details);
- `Field(description=...)` text the API docs or the model shows;
- the messages the CLI commands print (`app/reset_db.py`, `app/restore_db.py`);
- `docs/`, the `README.md` and the eval cases in `evals/casos.yaml`.

## Domain terms translate too

A business word does not stay Spanish because it is "the domain word":

| Spanish | In code |
|---|---|
| socio | `partner` |
| venta | `sale` |
| compra | `purchase` |
| gasto | `expense` |
| aporte | `contribution` |
| reembolso | `reimbursement` |
| liquidación | `settlement` |
| fondo, caja chica, ahorro | `fund`, `petty_cash`, `savings` |
| tasa (BCV) | `rate` |
| caja, cartón, medio cartón, huevo suelto | `box`, `carton`, `half`, `unit` |
| anular | `void` |

## The one exception: the agent's tool schemas

The tool inputs in `app/agent/tools.py` (`VentaInput`, `cajas`, `forma_pago`,
`cobrado_bs`) are Spanish on purpose. Their field names and values are text
the language model reads, and they follow how the partners talk. They are the
boundary, like another system's API keys: each tool turns them into an English
service input right away (`sales.SaleInput(boxes=p.cajas, ...)`).

Spanish stops at that boundary. A service, a model or a test never takes a
Spanish name because a tool schema has one.

## ❌ Don't

```python
class Venta(Base):
    cajas: Mapped[int]


async def registrar_venta(session, datos): ...


total_cobrado = sum(...)


def test_una_venta_sin_tasa_usa_la_anterior(): ...
```

## ✅ Do

```python
class Sale(Base):
    boxes: Mapped[int]


async def record_sale(session, sale): ...


charged_total = sum(...)


def test_a_sale_without_a_rate_that_day_uses_the_previous_one(): ...


raise DomainError(f"La venta {sale_id} ya estaba anulada.")  # Spanish: a partner reads it
```

## Why this rule exists

Mixed-language code costs a translation in the middle of every sentence
(`venta.boxes`, `record_venta`), grep stops working in either language
alone, and the boundary moves a little every time someone guesses. Keeping
code English and the text people read Spanish makes the one boundary that
matters visible: which strings need care with wording and tone.

Adapted from firu's rule of the same name, set by David Granados on
2026-09-01.
