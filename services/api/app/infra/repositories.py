"""用户、会话和消息的数据访问层。"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.models import Conversation, Message, User, UserModeEvent


class UserRepository:
    """封装用户查询、创建和数据授权更新。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_external_id(self, external_id: str) -> User | None:
        """根据前端匿名标识查询用户。"""
        statement = select(User).where(User.external_id == external_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_phone_number(self, phone_number: str) -> User | None:
        """根据手机号查询用户（登录用：手机号已绑定过就认那个老用户）。"""
        statement = select(User).where(User.phone_number == phone_number)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_or_create(self, external_id: str) -> User:
        """返回已有用户；不存在时创建但不提交事务。"""
        user = await self.get_by_external_id(external_id)
        if user is not None:
            return user

        user = User(external_id=external_id)
        self._session.add(user)
        await self._session.flush()
        return user

    async def set_data_consent(
        self,
        user: User,
        *,
        granted: bool,
        version: str | None,
    ) -> User:
        """更新用户的数据授权状态，但不提交事务。"""
        user.data_consent = granted
        user.consent_version = version if granted else None
        user.consented_at = datetime.now(UTC) if granted else None
        await self._session.flush()
        return user


class ConversationRepository:
    """封装聊天会话的创建和按用户查询。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: UUID,
        persona: str = "nini",
    ) -> Conversation:
        """创建会话但不提交事务。"""
        conversation = Conversation(
            user_id=user_id,
            persona=persona,
        )
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def take_deletion_hint(self, conversation: Conversation) -> bool:
        """这个会话欠不欠一句"可以删"。**读到就清掉**——读和清是一个操作，
        分开写迟早会出现读了没清、于是每轮都提的情况。
        """
        owed = conversation.owes_deletion_hint
        if owed:
            conversation.owes_deletion_hint = False
            await self._session.flush()
        return owed

    async def mark_deletion_hint_owed(self, conversation: Conversation) -> None:
        conversation.owes_deletion_hint = True
        await self._session.flush()

    async def mark_safety_locked(
        self, conversation: Conversation, risk_level: str
    ) -> None:
        """锁住会话并记下等级。只升不降——同一个会话里后来的普通对话
        不该把已经识别出的危机抹掉。"""
        conversation.safety_locked = True
        conversation.risk_level = risk_level
        await self._session.flush()

    async def get_for_user(
        self,
        conversation_id: UUID,
        user_id: UUID,
    ) -> Conversation | None:
        """按会话和用户共同查询，避免读取其他用户的会话。"""
        statement = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def trim_for_user(self, user_id: UUID, *, keep: int = 7) -> None:
        """只保留用户最近的若干次浏览器会话。"""
        stale_ids = (
            select(Conversation.id)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
            .offset(keep)
        )
        await self._session.execute(
            delete(Conversation).where(Conversation.id.in_(stale_ids))
        )

    async def list_ended_for_user(self, user_id: UUID) -> list[Conversation]:
        """列出用户已结束归档的轮次，最新的在前。进行中的当前轮不出现在这里。"""
        statement = (
            select(Conversation)
            .where(Conversation.user_id == user_id, Conversation.ended_at.is_not(None))
            .order_by(Conversation.ended_at.desc())
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())


class MessageRepository:
    """封装消息写入和最近消息查询。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        conversation_id: UUID,
        role: Literal["user", "assistant"],
        content: str,
        safety_flag: str = "ok",
        emotion: str | None = None,
        request_id: str | None = None,
        is_mock: bool = False,
        degraded: bool = False,
    ) -> Message:
        """创建一条消息但不提交事务。"""
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            safety_flag=safety_flag,
            emotion=emotion,
            request_id=request_id,
            is_mock=is_mock,
            degraded=degraded,
            created_at=datetime.now(UTC),
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def list_recent(
        self,
        conversation_id: UUID,
        *,
        limit: int = 20,
    ) -> list[Message]:
        """按时间顺序返回会话最近的消息。"""
        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        messages = list(result.scalars().all())
        messages.reverse()
        return messages

    async def list_all(self, conversation_id: UUID) -> list[Message]:
        """按时间顺序返回某一轮的完整消息（不截断），用于历史轮次回看。"""
        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())


class UserModeEventRepository:
    """回应模式的落库与回读。偏好那一层唯一的数据来源。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self, *, user_id: UUID, mode: str, classifier_version: str
    ) -> None:
        """记一次判定。不提交事务——和这一轮的消息写在同一个事务里，
        要么都成要么都不成，避免出现"有回复没记录"的半截状态。
        """
        self._session.add(
            UserModeEvent(
                user_id=user_id,
                mode=mode,
                classifier_version=classifier_version,
            )
        )
        await self._session.flush()

    async def recent_for_user(self, user_id: UUID, limit: int = 50) -> list[UserModeEvent]:
        """取最近 N 条，新的在前。

        limit 默认 50 而不是全量：偏好只看近期倾向，而且一个长期用户的
        历史可能有几千条，全读回来算三个计数是浪费。
        """
        statement = (
            select(UserModeEvent)
            .where(UserModeEvent.user_id == user_id)
            .order_by(UserModeEvent.occurred_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())
