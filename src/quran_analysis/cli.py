from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from quran_analysis.analysis import exact_token_search, frequency_count, normalized_token_search, phrase_search, repeated_ngrams, substring_search, ensure_normalized_tokens, latest_source, tokens_query
from quran_analysis.config import settings
from quran_analysis.db.session import get_session_local
from quran_analysis.ingestion.memory import ingest_memory, ingest_source_release, validate_source_release
from quran_analysis.models.tables import NormalizedToken, OrthographicToken, SourceRelease, TextUnit, UnicodeCodepoint
from quran_analysis.normalization.profiles import PROFILES, get_profile, normalize_token
from quran_analysis.provenance import environment
from quran_analysis.scopes.core import numbered_only, scope_hash
from quran_analysis.sources.register import inspect_source, register_source

app = typer.Typer(no_args_is_help=True)
db_app = typer.Typer(); source_app = typer.Typer(); unicode_app = typer.Typer(); ayah_app = typer.Typer(); token_app = typer.Typer(); norm_app = typer.Typer(); scope_app = typer.Typer(); count_app = typer.Typer(); search_app = typer.Typer(); analysis_app = typer.Typer(); environment_app = typer.Typer(); export_app = typer.Typer(); ngrams_app = typer.Typer()
for sub, name in [(db_app,"db"),(source_app,"source"),(unicode_app,"unicode"),(ayah_app,"ayah"),(token_app,"token"),(norm_app,"normalization"),(scope_app,"scope"),(count_app,"count"),(search_app,"search"),(analysis_app,"analysis"),(environment_app,"environment"),(export_app,"export"),(ngrams_app,"ngrams")]: app.add_typer(sub, name=name)


