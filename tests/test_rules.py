from decimal import Decimal as D

import pytest

from app.domain import rules
from app.domain.errors import DomainError
from app.domain.types import BoxStatus

MARKUP = D("0.25")


def test_part2_presentation_costs_of_a_60_dollar_box() -> None:
    assert rules.round_cents(D(60) / 12) == D("5.00")
    assert rules.round_cents(D(60) / 24) == D("2.50")
    assert rules.four_places(rules.egg_cost(D(60))) == D("0.1667")


def test_part3_prices_of_a_60_dollar_box() -> None:
    assert rules.prices_from_cost(D("60.00"), MARKUP) == rules.Prices(
        box=D("75.00"), carton=D("6.25"), half=D("3.15"), unit=D("0.21")
    )


def test_part4_prices_after_the_box_goes_up_to_63() -> None:
    assert rules.prices_from_cost(D("63.00"), MARKUP) == rules.Prices(
        box=D("78.75"), carton=D("6.60"), half=D("3.30"), unit=D("0.22")
    )


def test_box_price_rounds_up_to_the_cent() -> None:
    assert rules.prices_from_cost(D("61.30"), MARKUP).box == D("76.63")


@pytest.mark.parametrize(
    ("cost", "next_cost", "sales", "difference", "profit"),
    [
        (D(60), D(63), D(75), D(3), D(12)),
        (D(60), D(58), D(75), D(-2), D(17)),
        (D(60), D(63), D("74.42"), D(3), D("11.42")),
    ],
)
def test_part4_next_box_profit(cost: D, next_cost: D, sales: D, difference: D, profit: D) -> None:
    figures = rules.box_profit(sales, cost, next_cost)
    assert figures.difference == difference
    assert figures.final_cost == next_cost
    assert figures.profit == profit


@pytest.mark.parametrize(
    ("usd", "bs"),
    [
        (D("75.00"), D("65842.50")),
        (D("6.25"), D("5486.88")),
        (D("3.15"), D("2765.39")),
        (D("0.21"), D("184.36")),
    ],
)
def test_part6_price_list_in_bolivares(usd: D, bs: D) -> None:
    assert rules.to_bs(usd, D("877.90")) == bs


def test_part6_bolivares_to_dollars() -> None:
    assert rules.to_usd(D("21947.50"), D("877.90")) == D("25.00")


def test_part9_bolivares_round_to_nearest_cent() -> None:
    assert rules.to_bs(D("19.59"), D("876.80")) == D("17176.51")
    assert rules.to_bs(D("13.13"), D("878.40")) == D("11533.39")


def test_part7_broken_eggs_loss_and_percent() -> None:
    assert rules.broken_loss(3, D(60)) == D("0.50")
    assert rules.broken_percent(3) == D("0.8")


def test_part5_weighted_average_cost() -> None:
    whole = rules.average_box_cost([(D(60), 360), (D(60), 360), (D(65), 360), (D(65), 360)])
    assert whole == D("62.5")
    after_selling_one = rules.average_box_cost([(D(60), 360), (D(65), 360), (D(65), 360)])
    assert rules.round_cents(after_selling_one or D(0)) == D("63.33")


def test_average_cost_weighs_partial_boxes_by_eggs_left() -> None:
    assert rules.average_box_cost([(D(60), 180), (D(66), 360)]) == D(64)
    assert rules.average_box_cost([]) is None


def test_part8_partner_split() -> None:
    assert rules.split_shares(D("12.00"), [D("0.60"), D("0.40")]) == [D("7.20"), D("4.80")]
    assert rules.split_shares(D("9.52"), [D("0.60"), D("0.40")]) == [D("5.71"), D("3.81")]


def test_split_cent_left_over_goes_to_the_largest_share() -> None:
    parts = rules.split_shares(D("1.00"), [D("0.3333"), D("0.3334"), D("0.3333")])
    assert parts == [D("0.33"), D("0.34"), D("0.33")]
    assert sum(parts) == D("1.00")


def test_split_by_eggs_puts_the_remainder_on_the_last_part() -> None:
    assert rules.split_by_weights(D("0.63"), [1, 2]) == [D("0.21"), D("0.42")]
    assert rules.split_by_weights(D("6.46"), [30, 1]) == [D("6.25"), D("0.21")]
    assert rules.split_by_weights(D("1.00"), [1, 1, 1]) == [D("0.33"), D("0.33"), D("0.34")]


def test_eggs_and_list_amount_of_mondays_sale() -> None:
    prices = rules.prices_from_cost(D(60), MARKUP)
    assert rules.eggs_in(3, 0, 4) == 94
    assert rules.list_amount(prices, 3, 0, 4) == D("19.59")


def test_fifo_takes_the_oldest_box_first() -> None:
    assert rules.allocate_fifo(31, [(1, 30), (2, 360)]) == [(1, 30), (2, 1)]
    assert rules.allocate_fifo(10, [(1, 0), (2, 360)]) == [(2, 10)]


def test_fifo_refuses_more_eggs_than_there_are() -> None:
    with pytest.raises(DomainError, match="quedan 30 huevos"):
        rules.allocate_fifo(31, [(1, 30)])
    with pytest.raises(DomainError, match="No hay huevos"):
        rules.allocate_fifo(1, [])


def test_stock_in_boxes_rounds_half_up() -> None:
    assert rules.boxes_equivalent(189) == D("0.53")
    assert rules.boxes_equivalent(266) == D("0.74")
    assert rules.boxes_equivalent(390) == D("1.08")


def test_box_state_machine() -> None:
    assert rules.box_status_for(360, has_movements=False) == BoxStatus.STOCKED
    assert rules.box_status_for(100, has_movements=True) == BoxStatus.OPEN
    assert rules.box_status_for(0, has_movements=True) == BoxStatus.FINISHED
    rules.check_box_transition(BoxStatus.FINISHED, BoxStatus.SETTLED)
    with pytest.raises(ValueError, match="settled"):
        rules.check_box_transition(BoxStatus.SETTLED, BoxStatus.OPEN)


def test_reserve() -> None:
    assert rules.reserve_amount(D("9.52"), None, D("0.10")) == D("0.95")
    assert rules.reserve_amount(D("9.52"), D("2.00"), None) == D("2.00")
    assert rules.reserve_amount(D("-1.90"), None, D("0.10")) == D("0.00")


def test_spanish_number_format() -> None:
    assert rules.format_usd(D("17176.5")) == "$ 17.176,50"
