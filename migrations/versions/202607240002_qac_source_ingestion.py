"""add source-only QAC morphology ingestion runs

Revision ID: 202607240002
Revises: 202607240001
"""
from alembic import op
import sqlalchemy as sa

revision = "202607240002"
down_revision = "202607240001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("morphology_ingestion_run", sa.Column("ingestion_kind", sa.String(40), nullable=False, server_default="alignment"))
    op.alter_column("morphology_ingestion_run", "quran_source_release_id", nullable=True)
    op.alter_column("morphology_ingestion_run", "alignment_configuration_id", nullable=True)
    op.alter_column("morphology_ingestion_run", "transliteration_profile_id", nullable=True)
    op.alter_column("morphology_ingestion_run", "feature_mapping_profile_id", nullable=True)
    op.create_index("uq_morphology_ingestion_completed_source_kind", "morphology_ingestion_run", ["annotation_source_release_id", "ingestion_kind"], unique=True, postgresql_where=sa.text("status = 'completed' and ingestion_kind = 'qac-source-parse-v1'"))


def downgrade():
    op.drop_index("uq_morphology_ingestion_completed_source_kind", table_name="morphology_ingestion_run")
    op.alter_column("morphology_ingestion_run", "feature_mapping_profile_id", nullable=False)
    op.alter_column("morphology_ingestion_run", "transliteration_profile_id", nullable=False)
    op.alter_column("morphology_ingestion_run", "alignment_configuration_id", nullable=False)
    op.alter_column("morphology_ingestion_run", "quran_source_release_id", nullable=False)
    op.drop_column("morphology_ingestion_run", "ingestion_kind")
