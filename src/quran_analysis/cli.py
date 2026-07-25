from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from quran_analysis.annotation_sources.ingestion import ingest_qac_source
from quran_analysis.annotation_sources.alignment import align_qac_source
from quran_analysis.annotation_sources.capabilities import AnnotationFrameworkError, production_annotation_adapter_registry
from quran_analysis.annotation_sources.catalog import (
    SourceLifecycleError,
    get_catalog_source,
    guard_source_activation,
    guard_source_ingestion,
    list_catalog_sources,
)
from quran_analysis.annotation_sources.service import source_descriptor
from quran_analysis.annotation_sources.registration import EXPECTED_CONFIGURATION_HASH, SqlRegistrationRepository, register_local_qac
from quran_analysis.analysis import exact_token_search, frequency_count, normalized_token_search, phrase_search, repeated_ngrams, substring_search, ensure_normalized_tokens, latest_source, tokens_query, verify_export_file, verify_run, write_export
from quran_analysis.config import settings
from quran_analysis.db.session import get_session_local
from quran_analysis.ingestion.memory import ingest_memory, ingest_source_release, validate_source_release
from quran_analysis.models.tables import NormalizedToken, OrthographicToken, SourceRelease, TextUnit, UnicodeCodepoint
from quran_analysis.morphology.analytics import MorphologyAnalyticsFilter, MorphologyAnalyticsService
from quran_analysis.morphology.query import MorphologyQuery, MorphologyQueryService, SqlMorphologyRepository
from quran_analysis.morphology.core import (conflicts as morph_conflicts, export_entity as morph_export_entity, get_table_row as morph_get_table_row, ingest_morphology, inspect_annotation_source, list_annotation_sources, register_annotation_source, show_annotation_source, show_token as morph_show_token, stats as morph_stats, unresolved as morph_unresolved, validate_annotation_source, validate_ingestion, verify_export as morph_verify_export)
from quran_analysis.normalization.profiles import PROFILES, get_profile, normalize_token
from quran_analysis.provenance import environment
from quran_analysis.presentation import emit_research
from quran_analysis.research import (
    AggregateQuery, AggregationError, CooccurrenceQuery, ResearchEngine, ResearchQueryError, SetQuery, load_query,
)
from quran_analysis.scopes.core import numbered_only, scope_hash
from quran_analysis.sources.register import inspect_source, register_source
from quran_analysis.verification import (
    VerificationError,
    benchmark as verification_benchmark,
    compatibility_locks,
    database_counts,
    golden_contract,
    release_manifest,
    render as render_verification,
    replay_goldens,
    research_certificate,
    verify_goldens,
)

app = typer.Typer(no_args_is_help=True)
db_app = typer.Typer(); source_app = typer.Typer(); unicode_app = typer.Typer(); ayah_app = typer.Typer(); token_app = typer.Typer(); norm_app = typer.Typer(); scope_app = typer.Typer(); count_app = typer.Typer(); search_app = typer.Typer(); analysis_app = typer.Typer(); environment_app = typer.Typer(); export_app = typer.Typer(); ngrams_app = typer.Typer(); annotation_source_app = typer.Typer(); morphology_app = typer.Typer(); morph_alignment_app = typer.Typer(); research_app = typer.Typer(no_args_is_help=True)
morphology_app.add_typer(morph_alignment_app, name="alignment")
morph_stats_app = typer.Typer(no_args_is_help=True)
morphology_app.add_typer(morph_stats_app, name="stats")
for sub, name in [(db_app,"db"),(source_app,"source"),(unicode_app,"unicode"),(ayah_app,"ayah"),(token_app,"token"),(norm_app,"normalization"),(scope_app,"scope"),(count_app,"count"),(search_app,"search"),(analysis_app,"analysis"),(environment_app,"environment"),(export_app,"export"),(ngrams_app,"ngrams"),(annotation_source_app,"annotation-source"),(morphology_app,"morphology"),(research_app,"research")]: app.add_typer(sub, name=name)