def echo(obj): typer.echo(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
def session_scope(): return get_session_local()()
def _state(source: Path): return ingest_memory(source)

@db_app.command("migrate")
def db_migrate(): command.upgrade(Config("alembic.ini"), "head"); typer.echo("migrations applied")

@source_app.command("register")
def source_register(path: Path, name: str=typer.Option(...), version: str=typer.Option(...), format: str=typer.Option(...)):
    result=register_source(path,name,version,format,settings.data_dir)
    if result["status"]=="registered":
        m=result["manifest"]
        with session_scope() as s:
            existing=s.scalar(select(SourceRelease).where(SourceRelease.sha256==m["sha256"]))
            if existing is None:
                row=SourceRelease(source_name=name,source_version=version,source_format=format,original_filename=m["original_filename"],stored_filename=m["stored_filename"],encoding="utf-8",sha256=m["sha256"],byte_size=m["byte_size"],line_count=m["line_count"],metadata_json=m,source_url=None,license=None,notes=None)
                s.add(row); s.commit(); m["source_release_id"]=row.id
            else:
                m["source_release_id"]=existing.id; result["status"]="already_registered"
    echo(result)

@source_app.command("list")
def source_list():
    with session_scope() as s: echo([{"id":r.id,"name":r.source_name,"version":r.source_version,"sha256":r.sha256,"stored_filename":r.stored_filename} for r in s.scalars(select(SourceRelease)).all()])

@source_app.command("inspect")
def source_inspect(path: Path, format: str=typer.Option(...)): echo(inspect_source(path,format))

@app.command("ingest")
def ingest(source_id: int):
    with session_scope() as s: echo(ingest_source_release(s,source_id))

@app.command("validate")
def validate(source_id: int):
    with session_scope() as s: echo(validate_source_release(s,source_id))

@environment_app.command("show")
def environment_show():
    with session_scope() as s: echo(environment(s))

@unicode_app.command("inventory")
def unicode_inventory(source_id: int):
    with session_scope() as s:
        cps=s.scalars(select(UnicodeCodepoint).join(TextUnit, UnicodeCodepoint.text_unit_id==TextUnit.id).where(TextUnit.source_release_id==source_id)).all(); counts={}
        for cp in cps: counts[(cp.unicode_hex,cp.character,cp.unicode_name,cp.general_category)] = counts.get((cp.unicode_hex,cp.character,cp.unicode_name,cp.general_category),0)+1
        echo([{"unicode_hex":k[0],"character":k[1],"unicode_name":k[2],"general_category":k[3],"count":v} for k,v in sorted(counts.items())])

@ayah_app.command("get")
def ayah_get(source: Path, surah: int, ayah: int):
    for u in _state(source)["units"]:
        if u["surah_number"]==surah and u["ayah_number"]==ayah: typer.echo(u["text_raw"]); return
    raise typer.Exit(1)

@token_app.command("global")
def token_global(source: Path, position: int):
    toks=[t for u in _state(source)["units"] for t in u["tokens"]]; typer.echo(toks[position-1]["surface_raw"])

@norm_app.command("list")
def normalization_list(): echo(PROFILES)

@norm_app.command("inspect")
def normalization_inspect(profile: str): echo(get_profile(profile))

@norm_app.command("token")
def normalization_token(address: str, profile: str): echo(normalize_token(address,profile))

@norm_app.command("compare")
def normalization_compare(token_address: str, profiles: list[str]=typer.Option(..., "--profiles")):
    # TOKEN_ADDRESS accepts raw text for inspection or db:<global_token_position> for persisted token lookup.
    value = token_address
    source_ids = None
    if token_address.startswith("db:"):
        with session_scope() as s:
            pos = int(token_address[3:]); source = latest_source(s); token = s.scalar(select(OrthographicToken).join(TextUnit).where(TextUnit.source_release_id == source.id, OrthographicToken.token_in_full_source_stream == pos))
            value = token.surface_raw; source_ids = [cp.id for cp in s.scalars(select(UnicodeCodepoint).where(UnicodeCodepoint.orthographic_token_id == token.id).order_by(UnicodeCodepoint.codepoint_in_token)).all()]
    echo({"token_address": token_address, "raw_surface": value, "profiles": {p: normalize_token(value, p, source_ids) for p in profiles}})

@scope_app.command("create")
def scope_create(): c=numbered_only(); echo({"configuration":c,"sha256":scope_hash(c)})
@scope_app.command("inspect")
def scope_inspect(config: str): c=json.loads(config); echo({"configuration":c,"sha256":scope_hash(c)})

@search_app.command("exact-token")
def cli_exact_token(surface: str=typer.Option(..., "--surface"), scope: str=typer.Option("numbered_ayah", "--scope")):
    with session_scope() as s: run, results = exact_token_search(s, surface, scope); echo({"analysis_run_id": run.id, "result_count": len(results), "results": results})

@search_app.command("substring")
def cli_substring(value: str=typer.Option(..., "--value"), representation: str=typer.Option("raw", "--representation")):
    if representation != "raw": raise typer.BadParameter("only --representation raw is supported")
    with session_scope() as s: run, results = substring_search(s, value); echo({"analysis_run_id": run.id, "result_count": len(results), "results": results})

@search_app.command("normalized-token")
def cli_normalized_token(value: str=typer.Option(..., "--value"), profile: str=typer.Option(..., "--profile"), scope: str=typer.Option("numbered_ayah", "--scope")):
    with session_scope() as s: run, results = normalized_token_search(s, value, profile, scope); echo({"analysis_run_id": run.id, "result_count": len(results), "results": results})

@search_app.command("phrase")
def cli_phrase(value: str=typer.Option(..., "--value"), representation: str=typer.Option("raw-token", "--representation"), profile: Optional[str]=typer.Option(None, "--profile"), cross_unit: bool=typer.Option(False, "--cross-unit")):
    with session_scope() as s: run, results = phrase_search(s, value, representation, profile, cross_unit); echo({"analysis_run_id": run.id, "result_count": len(results), "results": results})

@count_app.command("token-frequencies")
def cli_token_freq(representation: str=typer.Option(..., "--representation"), scope: str=typer.Option("numbered_ayah", "--scope"), profile: Optional[str]=typer.Option(None, "--profile")):
    with session_scope() as s: run, results = frequency_count(s, representation, profile, scope); echo({"analysis_run_id": run.id, "result_count": len(results), "results": results})

@ngrams_app.command("repeated")
def cli_ngrams(n: int=typer.Option(..., "--n"), representation: str=typer.Option("raw-token", "--representation"), profile: Optional[str]=typer.Option(None, "--profile"), cross_unit: bool=typer.Option(False, "--cross-unit")):
    with session_scope() as s: run, results = repeated_ngrams(s, n, representation, profile, cross_unit); echo({"analysis_run_id": run.id, "result_count": len(results), "results": results})

@export_app.command("tokens")
def export_tokens(scope: str=typer.Option("numbered_ayah", "--scope"), format: str=typer.Option("csv", "--format")):
    with session_scope() as s:
        source=latest_source(s); rows=[{"surah":u.surah_number,"ayah":u.ayah_number,"token_position_in_ayah":t.token_in_unit,"global_token_position":t.token_in_full_source_stream,"raw_surface":t.surface_raw,"codepoint_start":t.start_codepoint_in_unit,"codepoint_end":t.end_codepoint_in_unit,"source_release_sha256":source.sha256,"tokenizer_version":t.tokenizer_version} for t,u in s.execute(tokens_query(source.id)).all()]
    if format == "json": echo(rows); return
    w=csv.DictWriter(typer.get_text_stream("stdout"), fieldnames=list(rows[0].keys()) if rows else ["raw_surface"]); w.writeheader(); w.writerows(rows)

@export_app.command("normalized-tokens")
def export_normalized_tokens(profile: str=typer.Option(..., "--profile"), scope: str=typer.Option("numbered_ayah", "--scope"), format: str=typer.Option("csv", "--format")):
    with session_scope() as s:
        source=latest_source(s); pr=ensure_normalized_tokens(s, source.id, profile)
        data=s.execute(select(OrthographicToken, TextUnit, NormalizedToken).join(TextUnit, OrthographicToken.text_unit_id==TextUnit.id).join(NormalizedToken, NormalizedToken.orthographic_token_id==OrthographicToken.id).where(TextUnit.source_release_id==source.id, NormalizedToken.normalization_profile_id==pr.id).order_by(OrthographicToken.token_in_full_source_stream)).all()
        rows=[{"surah":u.surah_number,"ayah":u.ayah_number,"token_position_in_ayah":t.token_in_unit,"global_token_position":t.token_in_full_source_stream,"raw_surface":t.surface_raw,"normalized_surface":nt.normalized_value,"profile_configuration_sha256":nt.profile_configuration_sha256,"source_release_sha256":source.sha256} for t,u,nt in data]
    if format == "json": echo(rows); return
    w=csv.DictWriter(typer.get_text_stream("stdout"), fieldnames=list(rows[0].keys()) if rows else ["raw_surface"]); w.writeheader(); w.writerows(rows)

@analysis_app.command("show")
def analysis_show(): typer.echo("analysis persistence enabled via analysis_run / analysis_evidence and data/analysis_runs exports")

if __name__ == "__main__": app()
