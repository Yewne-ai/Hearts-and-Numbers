"""高风险升级决策——对齐《三数问心 MVP 产品开发文档》8.4 / 8.5.2 / 8.6 / 8.8。

## 这个模块做什么、不做什么

**做**：给定风险等级、联系人状态、确认依据，算出该不该发紧急短信。纯函数，
可测，不碰网络也不碰数据库。

**不做**：真的发短信、读写联系人、落审计日志。那些要数据库和短信通道，
现在两个都没有——接口占位在 `ports.py`。

## 为什么决策逻辑要单独拎出来

文档 10.9 的工程执行规则写着：

> 风险状态机和短信触发**不得只存在于 Prompt 中**，必须由服务端确定性代码
> 和显式状态控制

所以这里一行模型调用都不能有。判等级是分类器的事（`llm/classifier_v2.py` +
`llm/danger_rules.py`），拿到等级之后怎么处置是这里的事，两件事分开。

## 一条贯穿的原则：不伪装

文档 8.5.2 明写「无可用联系人时**不伪装成"已求助"**」，8.5.3 又写
「短信不保证送达，也不代表已经完成现实援护」。所以这里所有"没做成"的分支
都必须返回一个能让前端如实显示的值，不能悄悄降级成看起来成功的样子。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ── 文档 8.4 的五级风险 ────────────────────────────────────────────────
# 分类器只给到 S3（见 llm/classifier_v2.py 的 risk_level_for）：
# S4 是"正在发生"，要靠跨轮状态和现实信号，单句判不出来。
RiskLevel = str  # "S0" | "S1" | "S2" | "S3" | "S4"

_LEVEL_ORDER: dict[str, int] = {"S0": 0, "S1": 1, "S2": 2, "S3": 3, "S4": 4}


class ContactStatus(str, Enum):
    """紧急联系人状态。取值同文档 8.8 的 EMERGENCY_CONTACT.status。"""

    NONE = "none"  # 用户没设置
    PENDING = "pending"  # 设了但联系人还没确认
    VERIFIED = "verified"  # 联系人已通过一次性链接确认
    UNAVAILABLE = "unavailable"  # 号码失效
    REVOKED = "revoked"  # 已撤回


class ConfirmationBasis(str, Enum):
    """凭什么认定的。取值同文档 8.8 的 RISK_EVENT.confirmation_basis。"""

    ANSWER = "answer"  # 用户回答了那句直接安全问题
    EXPLICIT_TEXT = "explicit_text"  # 原始文本本身已达高置信
    NO_RESPONSE = "no_response"  # 问了但没回


class NotificationDecision(str, Enum):
    """取值同文档 8.8 的 RISK_EVENT.notification_decision。"""

    NOTIFY = "notify"  # 创建通知任务
    NO_CONTACT = "no_contact"  # 没有可用联系人——**不能伪装成已求助**
    NOT_ELIGIBLE = "not_eligible"  # 风险等级或确认依据不够


@dataclass(frozen=True, slots=True)
class EscalationOutcome:
    """决策结果。`reason_code` 进 RISK_EVENT，**不含原文引用**（文档 8.8）。"""

    decision: NotificationDecision
    reason_code: str
    high_priority: bool = False  # S4 用，文档 8.5.2 要求"立即创建高优先级通知任务"
    show_direct_dial: bool = True  # 文档 8.5.2：任何情况下都持续显示一键拨号


# 联系人处于这些状态时，一律不发——文档 8.5.1 第 5 条。
_UNUSABLE = (
    ContactStatus.NONE,
    ContactStatus.PENDING,
    ContactStatus.UNAVAILABLE,
    ContactStatus.REVOKED,
)


def decide_notification(
    risk_level: RiskLevel,
    contact_status: ContactStatus,
    basis: ConfirmationBasis,
) -> EscalationOutcome:
    """该不该给紧急联系人发短信。文档 8.5.2 那张触发规则表的实现。

    判定顺序有讲究——先看等级够不够，再看依据成不成立，最后才看联系人。
    反过来的话，"没有联系人"会掩盖掉"等级本来就不该发"，日志里分不清是
    哪一步拦下的。
    """
    level = _LEVEL_ORDER.get(risk_level, 0)

    # S0–S2 一律不自动发送。S2 只做安全确认与现实求助引导（文档 8.5.2 第一行）。
    if level < _LEVEL_ORDER["S3"]:
        return EscalationOutcome(
            decision=NotificationDecision.NOT_ELIGIBLE,
            reason_code="below_s3",
        )

    # S3/S4 且用户明确表达后无响应：只有原始文本本身已达高置信才算数。
    # 文档 8.5.2 最后一行——"问了没回"不能单独作为依据，否则用户只是走开
    # 或者手机没电，就会惊动他的紧急联系人。
    if basis is ConfirmationBasis.NO_RESPONSE:
        return _with_contact(
            contact_status,
            reason_code="explicit_risk_no_response",
            high_priority=level >= _LEVEL_ORDER["S4"],
        )

    return _with_contact(
        contact_status,
        reason_code="confirmed_s4" if level >= _LEVEL_ORDER["S4"] else "confirmed_s3",
        high_priority=level >= _LEVEL_ORDER["S4"],
    )


def _with_contact(
    contact_status: ContactStatus, reason_code: str, high_priority: bool
) -> EscalationOutcome:
    """等级和依据都过了之后，只剩联系人这一关。"""
    if contact_status in _UNUSABLE:
        # 关键：这里返回 NO_CONTACT 而不是 NOT_ELIGIBLE。两者在日志里必须分得开——
        # 前者是"该发但没人可发"（要引导用户直接拨号），后者是"本来就不该发"。
        return EscalationOutcome(
            decision=NotificationDecision.NO_CONTACT,
            reason_code=f"{reason_code}_no_usable_contact",
        )
    return EscalationOutcome(
        decision=NotificationDecision.NOTIFY,
        reason_code=reason_code,
        high_priority=high_priority,
    )


def idempotency_key(risk_event_id: str, contact_id: str, template_version: str) -> str:
    """短信任务的幂等键。文档 10.2 指定的三元组。

    防的是"模型重试造成重复短信"——同一次风险事件重试多少遍，联系人只应该
    收到一条。缺了这个，一次网络抖动就会让人连收几条紧急通知。
    """
    return f"{risk_event_id}:{contact_id}:{template_version}"


def should_retry(retry_count: int) -> bool:
    """文档 8.5.2：短信失败最多重试一次（8.8 的 SMS_NOTIFICATION.retry_count
    也写着 "zero or one"）。

    不做指数退避、不做多次重试：紧急通知过了时效就没意义了，而重复打扰
    是实打实的伤害。失败之后要做的是如实告诉用户未送达，不是继续重试。
    """
    return retry_count < 1
