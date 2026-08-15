"""三数问心确定性计算器测试。"""

import pytest

from app.domain.reflection import (
    INPUT_RULE_VERSION,
    METHOD_VERSION,
    InvalidThreeNumbersError,
    Palace,
    PositionName,
    calculate_three_numbers,
)


@pytest.mark.parametrize(
    ("numbers", "expected"),
    [
        ((1, 1, 1), (Palace.DA_AN, Palace.DA_AN, Palace.DA_AN)),
        ((2, 5, 2), (Palace.LIU_LIAN, Palace.KONG_WANG, Palace.DA_AN)),
        ((6, 6, 6), (Palace.KONG_WANG, Palace.XIAO_JI, Palace.CHI_KOU)),
        ((3, 3, 3), (Palace.SU_XI, Palace.XIAO_JI, Palace.DA_AN)),
        ((99, 99, 99), (Palace.SU_XI, Palace.XIAO_JI, Palace.DA_AN)),
    ],
)
def test_calculate_three_numbers_matches_golden_cases(
    numbers: tuple[int, int, int],
    expected: tuple[Palace, Palace, Palace],
) -> None:
    result = calculate_three_numbers(*numbers)

    assert result.result == expected


def test_result_uses_fixed_method_and_position_names() -> None:
    result = calculate_three_numbers(2, 5, 2)

    assert result.method_version == METHOD_VERSION
    assert result.input_rule_version == INPUT_RULE_VERSION
    assert result.numbers == (2, 5, 2)
    assert tuple(position.name for position in result.positions) == (
        PositionName.ORIGIN,
        PositionName.PROCESS,
        PositionName.PRESENT,
    )
    assert tuple(position.palace for position in result.positions) == result.result


@pytest.mark.parametrize("position", range(3))
def test_every_number_from_one_to_99_is_valid_in_each_position(position: int) -> None:
    for number in range(1, 100):
        numbers = [1, 1, 1]
        numbers[position] = number
        result = calculate_three_numbers(*numbers)

        assert result.numbers == tuple(numbers)
        assert len(result.result) == 3
        assert all(isinstance(palace, Palace) for palace in result.result)


def test_same_input_always_returns_the_same_result() -> None:
    for numbers in ((1, 1, 1), (6, 6, 6), (42, 17, 99), (99, 99, 99)):
        first = calculate_three_numbers(*numbers)
        second = calculate_three_numbers(*numbers)

        assert first == second


@pytest.mark.parametrize(
    "numbers",
    [
        (0, 2, 3),
        (2, 0, 3),
        (2, 3, 0),
        (-1, 2, 3),
        (100, 2, 3),
        (2.5, 3, 4),
        ("2", 3, 4),
        (True, 3, 4),
        (2, 3),
        (1, 2, 3, 4),
    ],
)
def test_invalid_inputs_are_rejected(numbers: tuple[object, ...]) -> None:
    with pytest.raises(InvalidThreeNumbersError):
        calculate_three_numbers(*numbers)
