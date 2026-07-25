"""Deterministic, read-only rendering for public research results."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

FORMATS = {"text", "json", "yaml", "csv", "jsonl", "markdown"}


def _cell(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    for key in ("matches", "groups", "results", "pairs"):
        value = payload.get(key)
        if isinstance(value, list):
            return [{str(k): _cell(v) for k, v in row.items()} if isinstance(row, Mapping) else {key: _cell(row)} for row in value]
    return [{str(k): _cell(v) for k, v in payload.items()}]


def render_research(payload: Mapping[str, Any], format: str) -> str:
    """Render public research data with UTF-8-safe, deterministic bytes."""
    if format not in FORMATS:
        raise ValueError("format must be text, json, yaml, csv, jsonl, or markdown")
    data = dict(payload)
    if isinstance(data.get("metadata"), Mapping):
        data["metadata"] = {
            key: value
            for key, value in data["metadata"].items()
            if key not in {"executed_at_utc", "duration_ms"}
        }
    if format == "json":
        return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    if format == "yaml":
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=True)
    if format == "text":
        reproducibility_hash = data.get("reproducibility_hash", data.get("metadata", {}).get("reproducibility_hash", ""))
        lines = [f"reproducibility_hash={reproducibility_hash}"]
        if "matches" in data:
            summary = data.get("summary", {})
            lines.append(f"returned_rows={summary.get('returned_rows', 0)} total_matching_rows={summary.get('total_matching_rows', 0)}")
            for match in data["matches"]:
                if not isinstance(match, Mapping) or "coordinate" not in match:
                    continue
                coordinate = match["coordinate"]
                lines.append(f"{coordinate['surah']}:{coordinate['ayah']}:{coordinate['token']}:{match['segment']} root={match['root']} lemma={match['lemma']} pos={match['pos']}")
        return "\n".join(lines) + "\n"
    rows = _rows(data)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    if format == "jsonl":
        return "".join(json.dumps({key: row.get(key) for key in columns}, ensure_ascii=False, separators=(",", ":"), default=str) + "\n" for row in rows)
    if format == "csv":
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)
        return stream.getvalue()
    def escaped(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", "<br>")

    return "| " + " | ".join(columns) + " |\n| " + " | ".join("---" for _ in columns) + " |\n" + "".join("| " + " | ".join(escaped(row.get(column, "")) for column in columns) + " |\n" for row in rows)


def emit_research(payload: Mapping[str, Any], format: str, output: Path | None = None) -> str:
    rendered = render_research(payload, format)
    if output is not None:
        output.write_text(rendered, encoding="utf-8", newline="\n")
        return ""
    return rendered
