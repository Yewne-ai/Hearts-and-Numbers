"""回应模式：系统推断的 ResponseMode 与用户自选的 ChatMode。

## 为什么两个枚举放在一起，而且放在 domain 而不是 llm

它们是**领域概念**，不是某个模型供应商的实现细节：`ChatMode` 直接对应产品文档
8.8 数据模型里的 `CONVERSATION.mode`，`ResponseMode` 决定回复形状并被
`domain/preference` 当作观测单位。换掉 DeepSeek 它们一个字都不用改。

依赖方向因此是干净的——**类型往里，行为往外**：

    domain/conversation/modes.py   ← llm/classifier_v2.py（判）
                                   ← llm/mode_blocks.py（拼 prompt）
                                   ← domain/preference（统计）

`classifier_v2.py` 原来的 docstring 里就写了"v2 胜出后再搬去 schemas"，
2026-08-09 v2 接进主链路、对齐产品文档之后，那个"以后"到了。

## 两者的关系（别混）

    用户选了 ChatMode  →  听用户的，推断结果完全不参与
    用户没选           →  用推断的 ResponseMode

有重叠但不等价，也不该合并成一个枚举——合并之后"用户说的"和"我们猜的"
在同一个字段里分不开，而那个区分正是偏好那一层的观测基础
（见 domain/preference/schemas.py）。
"""

from enum import Enum


class ResponseMode(str, Enum):
    """用户这一刻想要的回应类型。

    单选而非多标签：它直接映射到一个 prompt 分支，分支必须选一个。
    （话题维度天然多标，所以 v2 把话题整个砍掉了，不在这里凑合。）
    """

    VENT = "vent"  # 倾诉：只想被听见，给建议是添堵
    ADVICE = "advice"  # 求解：想要具体办法
    VALIDATE = "validate"  # 求认同：想确认"我这样想不过分吧"
    CRISIS = "crisis"  # 危机：明确的自伤/自杀表达或决意，走谨慎路径
    CONCERN = "concern"  # 疑似：情境暗示型的危险信号，收住语气 + 轻轻确认
    UNCLEAR = "unclear"  # 判不了：信息不足，下游应该先问一句


class ChatMode(str, Enum):
    """用户在深聊页主动选择的模式。取值与产品文档 8.8 的 CONVERSATION.mode 一致。"""

    LISTEN = "listen"  # 只听我说
    CLARIFY = "clarify"  # 帮我理清
    REFRAME = "reframe"  # 帮我换个角度
    ACT = "act"  # 陪我做下一步


# ── 版本号与风险等级映射：对齐产品文档 10.4 / 8.4 ────────────────────
#
# 文档 10.4 要求每次线上异常都能追溯到具体版本，`risk_classifier_version`
# 是必须记录的字段之一。改判据就要改这里，否则日志里分不清是哪一版判的。
RISK_CLASSIFIER_VERSION = "response-mode-v2.2026-08-09"

# 文档 8.4 定义了 S0–S4 五级风险，安全状态机（8.6）和紧急短信（8.5）都按这个走。
# 我们的两级要映射过去，不能自成一套——否则下游拿到 "crisis" 不知道该走哪条。
#
# 对不齐的地方，明确记下来：
# - S1（明显低落）我们不单独判。vent 里包含了它，但产品对 S1 的要求是
#   "温和确认状态 + 鼓励现实支持 + 缩短对话"，vent 块只做了第一件。
# - S4（正在发生：已服药、流血、在危险地点）**单句判不出来**，需要跨轮状态
#   和明确的现实信号。我们最高只到 S3，不要假装能判 S4。
_RISK_LEVELS: dict[ResponseMode, str] = {
    ResponseMode.CRISIS: "S3",  # 明确说出自伤意图或决意
    ResponseMode.CONCERN: "S2",  # 模糊自伤暗示——文档 S2 的定义就是这个
}


def risk_level_for(mode: ResponseMode) -> str:
    """把回应模式映射到产品文档 8.4 的 S0–S4。非危险类一律 S0。

    注意上限是 S3：S4 要靠跨轮状态和现实信号判定，单句分类器给不出。
    """
    return _RISK_LEVELS.get(mode, "S0")
