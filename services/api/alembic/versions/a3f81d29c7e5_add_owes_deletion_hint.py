"""给 conversations 加 owes_deletion_hint

用户要求保密时不当场解释数据政策（那等于在他要开口时打断他），
改成下一轮说完再提一句可以删。要跨轮记住，所以落一列。

见 app/domain/safety/privacy.py。

Revision ID: a3f81d29c7e5
Revises: f7c2a8e91b34
Create Date: 2026-08-11
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f81d29c7e5"
down_revision: Union[str, Sequence[str], None] = "f7c2a8e91b34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "owes_deletion_hint",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "owes_deletion_hint")
