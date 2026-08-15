"""Yewne 六宫三数法 v1 的确定性计算器。"""

from app.domain.reflection.schemas import (
    Palace,
    PositionName,
    PositionResult,
    ThreeNumberResult,
)

_PALACES = (
    Palace.DA_AN,
    Palace.LIU_LIAN,
    Palace.SU_XI,
    Palace.CHI_KOU,
    Palace.XIAO_JI,
    Palace.KONG_WANG,
)

_POSITIONS = (
    PositionName.ORIGIN,
    PositionName.PROCESS,
    PositionName.PRESENT,
)


class InvalidThreeNumbersError(ValueError):
    """三个数字不符合“恰好三个 1-99 整数”时抛出。"""


def _validate_numbers(numbers: tuple[object, ...]) -> tuple[int, int, int]:
    if len(numbers) != 3:
        raise InvalidThreeNumbersError("必须提供恰好三个数字")

    validated: list[int] = []
    for number in numbers:
        # bool 是 int 的子类，但不属于产品定义的数字输入。
        if type(number) is not int:
            raise InvalidThreeNumbersError("每个数字都必须是整数")
        # 下界是 1 而不是 0：用户「报三个数」从 1 起（§5.2），且 0 会让两端算不出
        # 同一个结果——Python 的 (0-1) % 6 == 5（空亡），JS 的 (0-1) % 6 == -1
        # （PALACES[-1] 为 undefined）。校验挡在入口，不依赖某一端的取模行为。
        if not 1 <= number <= 99:
            raise InvalidThreeNumbersError("每个数字都必须在 1 到 99 之间")
        validated.append(number)

    return validated[0], validated[1], validated[2]


def calculate_three_numbers(*numbers: object) -> ThreeNumberResult:
    """按包含起点的顺推规则计算“起势、过程、当下”三个宫位。"""

    n1, n2, n3 = _validate_numbers(numbers)

    r1 = (n1 - 1) % 6
    r2 = (r1 + n2 - 1) % 6
    r3 = (r2 + n3 - 1) % 6
    palaces = (_PALACES[r1], _PALACES[r2], _PALACES[r3])

    return ThreeNumberResult(
        numbers=(n1, n2, n3),
        result=palaces,
        positions=(
            PositionResult(name=_POSITIONS[0], palace=palaces[0]),
            PositionResult(name=_POSITIONS[1], palace=palaces[1]),
            PositionResult(name=_POSITIONS[2], palace=palaces[2]),
        ),
    )
