import pytest

from carecircle.errors import ValidationError
from carecircle.parsing import parse_days


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, None),
        ("", None),
        ("daily", [0, 1, 2, 3, 4, 5, 6]),
        ("weekdays", [0, 1, 2, 3, 4]),
        ("weekends", [5, 6]),
        ("mon, wed and fri", [0, 2, 4]),
        (["Monday", 2, "SUN"], [0, 2, 6]),
        (3, [3]),
    ],
)
def test_parse_days(raw, expected):
    assert parse_days(raw) == expected


@pytest.mark.parametrize("raw", ["funday", 9, [True], True])
def test_parse_days_invalid(raw):
    with pytest.raises(ValidationError):
        parse_days(raw)
