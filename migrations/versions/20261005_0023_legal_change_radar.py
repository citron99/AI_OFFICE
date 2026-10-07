"""Legal Change Radar runs and append-only human reviews."""

import sqlalchemy as sa
from alembic import op

revision = "20261005_0023"
down_revision = "20260906_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legal_change_radar_runs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("company_id", sa.String(40), nullable=False),
        sa.Column("owner_id", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "baseline_source_id",
            sa.String(40),
            sa.ForeignKey("knowledge_sources.id"),
            nullable=False,
        ),
        sa.Column(
            "current_source_id",
            sa.String(40),
            sa.ForeignKey("knowledge_sources.id"),
            nullable=False,
        ),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.String(2), nullable=False),
        sa.Column("effective_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("company_id", "idempotency_key", name="uq_legal_radar_idempotency"),
    )
    op.create_index(
        "ix_legal_change_radar_runs_company_id", "legal_change_radar_runs", ["company_id"]
    )
    op.create_index("ix_legal_change_radar_runs_owner_id", "legal_change_radar_runs", ["owner_id"])
    op.create_index(
        "ix_legal_change_radar_runs_baseline_source_id",
        "legal_change_radar_runs",
        ["baseline_source_id"],
    )
    op.create_index(
        "ix_legal_change_radar_runs_current_source_id",
        "legal_change_radar_runs",
        ["current_source_id"],
    )
    op.create_index(
        "ix_legal_change_radar_runs_jurisdiction", "legal_change_radar_runs", ["jurisdiction"]
    )
    op.create_index("ix_legal_change_radar_runs_status", "legal_change_radar_runs", ["status"])
    op.create_table(
        "legal_change_radar_reviews",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(40),
            sa.ForeignKey("legal_change_radar_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company_id", sa.String(40), nullable=False),
        sa.Column("reviewer_id", sa.String(40), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("run_id", name="uq_legal_radar_review_run"),
    )
    op.create_index(
        "ix_legal_change_radar_reviews_run_id", "legal_change_radar_reviews", ["run_id"]
    )
    op.create_index(
        "ix_legal_change_radar_reviews_company_id", "legal_change_radar_reviews", ["company_id"]
    )
    op.create_index(
        "ix_legal_change_radar_reviews_reviewer_id", "legal_change_radar_reviews", ["reviewer_id"]
    )


def downgrade() -> None:
    op.drop_table("legal_change_radar_reviews")
    op.drop_table("legal_change_radar_runs")
