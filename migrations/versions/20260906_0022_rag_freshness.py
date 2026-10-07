"""RAG cache freshness: indexed_at on knowledge sources (LEG-007)."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0022"
down_revision = "20260906_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_sources") as batch:
        batch.add_column(
            sa.Column(
                "indexed_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_sources") as batch:
        batch.drop_column("indexed_at")
