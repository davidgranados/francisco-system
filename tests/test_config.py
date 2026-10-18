import pytest
from pydantic import ValidationError

from app.config import DevUser, Settings, parse_dev_users


def test_dev_users_are_name_and_telegram_id_pairs() -> None:
    assert parse_dev_users("David:820460532, Otro:123 ,") == (
        DevUser("David", 820460532),
        DevUser("Otro", 123),
    )


@pytest.mark.parametrize("raw", ["", "   ", " , "])
def test_no_dev_users_when_blank(raw: str) -> None:
    assert parse_dev_users(raw) == ()
    assert Settings(dev_telegram_users=raw).dev_users == ()


@pytest.mark.parametrize(
    "raw",
    ["David", "David:", ":123", "David:abc", "David:-5", "David:0", "David:12.5", "A:1,B"],
)
def test_a_malformed_value_fails_at_startup_with_the_expected_shape(raw: str) -> None:
    with pytest.raises(ValidationError, match="DEV_TELEGRAM_USERS must look like"):
        Settings(dev_telegram_users=raw)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("David:1,david:2", "repeats a name"),
        ("David:1,Otro:1", "repeats a Telegram id"),
    ],
)
def test_names_and_ids_must_be_unique(raw: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(dev_telegram_users=raw)


def test_the_environment_variable_feeds_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_TELEGRAM_USERS", "David:820460532")
    assert Settings().dev_users == (DevUser("David", 820460532),)
