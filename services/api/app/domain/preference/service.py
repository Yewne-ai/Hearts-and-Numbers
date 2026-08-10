"""从历史判定算出用户偏向——2026-08-09。

**纯函数,不碰数据库。** 存储那层等 Postgres 起来了再接（现在
`PERSISTENCE_ENABLED=false`，一条历史都存不下来）。先把逻辑写对并测掉，
接上去只是把 events 换成从表里读。

设计上刻意保守：宁可判成"看不出倾向"，也不要凭三条记录给人贴标签。
贴错了的代价是持续的——每一轮都按错的倾向回应，而用户不会知道为什么。
"""

from collections import Counter

from app.domain.preference.schemas import (
    LEAN_MIN_GAP,
    LEAN_MIN_SHARE,
    LEANABLE_MODES,
    MIN_EVENTS_FOR_LEAN,
    Lean,
    ModeEvent,
    ModePreference,
)
from app.domain.conversation.modes import ResponseMode


def compute_preference(events: list[ModeEvent]) -> ModePreference:
    """把一串历史判定压成一个倾向。

    三道闸，任何一道不过就返回 NONE：
      1. 可计数的事件够不够（crisis/concern/unclear 都不算数）
      2. 最高的那一类占比够不够
      3. 它和第二名拉开的差距够不够

    第 3 道是防"两类几乎持平"——那种情况下选谁都是抛硬币，不如不选。
    """
    counts: Counter[ResponseMode] = Counter()
    for event in events:
        if event.mode in LEANABLE_MODES:
            counts[event.mode] += 1

    tallied = {m: counts.get(m, 0) for m in LEANABLE_MODES}
    total = sum(tallied.values())
    if total < MIN_EVENTS_FOR_LEAN:
        return ModePreference(counts=tallied, lean=Lean.NONE)

    ranked = sorted(tallied.items(), key=lambda kv: kv[1], reverse=True)
    (top_mode, top_n), (_, second_n) = ranked[0], ranked[1]

    if top_n / total < LEAN_MIN_SHARE or top_n - second_n < LEAN_MIN_GAP:
        return ModePreference(counts=tallied, lean=Lean.NONE)

    return ModePreference(counts=tallied, lean=Lean(top_mode.value))


def should_personalize(mode: ResponseMode) -> bool:
    """这一轮允不允许用偏好调整回应。

    第一版只在 unclear 上生效——那本来就是"我不知道"，用历史补一手是正当的，
    不覆盖任何确定的判断，最坏也只是问错方向。

    其余模式一律不动：判定是确定的，就该按判定回，不该被历史带偏。
    crisis / concern 更是硬性排除（见 schemas 里的说明）。
    """
    return mode is ResponseMode.UNCLEAR
