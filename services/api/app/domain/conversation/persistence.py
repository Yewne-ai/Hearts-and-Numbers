"""会话持久化接口，隔离领域编排与具体数据库实现。"""

from typing import Protocol
from uuid import UUID

from app.domain.safety import SafetyReason


class ConversationPersistence(Protocol):
    """保存一轮完整对话。"""

    async def save_exchange(
        self,
        *,
        external_user_id: str,
        conversation_id: UUID | None,
        persona: str,
        user_text: str,
        reply: str,
        safety_flag: SafetyReason,
        emotion: str,
        request_id: str,
        is_mock: bool,
        degraded: bool,
        mode: str = "",
    ) -> UUID:
        """原子保存用户输入和助手回复，并返回实际会话 ID。

        `mode` 非空时顺带记一条 `user_mode_events`。放在同一个事务里是有意的——
        分开写会出现"有回复没记录"或反过来的半截状态，而偏好统计最怕的就是
        样本有系统性缺口（比如只有失败的那些轮次没记上）。
        """
        ...

    async def take_deletion_hint(
        self, *, external_user_id: str, conversation_id: UUID | None
    ) -> bool:
        """这个会话欠不欠一句"可以删"（用户上一轮要求过保密）。

        **读到就清**——只提一次。见 domain/safety/privacy.py。
        """
        ...

    async def is_safety_locked(
        self, *, external_user_id: str, conversation_id: UUID | None
    ) -> bool:
        """这个会话是否已经因为危机被锁住（产品文档 8.4 的"停止普通陪伴"）。

        必须在生成回复**之前**查——`save_exchange` 是回复之后才写的，
        等到那时候再看就晚了，这一轮已经按正常聊天回过去了。
        """
        ...

    async def lock_for_safety(
        self, *, external_user_id: str, conversation_id: UUID, risk_level: str
    ) -> None:
        """把会话标记成危机状态。**不提供解锁**——见 models.py 里的说明：
        不该由模型判断"他现在好些了"来解除。"""
        ...
