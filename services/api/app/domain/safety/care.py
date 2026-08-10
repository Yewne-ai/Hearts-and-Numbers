"""现实求助入口——对齐产品文档 8.5.2 / 8.6。

## 为什么把入口和回复分开

产品文档 8.4 要求 S2「进入安全确认流程」，也就是直接问一句；而 concern 块
写的是「不要说破」——他没打算讲，被点破只会否认，然后什么都不说了。

两边要的东西其实不冲突，冲突的是**由谁来问**：

    回复层    保持不说破，顺着他的话往下接（concern 块不变）
    界面层    旁边挂一个不打断的入口，用户想用就用

这样既不破坏对话，又能拿到 `ConfirmationBasis`——升级决策要它，而
「问了没回」和「主动说需要帮助」在文档 8.5.2 里是两种完全不同的依据。

## 号码放这里的原因

`400-161-9995` 原来硬编码在 `safety/rules.py` 和 `aftercare/service.py` 两处，
110/120/12356 只出现在注释里、从没进过响应数据。号码会变（12356 是 2024 年
才启用的全国统一号码），散在各处改不干净，而且前端拿不到就只能自己写死。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Hotline(BaseModel):
    """一个可直接拨打的现实求助号码。"""

    number: str
    label: str
    note: str = ""


# 文档 8.5.2 要求这些入口在 S2 以上**持续显示**，而且"无可用联系人时不伪装成
# 已求助"——也就是说它们不是备选方案，是任何情况下都在的底线。
HOTLINES: tuple[Hotline, ...] = (
    Hotline(
        number="12356",
        label="全国心理援助热线",
        note="24 小时，2024 年启用的全国统一号码",
    ),
    Hotline(number="110", label="报警", note="有即时人身危险时"),
    Hotline(number="120", label="急救", note="已经受伤或服药时"),
)

# 固定文案里用的那个号码。和上面分开是因为它出现在**文字内容**里，
# 不是可点击的入口——改文案和改入口是两件事。
CRISIS_TEXT_HOTLINE = "400-161-9995"


class CareLevel(str, Enum):
    """入口的显眼程度。不是风险等级——风险等级是 S0–S4，在 escalation 里。"""

    NONE = "none"  # 不显示
    QUIET = "quiet"  # 安静地摆在旁边，不打断（S2）
    PROMINENT = "prominent"  # 明确显示（S3 及以上、或会话已锁）


class CareAffordance(BaseModel):
    """告诉前端要不要显示现实求助入口、显示到什么程度。

    **不含任何原文或判断依据**——前端不需要知道我们为什么觉得他需要帮助，
    知道了也只会让界面上多出解释的冲动，而解释就是"说破"。
    """

    level: CareLevel = CareLevel.NONE
    hotlines: list[Hotline] = Field(default_factory=list)
    # 用户主动点了之后往哪儿回报。为空表示这一轮不需要收集确认。
    confirm_path: str = ""


_CONFIRM_PATH = "/v1/safety/confirm"


def affordance_for(*, risk_level: str, session_locked: bool) -> CareAffordance:
    """按风险等级决定入口的显眼程度。

    会话已锁时一律 PROMINENT——文档 8.6 里 Safety 是终态，这时候还把入口
    藏起来说不过去。
    """
    if session_locked or risk_level in ("S3", "S4"):
        return CareAffordance(
            level=CareLevel.PROMINENT,
            hotlines=list(HOTLINES),
            confirm_path=_CONFIRM_PATH,
        )
    if risk_level == "S2":
        # 安静地摆着。这一层的全部意义就是"不打断"——一旦它变成弹窗或者
        # 一句追问，就退化成了 concern 块特意避免的"说破"。
        return CareAffordance(
            level=CareLevel.QUIET,
            hotlines=list(HOTLINES),
            confirm_path=_CONFIRM_PATH,
        )
    return CareAffordance()
