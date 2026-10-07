"""Allow isolated model/dimension namespaces without deleting old vectors."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "20260827_0004"
down_revision = "20260827_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_sources",
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False, server_default="128"),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("knowledge_chunks", "embedding", type_=Vector(), existing_type=Vector(128))


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT count(*) FROM knowledge_sources WHERE embedding_dimensions != 128")
    ):
        raise RuntimeError("Non-128 vectors exist; downgrade would lose compatibility")
    if connection.dialect.name == "postgresql":
        op.alter_column("knowledge_chunks", "embedding", type_=Vector(128), existing_type=Vector())
    op.drop_column("knowledge_sources", "embedding_dimensions")
