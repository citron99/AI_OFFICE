"""Idempotent reindex identity without rewriting source/chunk tables."""

import sqlalchemy as sa
from alembic import op

revision = "20260827_0005"
down_revision = "20260827_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable lineage: historical rows remain unchanged. Source deletion has no API.
    # Avoid SQLite batch table recreation: existing source FKs may cascade to chunks.
    op.add_column("knowledge_sources", sa.Column("reindex_of_id", sa.String(40), nullable=True))
    op.create_index(
        "uq_knowledge_reindex_target",
        "knowledge_sources",
        ["reindex_of_id", "embedding_model", "embedding_dimensions"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_knowledge_reindex_target", table_name="knowledge_sources")
    op.drop_column("knowledge_sources", "reindex_of_id")
