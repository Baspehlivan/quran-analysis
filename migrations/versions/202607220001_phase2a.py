"""phase2a normalized token provenance

Revision ID: 202607220001
Revises: 202607210001
Create Date: 2026-07-22 00:01:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "202607220001"
down_revision = "202607210001"
branch_labels = None
depends_on = None

json_type = postgresql.JSONB(astext_type=sa.Text())


def upgrade():
    op.add_column("normalized_token", sa.Column("profile_configuration_sha256", sa.String(64), nullable=False, server_default=""))
    op.add_column("normalized_token", sa.Column("normalized_to_source_codepoint_ids_json", json_type, nullable=False, server_default="[]"))
    op.alter_column("normalized_token", "profile_configuration_sha256", server_default=None)
    op.alter_column("normalized_token", "normalized_to_source_codepoint_ids_json", server_default=None)


def downgrade():
    op.drop_column("normalized_token", "normalized_to_source_codepoint_ids_json")
    op.drop_column("normalized_token", "profile_configuration_sha256")
