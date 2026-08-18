"""基于 PostgreSQL 的会话持久化实现。"""

from uuid import UUID

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.conversation.modes import RISK_CLASSIFIER_VERSION
from app.domain.safety import SafetyReason
from app.domain.safety.privacy import asks_for_secrecy
from app.infra.repositories import (
    ConversationRepository,
    MessageRepository,
    UserModeEventRepository,
    UserRepository,
)

logger = structlog.get_logger(__name__)


class PostgresConversationPersistence:
    """使用同一事务保存用户、会话和一轮消息。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._conversations = ConversationRepository(session)
        self._messages = MessageRepository(session)
        self._mode_events = UserModeEventRepository(session)

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
        """保存整轮对话；任一步失败都会回滚本次事务。"""
        try:
            user = await self._users.get_or_create(external_user_id)
            if mode:
                await self._mode_events.record(
                    user_id=user.id,
                    mode=mode,
                    classifier_version=RISK_CLASSIFIER_VERSION,
                )
            conversation = None
            if conversation_id is not None:
                conversation = await self._conversations.get_for_user(
                    conversation_id,
                    user.id,
                )

            if conversation is None:
                conversation = await self._conversations.create(
                    user_id=user.id,
                    persona=persona,
                )
            else:
                conversation.persona = persona

            # 他这轮要求了保密 → 记下来，下一轮说完再提"可以删"。
            # 放在会话拿到之后：首轮时会话是上面才创建的。
            if asks_for_secrecy(user_text):
                await self._conversations.mark_deletion_hint_owed(conversation)

            await self._messages.create(
                conversation_id=conversation.id,
                role="user",
                content=user_text,
                safety_flag=safety_flag,
                emotion=emotion or None,
                request_id=request_id,
            )
            await self._messages.create(
                conversation_id=conversation.id,
                role="assistant",
                content=reply,
                safety_flag=safety_flag,
                request_id=request_id,
                is_mock=is_mock,
                degraded=degraded,
            )
            await self._conversations.trim_for_user(user.id, keep=7)
            await self._session.commit()
            return conversation.id
        except Exception:
            await self._session.rollback()
            raise

    async def take_deletion_hint(
        self, *, external_user_id: str, conversation_id: UUID | None
    ) -> bool:
        """取并清掉"欠一句可以删"的标记。读失败返回 False——
        提不提这一句不值得让请求失败，下一轮还有机会。
        """
        if conversation_id is None:
            return False
        try:
            user = await self._users.get_by_external_id(external_user_id)
            if user is None:
                return False
            conversation = await self._conversations.get_for_user(
                conversation_id, user.id
            )
            if conversation is None:
                return False
            owed = await self._conversations.take_deletion_hint(conversation)
            if owed:
                await self._session.commit()
            return owed
        except SQLAlchemyError as exc:
            logger.warning("deletion_hint_read_failed", error=str(exc))
            return False

    async def is_safety_locked(
        self, *, external_user_id: str, conversation_id: UUID | None
    ) -> bool:
        """查这个会话有没有被锁。首轮（没有 conversation_id）一定是 False。

        读失败一律返回 False——**不能因为数据库抖动就把正常会话锁住**。
        反过来的风险（漏掉一次锁定）由这一轮的分类器兜底：真危机会被重新识别。
        """
        if conversation_id is None:
            return False
        try:
            user = await self._users.get_by_external_id(external_user_id)
            if user is None:
                return False
            conversation = await self._conversations.get_for_user(
                conversation_id, user.id
            )
            return bool(conversation and conversation.safety_locked)
        except SQLAlchemyError as exc:
            logger.warning("safety_lock_read_failed", error=str(exc))
            return False

    async def lock_for_safety(
        self, *, external_user_id: str, conversation_id: UUID, risk_level: str
    ) -> None:
        """锁住会话。失败只记日志——这一轮的固定文案已经发出去了，
        锁不上最多是下一轮又走一遍识别，不该让它把请求搞失败。
        """
        try:
            user = await self._users.get_by_external_id(external_user_id)
            if user is None:
                return
            conversation = await self._conversations.get_for_user(
                conversation_id, user.id
            )
            if conversation is None:
                return
            await self._conversations.mark_safety_locked(conversation, risk_level)
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.warning("safety_lock_write_failed", error=str(exc))
