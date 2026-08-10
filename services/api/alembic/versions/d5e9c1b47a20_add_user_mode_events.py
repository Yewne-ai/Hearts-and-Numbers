"""add user_mode_events

偏好那一层的数据来源。只存三样：谁、什么时候、判成了什么模式——
不存对话内容，见 app/infra/models.py 里 UserModeEvent 的说明。

Revision ID: d5e9c1b47a20
Revises: c4f1a2d7b8e3
Create Date: 2026-08-09
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e9c1b47a20"
down_revision: Union[str, Sequence[str], None] = "c4f1a2d7b8e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_mode_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column(
            "classifier_version",
            sa.String(length=64),
            server_default="",
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # 偏好只查"某人最近 N 条"，复合索引正好覆盖这个模式。
    op.create_index(
        "ix_user_mode_events_user_time",
        "user_mode_events",
        ["user_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_mode_events_user_time", table_name="user_mode_events")
    op.drop_table("user_mode_events")
