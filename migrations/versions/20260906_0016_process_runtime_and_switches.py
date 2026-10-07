"""Runtime controls per process: autonomy ladder and kill switches (migration)."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0016"
down_revision = "20260906_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "process_runtime",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("company_id", sa.String(40), nullable=False),
        sa.Column("process_id", sa.String(80), nullable=False),
        sa.Column("autonomy_level", sa.String(30), nullable=False),
        sa.Column("process_enabled", sa.Boolean(), nullable=False),
        sa.Column("llm_enabled", sa.Boolean(), nullable=False),
        sa.Column("write_tools_enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.UniqueConstraint("company_id", "process_id", name="uq_runtime_company_proc"),
    )
    op.create_index("ix_process_runtime_company_id", "process_runtime", ["company_id"])
    op.create_index("ix_process_runtime_process_id", "process_runtime", ["process_id"])


def downgrade() -> None:
    op.drop_index("ix_process_runtime_process_id", table_name="process_runtime")
    op.drop_index("ix_process_runtime_company_id", table_name="process_runtime")
    op.drop_table("process_runtime")
