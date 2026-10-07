"""Legal KB metadata and fixed-version pilot vectors."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "20260827_0003"
down_revision = "20260827_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_sources",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("artifact_id", sa.String(40), sa.ForeignKey("artifacts.id"), nullable=False),
        sa.Column("owner_id", sa.String(40), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("jurisdiction", sa.String(2), nullable=False),
        sa.Column("document_type", sa.String(255), nullable=False),
        sa.Column("authority", sa.String(255), nullable=False),
        sa.Column("version", sa.String(255), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.String(100), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
    )
    for column in ("artifact_id", "owner_id", "jurisdiction"):
        op.create_index(f"ix_knowledge_sources_{column}", "knowledge_sources", [column])
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(40),
            sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("locator", sa.String(255), nullable=False),
        sa.Column("page", sa.Integer()),
        sa.Column("article", sa.String(255)),
        sa.Column("embedding", Vector(128).with_variant(sa.JSON(), "sqlite"), nullable=False),
    )
    op.create_index("ix_knowledge_chunks_source_id", "knowledge_chunks", ["source_id"])


def downgrade() -> None:
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_sources")
    # vector extension can be shared with other applications; do not remove it.