def echo(obj): typer.echo(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
def preview(run, results, limit=50, offset=0):
    sliced=results[offset:offset+limit]
    return {"analysis_run_id": run.id, "query_hash": run.query_hash, "evidence_hash": getattr(run, "evidence_hash", None), "result_count": len(results), "limit": limit, "offset": offset, "truncated": offset + len(sliced) < len(results), "results": sliced}
def session_scope(): return get_session_local()()
def _state(source: Path): return ingest_memory(source)

@research_app.command("query")
def research_query(query: Optional[str] = typer.Option(None, "--query"), file: Optional[Path] = typer.Option(None, "--file"), input_format: Optional[str] = typer.Option(None, "--input-format"), format: str = typer.Option("text", "--format"), output: Optional[Path] = typer.Option(None, "--output")):
    """Execute a bounded immutable research query from inline JSON/YAML or a query file."""
    if (query is None) == (file is None):
        raise typer.BadParameter("provide exactly one of --query or --file")
    if format not in {"text", "json", "yaml", "csv", "jsonl", "markdown"}:
        raise typer.BadParameter("format must be text, json, yaml, csv, jsonl, or markdown")
    try:
        if file is not None and not file.is_file():
            raise ResearchQueryError(f"query file not found: {file}")
        parsed = load_query(file if file is not None else query or "", input_format)
        with session_scope() as s:
            result = ResearchEngine(s).execute(parsed)
        typer.echo(emit_research(result.to_dict(), format, output), nl=False)
    except (ResearchQueryError, AnnotationFrameworkError, OSError, ValueError) as exc:
        payload = exc.to_dict() if hasattr(exc, "to_dict") else {"code": "invalid_research_query", "message": str(exc)}
        typer.echo(json.dumps(payload, ensure_ascii=False), err=True)
        raise typer.Exit(2) from exc

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
def cli_exact_token(surface: str=typer.Option(..., "--surface"), scope: str=typer.Option("numbered_ayah", "--scope"), limit: int=typer.Option(50, "--limit"), offset: int=typer.Option(0, "--offset"), allow_dirty: bool=typer.Option(False, "--allow-dirty")):
    with session_scope() as s: run, results = exact_token_search(s, surface, scope, allow_dirty); echo(preview(run, results, limit, offset))

@search_app.command("substring")
def cli_substring(value: str=typer.Option(..., "--value"), representation: str=typer.Option("raw", "--representation")):
    if representation != "raw": raise typer.BadParameter("only --representation raw is supported")
    with session_scope() as s: run, results = substring_search(s, value, True); echo({"analysis_run_id": run.id, "result_count": len(results), "results": results})

@search_app.command("normalized-token")
def cli_normalized_token(value: str=typer.Option(..., "--value"), profile: str=typer.Option(..., "--profile"), scope: str=typer.Option("numbered_ayah", "--scope"), limit: int=typer.Option(50, "--limit"), offset: int=typer.Option(0, "--offset"), allow_dirty: bool=typer.Option(False, "--allow-dirty")):
    with session_scope() as s: run, results = normalized_token_search(s, value, profile, scope, allow_dirty); echo(preview(run, results, limit, offset))

@search_app.command("phrase")
def cli_phrase(value: str=typer.Option(..., "--value"), representation: str=typer.Option("raw-token", "--representation"), profile: Optional[str]=typer.Option(None, "--profile"), cross_unit: bool=typer.Option(False, "--cross-unit"), limit: int=typer.Option(50, "--limit"), offset: int=typer.Option(0, "--offset"), allow_dirty: bool=typer.Option(False, "--allow-dirty")):
    with session_scope() as s: run, results = phrase_search(s, value, representation, profile, cross_unit, allow_dirty); echo(preview(run, results, limit, offset))

@count_app.command("token-frequencies")
def cli_token_freq(representation: str=typer.Option(..., "--representation"), scope: str=typer.Option("numbered_ayah", "--scope"), profile: Optional[str]=typer.Option(None, "--profile"), limit: int=typer.Option(50, "--limit"), offset: int=typer.Option(0, "--offset"), allow_dirty: bool=typer.Option(False, "--allow-dirty")):
    with session_scope() as s: run, results = frequency_count(s, representation, profile, scope, allow_dirty); echo(preview(run, results, limit, offset))

@ngrams_app.command("repeated")
def cli_ngrams(n: int=typer.Option(..., "--n"), representation: str=typer.Option("raw-token", "--representation"), profile: Optional[str]=typer.Option(None, "--profile"), cross_unit: bool=typer.Option(False, "--cross-unit"), limit: int=typer.Option(50, "--limit"), offset: int=typer.Option(0, "--offset"), allow_dirty: bool=typer.Option(False, "--allow-dirty")):
    with session_scope() as s: run, results = repeated_ngrams(s, n, representation, profile, cross_unit, allow_dirty); echo(preview(run, results, limit, offset))

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

@analysis_app.command("export")
def analysis_export(run_id: int, format: str=typer.Option("json", "--format"), output: Path=typer.Option(..., "--output")):
    with session_scope() as s: echo(write_export(s, run_id, format, output))

@analysis_app.command("verify-export")
def analysis_verify_export(path: Path):
    with session_scope() as s:
        result = verify_export_file(path, s)
    echo(result)
    if not result.get("ok"): raise typer.Exit(1)

@analysis_app.command("verify")
def analysis_verify(run_id: int):
    with session_scope() as s: result = verify_run(s, run_id)
    echo(result)
    if not result.get("ok"): raise typer.Exit(1)


@annotation_source_app.command("register-local-qac")
def annotation_source_register_local_qac(path: Path, original_filename: Optional[str] = typer.Option(None), expected_parser_configuration_hash: Optional[str] = typer.Option(None)):
    """Register local QAC source metadata only; no raw copy, records, or ingestion."""
    with session_scope() as s:
        result = register_local_qac(SqlRegistrationRepository(s), path, original_filename=original_filename, expected_parser_configuration_hash=expected_parser_configuration_hash)
        s.commit()
    echo(result | {"expected_parser_configuration_hash": EXPECTED_CONFIGURATION_HASH.digest})


@annotation_source_app.command("ingest")
def annotation_source_ingest(source_id: int):
    """Persist a metadata-registered QAC source without any Tanzil alignment."""
    with session_scope() as s:
        echo(ingest_qac_source(s, source_id))

@annotation_source_app.command("align")
def annotation_source_align(source_id: int):
    """Create or reuse bounded QAC-to-Tanzil alignment evidence."""
    with session_scope() as s: echo(align_qac_source(s, source_id))

@annotation_source_app.command("inspect")
def annotation_source_inspect(path: Path, format: str = typer.Option(..., "--format")):
    echo(inspect_annotation_source(path, format))

@annotation_source_app.command("register")
def annotation_source_register(path: Path, name: str = typer.Option(...), version: str = typer.Option(...), format: str = typer.Option(...), publisher: str = typer.Option(...), license: str = typer.Option(...), official_url: Optional[str] = typer.Option(None), license_url: Optional[str] = typer.Option(None), citation: Optional[str] = typer.Option(None)):
    with session_scope() as s: echo(register_annotation_source(s, path, name=name, version=version, fmt=format, publisher=publisher, license=license, official_url=official_url, license_url=license_url, citation=citation))

@annotation_source_app.command("list")
def annotation_source_list():
    with session_scope() as s: echo(list_annotation_sources(s))

def _catalog_text(entry: dict) -> None:
    for key, value in entry.items():
        if key == "lifecycle":
            typer.echo(f"LIFECYCLE={value}")
        elif isinstance(value, list):
            typer.echo(f"{key}={json.dumps(value, ensure_ascii=False, separators=(',', ':'))}")
        else:
            typer.echo(f"{key}={value}")


@annotation_source_app.command("catalog")
def annotation_source_catalog(format: str = typer.Option("text", "--format")):
    """List static source catalog entries; this never consults source-release rows."""
    if format not in {"text", "json"}:
        raise typer.BadParameter("format must be text or json")
    entries = [entry.to_dict() for entry in list_catalog_sources()]
    if format == "json":
        echo(entries)
    else:
        for index, entry in enumerate(entries):
            if index:
                typer.echo()
            _catalog_text(entry)


@annotation_source_app.command("show")
def annotation_source_show(source: str, format: str = typer.Option("text", "--format")):
    """Show a static catalog source by identifier; numeric release IDs retain legacy output."""
    if format not in {"text", "json"}:
        raise typer.BadParameter("format must be text or json")
    if source.isdecimal():
        with session_scope() as s:
            echo(show_annotation_source(s, int(source)))
        return
    try:
        entry = get_catalog_source(source).to_dict()
    except KeyError as exc:
        typer.echo(json.dumps({"code": "catalog_source_not_found", "source_identifier": source}, ensure_ascii=False), err=True)
        raise typer.Exit(2) from exc
    if format == "json":
        echo(entry)
    else:
        _catalog_text(entry)


@annotation_source_app.command("lifecycle-guard")
def annotation_source_lifecycle_guard(source: str, operation: str = typer.Option(..., "--operation")):
    """Run a read-only future-operation lifecycle guard; it never activates or ingests."""
    if operation not in {"activation", "ingestion"}:
        raise typer.BadParameter("operation must be activation or ingestion")
    try:
        entry = get_catalog_source(source)
        if operation == "activation":
            guard_source_activation(entry)
        else:
            guard_source_ingestion(entry)
    except SourceLifecycleError as exc:
        typer.echo(json.dumps(exc.to_dict(), ensure_ascii=False), err=True)
        raise typer.Exit(2) from exc
    except KeyError as exc:
        typer.echo(json.dumps({"code": "catalog_source_not_found", "source_identifier": source}, ensure_ascii=False), err=True)
        raise typer.Exit(2) from exc
    echo({"source_identifier": entry.source_identifier, "lifecycle": entry.lifecycle.value, "operation": operation, "permitted": True})


@annotation_source_app.command("capabilities")
def annotation_source_capabilities(source_release_id: int, format: str = typer.Option("text", "--format")):
    """Display the immutable adapter-derived capability descriptor; this never writes."""
    if format not in {"text", "json"}:
        raise typer.BadParameter("format must be text or json")
    try:
        with session_scope() as s:
            descriptor = source_descriptor(s, source_release_id, production_annotation_adapter_registry())
        data = descriptor.to_dict()
        if format == "json":
            echo(data)
        else:
            for key, value in data.items():
                typer.echo(f"{key}={','.join(value) if isinstance(value, list) else value}")
    except AnnotationFrameworkError as exc:
        typer.echo(json.dumps(exc.to_dict(), ensure_ascii=False), err=True)
        raise typer.Exit(2) from exc

@annotation_source_app.command("validate")
def annotation_source_validate(source_id: int):
    with session_scope() as s:
        result = validate_annotation_source(s, source_id)
    echo(result)
    if not result.get("ok"): raise typer.Exit(1)

def _morphology_result(result, format: str) -> None:
    data = result.to_dict()
    if format == "json":
        echo(data)
    else:
        for item in data["results"]:
            typer.echo(f"{item['locator']} {item['tag']} {item['form']} {item['raw_features']}")


@morphology_app.command("find")
def morphology_find(source_release_id: Optional[int] = typer.Option(None, "--source-release-id"), root: Optional[str] = typer.Option(None, "--root"), lemma: Optional[str] = typer.Option(None, "--lemma"), tag: Optional[str] = typer.Option(None, "--tag"), feature: Optional[str] = typer.Option(None, "--feature"), surah: Optional[int] = typer.Option(None, "--surah"), ayah: Optional[int] = typer.Option(None, "--ayah"), token: Optional[int] = typer.Option(None, "--token"), alignment_method: Optional[str] = typer.Option(None, "--alignment-method"), limit: int = typer.Option(50, "--limit"), offset: int = typer.Option(0, "--offset"), format: str = typer.Option("human", "--format")):
    if format not in {"human", "json"}:
        raise typer.BadParameter("format must be human or json")
    try:
        query = MorphologyQuery(source_release_id, root, lemma, tag, feature, surah, ayah, token, None, alignment_method, limit, offset)
        with session_scope() as s:
            _morphology_result(MorphologyQueryService(SqlMorphologyRepository(s)).find(query), format)
    except AnnotationFrameworkError as exc:
        typer.echo(json.dumps(exc.to_dict(), ensure_ascii=False), err=True)
        raise typer.Exit(2) from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _locator(value: str, parts: int) -> tuple[int, ...]:
    try:
        values = tuple(int(part) for part in value.split(":"))
    except ValueError as exc:
        raise typer.BadParameter("malformed locator") from exc
    if len(values) != parts or any(part < 1 for part in values):
        raise typer.BadParameter("malformed locator")
    return values


@morphology_app.command("show-ayah")
def morphology_show_ayah(locator: str):
    surah, ayah = _locator(locator, 2)
    with session_scope() as s:
        _morphology_result(MorphologyQueryService(SqlMorphologyRepository(s)).show_ayah(surah, ayah), "human")


@morphology_app.command("show-token")
def morphology_show_token(locator: str):
    surah, ayah, token = _locator(locator, 3)
    with session_scope() as s:
        _morphology_result(MorphologyQueryService(SqlMorphologyRepository(s)).show_token(surah, ayah, token), "human")


@morphology_app.command("show-locator")
def morphology_show_locator(locator: str):
    surah, ayah, token, segment = _locator(locator, 4)
    with session_scope() as s:
        _morphology_result(MorphologyQueryService(SqlMorphologyRepository(s)).show_locator(surah, ayah, token, segment), "human")


@morphology_app.command("ingest")
def morphology_ingest(annotation_source_id: int, quran_source: int = typer.Option(..., "--quran-source"), alignment_config: str = typer.Option(..., "--alignment-config"), allow_dirty: bool = typer.Option(False, "--allow-dirty")):
    with session_scope() as s: echo(ingest_morphology(s, annotation_source_id, quran_source, alignment_config, allow_dirty))

@morphology_app.command("validate")
def morphology_validate(ingestion_run_id: int):
    with session_scope() as s:
        result = validate_ingestion(s, ingestion_run_id)
    echo(result)
    if not result.get("ok"): raise typer.Exit(1)

@morphology_app.command("source-record")
def morphology_source_record(record_id: int):
    with session_scope() as s: echo(morph_get_table_row(s, "annotation_source_record", record_id))

@morphology_app.command("analysis")
def morphology_analysis(analysis_id: int):
    with session_scope() as s: echo(morph_get_table_row(s, "morphological_analysis", analysis_id))

@morph_alignment_app.command("inspect")
def morphology_alignment_inspect(alignment_id: int):
    with session_scope() as s: echo(morph_get_table_row(s, "annotation_alignment", alignment_id))

@morph_alignment_app.command("show-token")
def morphology_alignment_show_token(token_locator: str, annotation_source: int = typer.Option(..., "--annotation-source")):
    with session_scope() as s: echo(morph_show_token(s, token_locator, annotation_source))

@morph_alignment_app.command("unresolved")
def morphology_alignment_unresolved(annotation_source: int = typer.Option(..., "--annotation-source"), status: str = typer.Option(..., "--status")):
    with session_scope() as s: echo(morph_unresolved(s, annotation_source, status))

@morphology_app.command("conflicts")
def morphology_conflicts(annotation_source: int = typer.Option(..., "--annotation-source"), dimension: str = typer.Option(..., "--dimension")):
    with session_scope() as s: echo(morph_conflicts(s, annotation_source, dimension))

def _analytics_filter(source_release_id: Optional[int], surah: Optional[int], ayah: Optional[int], root: Optional[str], lemma: Optional[str], tag: Optional[str], feature: Optional[str], alignment_method: Optional[str]) -> MorphologyAnalyticsFilter:
    return MorphologyAnalyticsFilter(source_release_id, surah, ayah, root, lemma, tag, feature, alignment_method)


def _analytics_result(result, format: str, dimension: str) -> None:
    if format not in {"text", "json"}:
        raise typer.BadParameter("format must be text or json")
    if hasattr(result, "to_dict"):
        data = result.to_dict()
    else:
        data = {"dimension": dimension, "results": [item.to_dict() for item in result]}
    if format == "json":
        echo(data)
    elif "results" in data:
        for row in data["results"]:
            typer.echo(" ".join(f"{key}={value}" for key, value in row.items()))
    else:
        for key, value in data.items():
            typer.echo(f"{key}={value}")


def _run_analytics(method: str, source_release_id: Optional[int], surah: Optional[int], ayah: Optional[int], root: Optional[str], lemma: Optional[str], tag: Optional[str], feature: Optional[str], alignment_method: Optional[str], limit: int, offset: int, format: str) -> None:
    try:
        filters = _analytics_filter(source_release_id, surah, ayah, root, lemma, tag, feature, alignment_method)
        with session_scope() as s:
            service = MorphologyAnalyticsService(s)
            service._page(limit, offset)
            result = getattr(service, method)(filters) if method == "summary" else getattr(service, method)(filters, limit, offset)
        _analytics_result(result, format, method)
    except AnnotationFrameworkError as exc:
        typer.echo(json.dumps(exc.to_dict(), ensure_ascii=False), err=True)
        raise typer.Exit(2) from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@morph_stats_app.command("summary")
def morphology_stats_summary(source_release_id: Optional[int] = typer.Option(None, "--source-release-id"), surah: Optional[int] = typer.Option(None, "--surah"), ayah: Optional[int] = typer.Option(None, "--ayah"), root: Optional[str] = typer.Option(None, "--root"), lemma: Optional[str] = typer.Option(None, "--lemma"), tag: Optional[str] = typer.Option(None, "--tag"), feature: Optional[str] = typer.Option(None, "--feature"), alignment_method: Optional[str] = typer.Option(None, "--alignment-method"), limit: int = typer.Option(50, "--limit"), offset: int = typer.Option(0, "--offset"), format: str = typer.Option("text", "--format")):
    _run_analytics("summary", source_release_id, surah, ayah, root, lemma, tag, feature, alignment_method, limit, offset, format)


@morph_stats_app.command("roots")
def morphology_stats_roots(source_release_id: Optional[int] = typer.Option(None, "--source-release-id"), surah: Optional[int] = typer.Option(None, "--surah"), ayah: Optional[int] = typer.Option(None, "--ayah"), root: Optional[str] = typer.Option(None, "--root"), lemma: Optional[str] = typer.Option(None, "--lemma"), tag: Optional[str] = typer.Option(None, "--tag"), feature: Optional[str] = typer.Option(None, "--feature"), alignment_method: Optional[str] = typer.Option(None, "--alignment-method"), limit: int = typer.Option(50, "--limit"), offset: int = typer.Option(0, "--offset"), format: str = typer.Option("text", "--format")):
    _run_analytics("root_frequency", source_release_id, surah, ayah, root, lemma, tag, feature, alignment_method, limit, offset, format)


@morph_stats_app.command("lemmas")
def morphology_stats_lemmas(source_release_id: Optional[int] = typer.Option(None, "--source-release-id"), surah: Optional[int] = typer.Option(None, "--surah"), ayah: Optional[int] = typer.Option(None, "--ayah"), root: Optional[str] = typer.Option(None, "--root"), lemma: Optional[str] = typer.Option(None, "--lemma"), tag: Optional[str] = typer.Option(None, "--tag"), feature: Optional[str] = typer.Option(None, "--feature"), alignment_method: Optional[str] = typer.Option(None, "--alignment-method"), limit: int = typer.Option(50, "--limit"), offset: int = typer.Option(0, "--offset"), format: str = typer.Option("text", "--format")):
    _run_analytics("lemma_frequency", source_release_id, surah, ayah, root, lemma, tag, feature, alignment_method, limit, offset, format)


@morph_stats_app.command("tags")
def morphology_stats_tags(source_release_id: Optional[int] = typer.Option(None, "--source-release-id"), surah: Optional[int] = typer.Option(None, "--surah"), ayah: Optional[int] = typer.Option(None, "--ayah"), root: Optional[str] = typer.Option(None, "--root"), lemma: Optional[str] = typer.Option(None, "--lemma"), tag: Optional[str] = typer.Option(None, "--tag"), feature: Optional[str] = typer.Option(None, "--feature"), alignment_method: Optional[str] = typer.Option(None, "--alignment-method"), limit: int = typer.Option(50, "--limit"), offset: int = typer.Option(0, "--offset"), format: str = typer.Option("text", "--format")):
    _run_analytics("tag_frequency", source_release_id, surah, ayah, root, lemma, tag, feature, alignment_method, limit, offset, format)


@morph_stats_app.command("features")
def morphology_stats_features(source_release_id: Optional[int] = typer.Option(None, "--source-release-id"), surah: Optional[int] = typer.Option(None, "--surah"), ayah: Optional[int] = typer.Option(None, "--ayah"), root: Optional[str] = typer.Option(None, "--root"), lemma: Optional[str] = typer.Option(None, "--lemma"), tag: Optional[str] = typer.Option(None, "--tag"), feature: Optional[str] = typer.Option(None, "--feature"), alignment_method: Optional[str] = typer.Option(None, "--alignment-method"), limit: int = typer.Option(50, "--limit"), offset: int = typer.Option(0, "--offset"), format: str = typer.Option("text", "--format")):
    _run_analytics("feature_frequency", source_release_id, surah, ayah, root, lemma, tag, feature, alignment_method, limit, offset, format)


@morph_stats_app.command("surahs")
def morphology_stats_surahs(source_release_id: Optional[int] = typer.Option(None, "--source-release-id"), surah: Optional[int] = typer.Option(None, "--surah"), ayah: Optional[int] = typer.Option(None, "--ayah"), root: Optional[str] = typer.Option(None, "--root"), lemma: Optional[str] = typer.Option(None, "--lemma"), tag: Optional[str] = typer.Option(None, "--tag"), feature: Optional[str] = typer.Option(None, "--feature"), alignment_method: Optional[str] = typer.Option(None, "--alignment-method"), limit: int = typer.Option(50, "--limit"), offset: int = typer.Option(0, "--offset"), format: str = typer.Option("text", "--format")):
    _run_analytics("surah_statistics", source_release_id, surah, ayah, root, lemma, tag, feature, alignment_method, limit, offset, format)


@morph_stats_app.command("ayahs")
def morphology_stats_ayahs(source_release_id: Optional[int] = typer.Option(None, "--source-release-id"), surah: Optional[int] = typer.Option(None, "--surah"), ayah: Optional[int] = typer.Option(None, "--ayah"), root: Optional[str] = typer.Option(None, "--root"), lemma: Optional[str] = typer.Option(None, "--lemma"), tag: Optional[str] = typer.Option(None, "--tag"), feature: Optional[str] = typer.Option(None, "--feature"), alignment_method: Optional[str] = typer.Option(None, "--alignment-method"), limit: int = typer.Option(50, "--limit"), offset: int = typer.Option(0, "--offset"), format: str = typer.Option("text", "--format")):
    _run_analytics("ayah_statistics", source_release_id, surah, ayah, root, lemma, tag, feature, alignment_method, limit, offset, format)


@morph_stats_app.command("segments")
def morphology_stats_segments(source_release_id: Optional[int] = typer.Option(None, "--source-release-id"), surah: Optional[int] = typer.Option(None, "--surah"), ayah: Optional[int] = typer.Option(None, "--ayah"), root: Optional[str] = typer.Option(None, "--root"), lemma: Optional[str] = typer.Option(None, "--lemma"), tag: Optional[str] = typer.Option(None, "--tag"), feature: Optional[str] = typer.Option(None, "--feature"), alignment_method: Optional[str] = typer.Option(None, "--alignment-method"), limit: int = typer.Option(50, "--limit"), offset: int = typer.Option(0, "--offset"), format: str = typer.Option("text", "--format")):
    _run_analytics("segment_distribution", source_release_id, surah, ayah, root, lemma, tag, feature, alignment_method, limit, offset, format)


@morphology_app.command("ingestion-stats")
def morphology_stats(ingestion_run_id: int):
    with session_scope() as s: echo(morph_stats(s, ingestion_run_id))

@morphology_app.command("export")
def morphology_export(ingestion_run_id: int, entity: str = typer.Option(..., "--entity"), format: str = typer.Option(..., "--format"), output: Path = typer.Option(..., "--output")):
    with session_scope() as s: echo(morph_export_entity(s, ingestion_run_id, entity, format, output))

@morphology_app.command("verify-export")
def morphology_verify_export(path: Path):
    with session_scope() as s:
        result = morph_verify_export(s, path)
    echo(result)
    if not result.get("ok"): raise typer.Exit(1)

if __name__ == "__main__": app()


def _phase5b_input(query: Optional[str], query_file: Optional[Path], input_format: Optional[str]) -> dict:
    if (query is None) == (query_file is None):
        raise AggregationError("ambiguous_count_semantics", "provide exactly one of --query or --query-file")
    payload = query_file.read_text(encoding="utf-8") if query_file else query or ""
    fmt = input_format or ("yaml" if query_file and query_file.suffix in {".yaml", ".yml"} else "json")
    if fmt == "json": return json.loads(payload)
    if fmt == "yaml":
        import yaml
        return yaml.safe_load(payload)
    raise AggregationError("ambiguous_count_semantics", "input format must be json or yaml")

def _phase5b_run(factory, operation: str, query: Optional[str], query_file: Optional[Path], input_format: Optional[str], format: str, output: Optional[Path] = None) -> None:
    try:
        request = factory(_phase5b_input(query, query_file, input_format))
        with session_scope() as session: result = getattr(ResearchEngine(session), operation)(request)
        data = result.to_dict() if hasattr(result, "to_dict") else result
        typer.echo(emit_research(data, format, output), nl=False)
    except (ResearchQueryError, AggregationError, AnnotationFrameworkError, OSError, ValueError) as exc:
        typer.echo(json.dumps(exc.to_dict() if hasattr(exc, "to_dict") else {"code":"invalid_research_query", "message":str(exc)}, ensure_ascii=False), err=True)
        raise typer.Exit(2) from exc

@research_app.command("aggregate")
def research_aggregate(query: Optional[str] = typer.Option(None, "--query"), query_file: Optional[Path] = typer.Option(None, "--query-file"), input_format: Optional[str] = typer.Option(None, "--input-format"), format: str = typer.Option("text", "--format"), output: Optional[Path] = typer.Option(None, "--output")):
    _phase5b_run(AggregateQuery.from_dict, "aggregate", query, query_file, input_format, format, output)
@research_app.command("set")
def research_set(query: Optional[str] = typer.Option(None, "--query"), query_file: Optional[Path] = typer.Option(None, "--query-file"), input_format: Optional[str] = typer.Option(None, "--input-format"), format: str = typer.Option("text", "--format"), output: Optional[Path] = typer.Option(None, "--output")):
    _phase5b_run(SetQuery.from_dict, "set", query, query_file, input_format, format, output)
@research_app.command("cooccurrence")
def research_cooccurrence(query: Optional[str] = typer.Option(None, "--query"), query_file: Optional[Path] = typer.Option(None, "--query-file"), input_format: Optional[str] = typer.Option(None, "--input-format"), format: str = typer.Option("text", "--format"), output: Optional[Path] = typer.Option(None, "--output")):
    _phase5b_run(CooccurrenceQuery.from_dict, "cooccurrence", query, query_file, input_format, format, output)
@research_app.command("explain")
def research_explain(query: Optional[str] = typer.Option(None, "--query"), query_file: Optional[Path] = typer.Option(None, "--query-file"), input_format: Optional[str] = typer.Option(None, "--input-format"), operation: str = typer.Option("aggregate", "--operation"), format: str = typer.Option("text", "--format")):
    factories={"aggregate":AggregateQuery.from_dict,"set":SetQuery.from_dict,"cooccurrence":CooccurrenceQuery.from_dict}
    if operation not in factories: raise typer.BadParameter("operation must be aggregate, set, or cooccurrence")
    _phase5b_run(factories[operation], "explain", query, query_file, input_format, format)

# Phase 5C commands are deliberately top-level, read-only certification boundaries.

def _verification_command(format: str, operation):
    try:
        with session_scope() as session:
            data = operation(session)
        typer.echo(render_verification(data, format))
        if data.get("status") in {"FAIL", "NOT_CERTIFIED"}:
            raise typer.Exit(1)
    except (VerificationError, ResearchQueryError, AggregationError, AnnotationFrameworkError, ValueError) as exc:
        typer.echo(json.dumps(exc.to_dict() if hasattr(exc, "to_dict") else {"code": "verification_error", "message": str(exc)}, ensure_ascii=False), err=True)
        raise typer.Exit(2) from exc


@app.command("verify")
def verify(format: str = typer.Option("text", "--format"), update_goldens: bool = typer.Option(False, "--update-goldens")):
    """Run deterministic golden and replay checks without persisting any result."""
    def operation(session):
        before = database_counts(session)
        contract = golden_contract()
        locks = compatibility_locks()
        golden = verify_goldens(session, update=update_goldens)
        replay = replay_goldens(session)
        after = database_counts(session)
        invariant = before == after
        passed = contract["passed"] and locks["failed"] == 0 and golden["failed"] == 0 and replay["failed"] == 0 and invariant
        return {"status": "PASS" if passed else "FAIL", "golden_contract": contract, "compatibility_locks": locks,
                "golden": golden, "replay": replay, "counts_before": before, "counts_after": after,
                "COUNTS_INVARIANT": invariant}
    _verification_command(format, operation)


@app.command("benchmark")
def benchmark_command(format: str = typer.Option("text", "--format")):
    """Run volatile read-only benchmark observations; no threshold or persistence exists."""
    _verification_command(format, verification_benchmark)


@app.command("release-manifest")
def release_manifest_command(format: str = typer.Option("text", "--format")):
    _verification_command(format, release_manifest)


@app.command("research-certificate")
def research_certificate_command(format: str = typer.Option("text", "--format")):
    def operation(session):
        before = database_counts(session)
        contract = golden_contract()
        locks = compatibility_locks()
        golden = verify_goldens(session)
        replay = replay_goldens(session)
        after = database_counts(session)
        invariant = before == after
        status = "PASS" if contract["passed"] and locks["failed"] == golden["failed"] == replay["failed"] == 0 and invariant else "NOT_CERTIFIED"
        return research_certificate(session, {"passed": golden["passed"] + replay["passed"] + locks["passed"], "failed": golden["failed"] + replay["failed"] + locks["failed"], "warnings": 0, "status": status, "COUNTS_INVARIANT": invariant, "GOLDEN_CONTRACT": contract["passed"], "counts_before": before, "counts_after": after})
    _verification_command(format, operation)
