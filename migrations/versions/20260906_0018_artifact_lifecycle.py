"""Artifact lifecycle: provenance, retention and DLP metadata (ART-003)."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0018"
down_revision = "20260906_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("artifacts") as batch:
        batch.add_column(
            sa.Column(
                "source_provenance",
                sa.String(80),
                nullable=False,
                server_default="user_upload",
            )
        )
        batch.add_column(sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("dlp_rules", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("artifacts") as batch:
        batch.drop_column("dlp_rules")
        batch.drop_column("retention_until")
        batch.drop_column("source_provenance")
