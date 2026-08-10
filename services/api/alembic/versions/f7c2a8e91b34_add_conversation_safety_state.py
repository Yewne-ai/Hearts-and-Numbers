"""给 conversations 加会话级安全状态

对齐产品文档 8.4 / 8.6：S3 之后要"停止普通陪伴"，而逐轮无状态做不到——
用户下一句说别的就又回到正常聊天了。

Revision ID: f7c2a8e91b34
Revises: d5e9c1b47a20
Create Date: 2026-08-10
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7c2a8e91b34"
down_revision: Union[str, Sequence[str], None] = "d5e9c1b47a20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "risk_level", sa.String(length=2), server_default="S0", nullable=False
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "safety_locked",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "safety_locked")
    op.drop_column("conversations", "risk_level")
