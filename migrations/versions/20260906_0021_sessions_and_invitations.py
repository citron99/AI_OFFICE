"""Durable sessions: refresh tokens and invitations (TZ 10.1)."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0021"
down_revision = "20260906_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.String(40), nullable=False),
        sa.Column("company_id", sa.String(40), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_to", sa.String(40), nullable=True),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_company_id", "refresh_tokens", ["company_id"])
    op.create_table(
        "invitations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("company_id", sa.String(40), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("invited_by", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "email", name="uq_invitation_company_email"),
    )
    op.create_index("ix_invitations_company_id", "invitations", ["company_id"])
    op.create_index("ix_invitations_email", "invitations", ["email"])


def downgrade() -> None:
    op.drop_index("ix_invitations_email", table_name="invitations")
    op.drop_index("ix_invitations_company_id", table_name="invitations")
    op.drop_table("invitations")
    op.drop_index("ix_refresh_tokens_company_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
