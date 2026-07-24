"""add immutable QAC-to-Tanzil alignment evidence

Revision ID: 202607240003
Revises: 202607240002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "202607240003"
down_revision = "202607240002"
branch_labels = None
depends_on = None
J = postgresql.JSONB(astext_type=sa.Text())


def upgrade():
    op.create_table("qac_alignment_run", sa.Column("id", sa.Integer, primary_key=True), sa.Column("annotation_source_release_id", sa.Integer, sa.ForeignKey("annotation_source_release.id"), nullable=False), sa.Column("morphology_ingestion_run_id", sa.Integer, sa.ForeignKey("morphology_ingestion_run.id"), nullable=False), sa.Column("quran_source_release_id", sa.Integer, sa.ForeignKey("source_release.id"), nullable=False), sa.Column("status", sa.String(40), nullable=False), sa.Column("algorithm_version", sa.String(80), nullable=False), sa.Column("statistics_json", J, nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("created_at", sa.DateTime, server_default=sa.text("now()"), nullable=False), sa.Column("completed_at", sa.DateTime), sa.UniqueConstraint("morphology_ingestion_run_id", "quran_source_release_id", "algorithm_version"))
    op.create_table("qac_morphology_alignment", sa.Column("id", sa.Integer, primary_key=True), sa.Column("alignment_run_id", sa.Integer, sa.ForeignKey("qac_alignment_run.id"), nullable=False), sa.Column("annotation_source_release_id", sa.Integer, sa.ForeignKey("annotation_source_release.id"), nullable=False), sa.Column("morphological_analysis_id", sa.Integer, sa.ForeignKey("morphological_analysis.id"), nullable=False), sa.Column("morphological_segment_id", sa.Integer, sa.ForeignKey("morphological_segment.id"), nullable=False), sa.Column("orthographic_token_id", sa.Integer, sa.ForeignKey("orthographic_token.id")), sa.Column("method", sa.String(40), nullable=False), sa.Column("status", sa.String(40), nullable=False), sa.Column("confidence", sa.Float, nullable=False), sa.Column("is_ambiguous", sa.Boolean, nullable=False), sa.Column("evidence_json", J, nullable=False), sa.UniqueConstraint("alignment_run_id", "morphological_segment_id", "orthographic_token_id", "method", name="uq_qac_alignment_segment_candidate"))
    op.create_index("ix_qac_alignment_run_segment", "qac_morphology_alignment", ["alignment_run_id", "morphological_segment_id"])
    op.execute("""create or replace function block_completed_qac_alignment() returns trigger as $$ begin if exists (select 1 from qac_alignment_run r where r.id = old.alignment_run_id and r.status = 'completed') then raise exception 'completed qac alignment evidence is immutable'; end if; return new; end; $$ language plpgsql; create trigger trg_qac_alignment_completed_immutable before update or delete on qac_morphology_alignment for each row execute function block_completed_qac_alignment();""")


def downgrade():
    op.execute("drop trigger if exists trg_qac_alignment_completed_immutable on qac_morphology_alignment; drop function if exists block_completed_qac_alignment();")
    op.drop_index("ix_qac_alignment_run_segment", table_name="qac_morphology_alignment")
    op.drop_table("qac_morphology_alignment")
    op.drop_table("qac_alignment_run")
