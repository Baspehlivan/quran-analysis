"""add read-only morphology query lookup indexes

Revision ID: 202607240004
Revises: 202607240003
"""
from alembic import op

revision = "202607240004"
down_revision = "202607240003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_text_unit_source_surah_ayah", "text_unit", ["source_release_id", "surah_number", "ayah_number"])
    op.create_index("ix_qac_alignment_source_token", "qac_morphology_alignment", ["annotation_source_release_id", "orthographic_token_id"])


def downgrade():
    op.drop_index("ix_qac_alignment_source_token", table_name="qac_morphology_alignment")
    op.drop_index("ix_text_unit_source_surah_ayah", table_name="text_unit")
