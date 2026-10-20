from enum import IntEnum, StrEnum


class Presentation(IntEnum):
    """Eggs in each presentation."""

    BOX = 360
    CARTON = 30
    HALF = 15
    UNIT = 1


class PaymentMethod(StrEnum):
    CASH_USD = "efectivo_usd"
    CASH_BS = "efectivo_bs"
    MOBILE_PAYMENT = "pago_movil"
    CARD = "punto"


class BoxStatus(StrEnum):
    STOCKED = "stocked"
    OPEN = "open"
    FINISHED = "finished"
    SETTLED = "settled"


class MovementKind(StrEnum):
    SALE = "sale"
    BROKEN = "broken"
    SHRINKAGE = "shrinkage"
    GIFT = "gift"


class RateSource(StrEnum):
    BCV_API = "bcv_api"
    MANUAL = "manual"


class Fund(StrEnum):
    CAPITAL = "capital"
    PETTY_CASH = "petty_cash"
    SAVINGS = "savings"


class TransferKind(StrEnum):
    BETWEEN_FUNDS = "between_funds"
    CONTRIBUTION_RETURN = "contribution_return"
    PROFIT_WITHDRAWAL = "profit_withdrawal"
