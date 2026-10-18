from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    MetaData,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.types import BoxStatus, MovementKind, PaymentMethod, RateSource

Money = Numeric(14, 2)
Rate = Numeric(14, 4)
Share = Numeric(5, 4)


def value_enum(enum: type[StrEnum]) -> Enum:
    return Enum(
        enum,
        native_enum=False,
        length=20,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )
    type_annotation_map = {  # noqa: RUF012
        Decimal: Money,
        date: Date,
        datetime: DateTime(timezone=True),
        PaymentMethod: value_enum(PaymentMethod),
        BoxStatus: value_enum(BoxStatus),
        MovementKind: value_enum(MovementKind),
        RateSource: value_enum(RateSource),
    }


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Partner(Base):
    __tablename__ = "partners"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    share: Mapped[Decimal] = mapped_column(Share)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    active: Mapped[bool] = mapped_column(server_default=text("true"))


class ExchangeRate(CreatedAt, Base):
    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(unique=True)
    rate: Mapped[Decimal] = mapped_column(Rate)
    source: Mapped[RateSource]


class Purchase(CreatedAt, Base):
    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(index=True)
    supplier: Mapped[str | None] = mapped_column(String(120))
    box_count: Mapped[int]
    cost_per_box_usd: Mapped[Decimal]
    rate: Mapped[Decimal] = mapped_column(Rate)
    total_usd: Mapped[Decimal]
    total_bs: Mapped[Decimal]
    payment_method: Mapped[PaymentMethod]
    paid_by_partner_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id"))
    note: Mapped[str | None] = mapped_column(Text)
    voided: Mapped[bool] = mapped_column(server_default=text("false"))
    void_reason: Mapped[str | None] = mapped_column(Text)

    paid_by_partner: Mapped[Partner | None] = relationship(lazy="joined")
    boxes: Mapped[list["Box"]] = relationship(back_populates="purchase", order_by="Box.number")

    __table_args__ = (CheckConstraint("box_count > 0", name="box_count_positive"),)


class Box(Base):
    __tablename__ = "boxes"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[int] = mapped_column(unique=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id"), index=True)
    cost_usd: Mapped[Decimal]
    box_price: Mapped[Decimal]
    carton_price: Mapped[Decimal]
    half_price: Mapped[Decimal]
    unit_price: Mapped[Decimal]
    status: Mapped[BoxStatus] = mapped_column(index=True)
    opened_on: Mapped[date | None]
    finished_on: Mapped[date | None]
    settlement_id: Mapped[int | None] = mapped_column(ForeignKey("settlements.id"), index=True)

    purchase: Mapped[Purchase] = relationship(back_populates="boxes", lazy="joined")

    __table_args__ = (
        Index(
            "uq_boxes_single_open",
            "status",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )


class Sale(CreatedAt, Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(index=True)
    rate: Mapped[Decimal] = mapped_column(Rate)
    boxes: Mapped[int] = mapped_column(server_default=text("0"))
    cartons: Mapped[int]
    halves: Mapped[int]
    units: Mapped[int]
    amount_usd: Mapped[Decimal]
    amount_bs: Mapped[Decimal]
    payment_method: Mapped[PaymentMethod]
    customer: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)
    voided: Mapped[bool] = mapped_column(server_default=text("false"))
    void_reason: Mapped[str | None] = mapped_column(Text)

    movements: Mapped[list["EggMovement"]] = relationship(
        back_populates="sale", order_by="EggMovement.id"
    )

    __table_args__ = (
        CheckConstraint(
            "boxes >= 0 AND cartons >= 0 AND halves >= 0 AND units >= 0 "
            "AND boxes + cartons + halves + units > 0",
            name="quantities",
        ),
    )


class InventoryCount(CreatedAt, Base):
    __tablename__ = "inventory_counts"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(index=True)
    expected_eggs: Mapped[int]
    counted_eggs: Mapped[int]
    difference: Mapped[int]
    note: Mapped[str | None] = mapped_column(Text)


class EggMovement(CreatedAt, Base):
    __tablename__ = "egg_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    box_id: Mapped[int] = mapped_column(ForeignKey("boxes.id"), index=True)
    day: Mapped[date] = mapped_column(index=True)
    kind: Mapped[MovementKind]
    eggs: Mapped[int]
    amount_usd: Mapped[Decimal | None]
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id"), index=True)
    count_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_counts.id"), index=True)
    note: Mapped[str | None] = mapped_column(Text)

    box: Mapped[Box] = relationship(lazy="joined")
    sale: Mapped[Sale | None] = relationship(back_populates="movements")

    __table_args__ = (
        CheckConstraint("eggs > 0", name="eggs_positive"),
        CheckConstraint("(kind = 'sale') = (sale_id IS NOT NULL)", name="sale_link"),
    )


class Settlement(CreatedAt, Base):
    __tablename__ = "settlements"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(index=True)
    box_profit_usd: Mapped[Decimal]
    expenses_usd: Mapped[Decimal]
    reserve_usd: Mapped[Decimal]
    net_profit_usd: Mapped[Decimal]
    rate: Mapped[Decimal] = mapped_column(Rate)
    amount_bs: Mapped[Decimal]
    next_box_money_usd: Mapped[Decimal]
    note: Mapped[str | None] = mapped_column(Text)

    shares: Mapped[list["SettlementShare"]] = relationship(
        back_populates="settlement", order_by="SettlementShare.id"
    )


class SettlementShare(Base):
    __tablename__ = "settlement_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    settlement_id: Mapped[int] = mapped_column(ForeignKey("settlements.id"), index=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"))
    share: Mapped[Decimal] = mapped_column(Share)
    amount_usd: Mapped[Decimal]

    settlement: Mapped[Settlement] = relationship(back_populates="shares")
    partner: Mapped[Partner] = relationship(lazy="joined")


class Expense(CreatedAt, Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(index=True)
    concept: Mapped[str] = mapped_column(String(200))
    amount_usd: Mapped[Decimal]
    rate: Mapped[Decimal] = mapped_column(Rate)
    amount_bs: Mapped[Decimal]
    paid_by_partner_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id"))
    reimbursed_on: Mapped[date | None]
    settlement_id: Mapped[int | None] = mapped_column(ForeignKey("settlements.id"), index=True)

    paid_by_partner: Mapped[Partner | None] = relationship(lazy="joined")

    __table_args__ = (CheckConstraint("amount_usd > 0", name="amount_positive"),)


class Contribution(CreatedAt, Base):
    __tablename__ = "contributions"

    id: Mapped[int] = mapped_column(primary_key=True)
    partner_id: Mapped[int] = mapped_column(ForeignKey("partners.id"), index=True)
    day: Mapped[date]
    amount_usd: Mapped[Decimal]
    note: Mapped[str | None] = mapped_column(Text)

    partner: Mapped[Partner] = relationship(lazy="joined")

    __table_args__ = (CheckConstraint("amount_usd > 0", name="amount_positive"),)


class ConversationMessage(CreatedAt, Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[Any] = mapped_column(JSONB)


class ProcessedUpdate(CreatedAt, Base):
    __tablename__ = "processed_updates"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
