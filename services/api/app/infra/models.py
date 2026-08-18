"""用于持久化用户、会话和消息的 SQLAlchemy ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    false,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """所有 ORM 模型的共同基类。"""


class User(Base):
    """Yewne 用户及其数据授权状态；当前支持匿名用户标识。"""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    # argon2 哈希串（自带盐和参数）。为空表示这个用户还没设过密码，只能用验证码登录。
    password_hash: Mapped[str | None] = mapped_column(String(255))
    data_consent: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    consent_version: Mapped[str | None] = mapped_column(String(32))
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Conversation(Base):
    """属于某位用户的一次聊天会话。"""

    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # [2026-08-03] 场景分类已移除，新对话不再写这一列。保留是因为历史数据里有值，
    # 且删列需要一次不可逆 migration——没有收益，等确认没人再查历史 scene 时再删。
    scene: Mapped[str | None] = mapped_column(String(32))
    # 会话级安全状态——对齐产品文档 8.4 / 8.6 / 8.8。
    #
    # 为什么必须是会话级而不是每轮独立：文档 8.4 对 S3 的要求是"停止普通陪伴"，
    # 8.6 状态机的终点是"结束普通 AI 服务"。逐轮无状态做不到这件事——
    # 用户下一句说别的，就又回到正常聊天了，等于那次识别白做。
    risk_level: Mapped[str] = mapped_column(
        String(2), nullable=False, default="S0", server_default="S0"
    )
    # 用户上一轮要求过保密。下一轮回复末尾要提一句"可以删"，提完就清掉——
    # 只提一次，重复提是唠叨，而且会让人觉得我们在推卸。
    # 见 domain/safety/privacy.py。
    owes_deletion_hint: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # 锁上之后这个会话不再进 LLM，每轮都回固定文案 + 现实求助入口。
    # **不自动解锁**：文档 8.6 里 Safety 是终态。用户想继续聊可以开新会话，
    # 但不该由模型判断"他现在好些了"来解除——那正是最不该让模型决定的事。
    safety_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    persona: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="nini",
        server_default="nini",
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mood: Mapped[str | None] = mapped_column(String(16))
    letter: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    """会话中的一条用户消息或助手消息。"""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_messages_role",
        ),
        Index(
            "ix_messages_conversation_created_at",
            "conversation_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    safety_flag: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="ok",
        server_default="ok",
    )
    emotion: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    is_mock: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    degraded: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class TodoItem(Base):
    """内部工作看板的待办项，供产品/设计/商业查看 IT 现阶段进度。"""

    __tablename__ = "todo_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'in_progress', 'done')",
            name="ck_todo_items_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="open",
        server_default="open",
    )
    position: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class FeedbackItem(Base):
    """产品/设计/商业提交的需求或 bug 反馈。"""

    __tablename__ = "feedback_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('new', 'triaged', 'done')",
            name="ck_feedback_items_status",
        ),
        CheckConstraint(
            "kind IN ('bug', 'feature', 'other')",
            name="ck_feedback_items_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    author_name: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="other",
        server_default="other",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="new",
        server_default="new",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserModeEvent(Base):
    """每轮判出的回应模式。**只记不用**——先攒分布，等有量了再看。

    见 domain/preference/：这张表是偏好那一层唯一的数据来源。

    ## 为什么不存对话内容

    偏好只需要"这个人通常想要什么形状的回应"，不需要知道他说了什么。
    三列就够，合规门槛比存内容低一个量级——这个克制是有意的，
    不要因为"顺便也存一下"就把它变成第二份聊天记录。

    ## 危险类也记，但不参与偏好

    crisis / concern 会写进来（分布本身要看），但
    `domain/preference/schemas.py` 的 LEANABLE_MODES 把它们排除在统计之外。
    一个反复陷入危机的人不该被贴标签然后区别对待。
    """

    __tablename__ = "user_mode_events"
    __table_args__ = (
        # 偏好只查"某人最近 N 条"，这个复合索引正好覆盖。
        Index(
            "ix_user_mode_events_user_time",
            "user_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    # 分类器版本——判据一改，旧数据的含义就变了，混在一起统计会得出错的倾向。
    # 文档 10.4 也要求线上异常能追溯到具体版本。
    classifier_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", server_default=""
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
