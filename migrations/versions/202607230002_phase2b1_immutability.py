"""phase2b1 database immutability hardening

Revision ID: 202607230002
Revises: 202607230001
Create Date: 2026-07-23 00:02:00
"""

from alembic import op

revision = "202607230002"
down_revision = "202607230001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''
    create or replace function block_environment_snapshot_update() returns trigger as $$
    begin
        raise exception 'environment_snapshot rows are immutable';
    end;
    $$ language plpgsql;

    create or replace function block_used_normalization_profile_delete() returns trigger as $$
    begin
        if exists (select 1 from normalized_token where normalization_profile_id = OLD.id)
           or exists (select 1 from analysis_run where normalization_profile_id = OLD.id) then
            raise exception 'used normalization_profile rows cannot be deleted';
        end if;
        return OLD;
    end;
    $$ language plpgsql;

    create or replace function block_query_scope_definition_delete() returns trigger as $$
    begin
        if exists (select 1 from analysis_run where scope_configuration_json = OLD.configuration_json) then
            raise exception 'used query_scope_definition rows cannot be deleted';
        end if;
        return OLD;
    end;
    $$ language plpgsql;

    create or replace function block_analysis_run_completed_update() returns trigger as $$
    begin
        if OLD.status = 'completed' and (
            OLD.status is distinct from NEW.status
            or OLD.query_hash is distinct from NEW.query_hash
            or OLD.evidence_hash is distinct from NEW.evidence_hash
            or OLD.environment_snapshot_id is distinct from NEW.environment_snapshot_id
            or OLD.environment_snapshot_hash is distinct from NEW.environment_snapshot_hash
            or OLD.git_commit_hash is distinct from NEW.git_commit_hash
            or OLD.git_dirty is distinct from NEW.git_dirty
            or OLD.schema_revision is distinct from NEW.schema_revision
            or OLD.result_count is distinct from NEW.result_count
            or OLD.completed_at is distinct from NEW.completed_at
            or OLD.result_manifest_path is distinct from NEW.result_manifest_path
        ) then
            raise exception 'completed analysis_run provenance is immutable';
        end if;
        return NEW;
    end;
    $$ language plpgsql;

    create trigger trg_normalization_profile_used_no_delete before delete on normalization_profile for each row execute function block_used_normalization_profile_delete();
    create trigger trg_query_scope_definition_used_no_delete before delete on query_scope_definition for each row execute function block_query_scope_definition_delete();
    ''')


def downgrade():
    op.execute('''
    drop trigger if exists trg_query_scope_definition_used_no_delete on query_scope_definition;
    drop trigger if exists trg_normalization_profile_used_no_delete on normalization_profile;
    drop function if exists block_query_scope_definition_delete();
    drop function if exists block_used_normalization_profile_delete();
    ''')
