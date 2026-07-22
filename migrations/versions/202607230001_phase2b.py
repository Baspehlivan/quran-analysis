"""phase2b reproducibility and export integrity

Revision ID: 202607230001
Revises: 202607220001
Create Date: 2026-07-23 00:01:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "202607230001"
down_revision = "202607220001"
branch_labels = None
depends_on = None

json_type = postgresql.JSONB(astext_type=sa.Text())


def upgrade():
    op.create_table("environment_snapshot", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("content_hash", sa.String(64), nullable=False, unique=True), sa.Column("canonical_json", json_type, nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")))
    op.add_column("analysis_run", sa.Column("query_hash_algorithm_version", sa.String(40), nullable=True))
    op.add_column("analysis_run", sa.Column("evidence_hash", sa.String(64), nullable=True))
    op.add_column("analysis_run", sa.Column("evidence_hash_algorithm_version", sa.String(40), nullable=True))
    op.add_column("analysis_run", sa.Column("environment_snapshot_id", sa.Integer(), nullable=True))
    op.add_column("analysis_run", sa.Column("environment_snapshot_hash", sa.String(64), nullable=True))
    op.add_column("analysis_run", sa.Column("git_commit_hash", sa.String(64), nullable=True))
    op.add_column("analysis_run", sa.Column("git_dirty", sa.Boolean(), nullable=True))
    op.add_column("analysis_run", sa.Column("schema_revision", sa.String(40), nullable=True))
    op.create_foreign_key("fk_analysis_run_environment_snapshot", "analysis_run", "environment_snapshot", ["environment_snapshot_id"], ["id"])
    op.create_index("ix_analysis_run_query_hash", "analysis_run", ["query_hash"])
    op.create_index("ix_analysis_run_evidence_hash", "analysis_run", ["evidence_hash"])
    op.create_index("ix_analysis_run_source_scope", "analysis_run", ["source_release_id", "normalization_profile_id"])
    op.create_index("ix_analysis_evidence_run_order", "analysis_evidence", ["analysis_run_id", "result_index"])
    op.create_index("ix_analysis_evidence_lookup", "analysis_evidence", ["text_unit_id", "orthographic_token_id"])
    op.create_table("export_manifest", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("analysis_run_id", sa.Integer(), sa.ForeignKey("analysis_run.id"), nullable=False), sa.Column("path", sa.Text(), nullable=False), sa.Column("format", sa.String(20), nullable=False), sa.Column("export_schema_version", sa.String(40), nullable=False), sa.Column("export_file_sha256", sa.String(64), nullable=False), sa.Column("manifest_sha256", sa.String(64), nullable=False, unique=True), sa.Column("canonical_json", json_type, nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")))
    op.create_index("ix_export_manifest_run", "export_manifest", ["analysis_run_id"])
    op.create_check_constraint("ck_analysis_run_status", "analysis_run", "status in ('pending','running','completed','failed','cancelled')")
    op.execute('''
    create or replace function block_environment_snapshot_update() returns trigger as $$ begin raise exception 'environment_snapshot rows are immutable'; end; $$ language plpgsql;
    create or replace function block_normalization_profile_update() returns trigger as $$ begin if OLD.is_frozen and (OLD.configuration_json is distinct from NEW.configuration_json or OLD.configuration_sha256 is distinct from NEW.configuration_sha256 or OLD.name is distinct from NEW.name or OLD.version is distinct from NEW.version) then raise exception 'frozen normalization_profile rows are immutable'; end if; return NEW; end; $$ language plpgsql;
    create or replace function block_query_scope_definition_update() returns trigger as $$ begin if OLD.is_frozen and (OLD.configuration_json is distinct from NEW.configuration_json or OLD.configuration_sha256 is distinct from NEW.configuration_sha256 or OLD.name is distinct from NEW.name or OLD.version is distinct from NEW.version) then raise exception 'frozen query_scope_definition rows are immutable'; end if; return NEW; end; $$ language plpgsql;
    create or replace function block_analysis_run_completed_update() returns trigger as $$ begin if OLD.status = 'completed' and (OLD.query_hash is distinct from NEW.query_hash or OLD.evidence_hash is distinct from NEW.evidence_hash or OLD.environment_snapshot_hash is distinct from NEW.environment_snapshot_hash or OLD.git_commit_hash is distinct from NEW.git_commit_hash or OLD.git_dirty is distinct from NEW.git_dirty or OLD.schema_revision is distinct from NEW.schema_revision or OLD.result_count is distinct from NEW.result_count) then raise exception 'completed analysis_run provenance is immutable'; end if; return NEW; end; $$ language plpgsql;
    create trigger trg_environment_snapshot_immutable before update or delete on environment_snapshot for each row execute function block_environment_snapshot_update();
    create trigger trg_normalization_profile_immutable before update on normalization_profile for each row execute function block_normalization_profile_update();
    create trigger trg_query_scope_definition_immutable before update on query_scope_definition for each row execute function block_query_scope_definition_update();
    create trigger trg_analysis_run_completed_immutable before update on analysis_run for each row execute function block_analysis_run_completed_update();
    ''')


def downgrade():
    op.execute("drop trigger if exists trg_analysis_run_completed_immutable on analysis_run; drop trigger if exists trg_query_scope_definition_immutable on query_scope_definition; drop trigger if exists trg_normalization_profile_immutable on normalization_profile; drop trigger if exists trg_environment_snapshot_immutable on environment_snapshot; drop function if exists block_phase2b_immutable_update();")
    op.drop_constraint("ck_analysis_run_status", "analysis_run", type_="check")
    op.drop_index("ix_export_manifest_run", table_name="export_manifest")
    op.drop_table("export_manifest")
    op.drop_index("ix_analysis_evidence_lookup", table_name="analysis_evidence")
    op.drop_index("ix_analysis_evidence_run_order", table_name="analysis_evidence")
    op.drop_index("ix_analysis_run_source_scope", table_name="analysis_run")
    op.drop_index("ix_analysis_run_evidence_hash", table_name="analysis_run")
    op.drop_index("ix_analysis_run_query_hash", table_name="analysis_run")
    op.drop_constraint("fk_analysis_run_environment_snapshot", "analysis_run", type_="foreignkey")
    for col in ["schema_revision", "git_dirty", "git_commit_hash", "environment_snapshot_hash", "environment_snapshot_id", "evidence_hash_algorithm_version", "evidence_hash", "query_hash_algorithm_version"]:
        op.drop_column("analysis_run", col)
    op.drop_table("environment_snapshot")
