"""用户回应偏好的数据结构——2026-08-09。

## 这一层要解决什么

同一句"在吗",对一个聊过二十轮的老用户和一个第一次来的人，不该问出同样的话。
但"记住偏好"这件事很容易做成回音室，所以这里的设计有几条硬约束：

1. **只调回应，不调检测。** mode 永远是当轮的真实判断，偏好不参与分类。
   一旦让先验去影响判定，记录下来的就不再是"用户想要什么"，而是"我们猜他想要
   什么"，唯一的观测渠道就被污染了，以后连回头分析都做不了。
2. **crisis / concern 永不参与。** 见 `LEANABLE_MODES`——它们既不计入偏好，
   也不受偏好影响。不管这个人历史上多少次只是抱怨，危险信号一视同仁。
3. **样本不够就不倾斜。** 三条记录看不出人格，只看得出巧合。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.domain.conversation.modes import ResponseMode

# 只有这三类计入偏好。
# - unclear 排除：它是"没有信号"，不是一种偏好。把它计进去会让沉默的用户
#   越来越被当成沉默的用户。
# - crisis / concern 排除：安全类不参与任何个性化，这条是硬线。
LEANABLE_MODES: tuple[ResponseMode, ...] = (
    ResponseMode.VENT,
    ResponseMode.ADVICE,
    ResponseMode.VALIDATE,
)

# 低于这个数一律不倾斜。10 是拍的——目的是挡住"前三轮碰巧都在倾诉"这种噪声，
# 有真实数据之后应该重新定。
MIN_EVENTS_FOR_LEAN = 10

# 最高的那一类要占到这个比例、且比第二名多这么多，才算真的有倾向。
# 三类均分是 33%，45% 是"明显偏向但不至于苛刻"的位置。
LEAN_MIN_SHARE = 0.45
LEAN_MIN_GAP = 3


class Lean(str, Enum):
    """这个用户偏向要什么样的回应。NONE 表示还看不出来或没有明显偏向。"""

    NONE = "none"
    VENT = "vent"
    ADVICE = "advice"
    VALIDATE = "validate"


@dataclass(frozen=True)
class ModeEvent:
    """一次判定的记录。只记不用——先攒着，等有量了再看分布。"""

    external_user_id: str
    mode: ResponseMode
    occurred_at: datetime


@dataclass(frozen=True)
class ModePreference:
    """某个用户的历史倾向。`counts` 只含 LEANABLE_MODES 里的三类。"""

    counts: dict[ResponseMode, int]
    lean: Lean

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @classmethod
    def empty(cls) -> ModePreference:
        return cls(counts={m: 0 for m in LEANABLE_MODES}, lean=Lean.NONE)
