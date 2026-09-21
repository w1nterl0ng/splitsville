"""Versioned Splitsville session/project files.

A ``.splitsville`` file is a zip:

    project.json   versioned document (settings, analysis, per-measure meta)
    media/markers  Transcribe .xsc or click audio
    media/stem     stem used for playback/matching

``project.json`` can also be saved/loaded alone when media already lives on disk
(paths in ``sources``). Extra keys are preserved so later metadata can land
without a format bump.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

FORMAT = "splitsville-project"
VERSION = 1

MEDIA_MARKERS = "media/markers"
MEDIA_STEM = "media/stem"
PROJECT_JSON = "project.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def empty_measure_meta(label: str = "", **extra: Any) -> dict[str, Any]:
    row = {
        "label": label,
        "locked": False,
        "status": "open",  # open | done — locked True implies done
        "notes": "",
        "tags": [],
        "meta": {},
    }
    row.update(extra)
    return row


def measure_meta_list(n: int, labels: list[str] | None = None) -> list[dict[str, Any]]:
    labels = list(labels or [])
    out = []
    for i in range(n):
        label = labels[i] if i < len(labels) else f"bar {i + 1}"
        out.append(empty_measure_meta(label))
    return out


def meta_by_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(i): dict(row) for i, row in enumerate(rows)}


def apply_lock_map(
    rows: list[dict[str, Any]],
    locked: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Merge CCv2/JS lock map into the project measure list without dropping extra keys."""
    if not locked:
        return rows
    out = [dict(r) for r in rows]
    for key, val in locked.items():
        try:
            i = int(key)
        except (TypeError, ValueError):
            continue
        if i < 0 or i >= len(out):
            continue
        if isinstance(val, dict):
            out[i] = {**out[i], **val}
        else:
            out[i]["locked"] = bool(val)
        if out[i].get("locked"):
            out[i]["status"] = "done"
        elif out[i].get("status") == "done" and not out[i].get("locked"):
            out[i]["status"] = "open"
    return out


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
    except ImportError:
        pass
    return value


def new_document(
    *,
    name: str = "Untitled",
    settings: dict[str, Any] | None = None,
    sources: dict[str, Any] | None = None,
    analysis: dict[str, Any] | None = None,
    measures: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    doc: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "name": name,
        "created": now,
        "updated": now,
        "settings": settings or {},
        "sources": sources or {},
        "analysis": _json_ready(analysis or {}),
        "measures": measures or [],
        "project_meta": {},
    }
    if extra:
        for key, val in extra.items():
            if key not in doc:
                doc[key] = val
    return doc


def dumps(doc: dict[str, Any]) -> str:
    payload = dict(doc)
    payload["format"] = FORMAT
    payload["version"] = int(payload.get("version") or VERSION)
    payload["updated"] = utc_now()
    return json.dumps(payload, indent=2)


def loads(raw: str | bytes) -> dict[str, Any]:
    doc = json.loads(raw)
    if not isinstance(doc, dict):
        raise ValueError("Project file is not an object")
    fmt = doc.get("format")
    if fmt not in {FORMAT, None}:
        raise ValueError(f"Not a Splitsville project ({fmt!r})")
    doc.setdefault("format", FORMAT)
    doc.setdefault("version", VERSION)
    doc.setdefault("name", "Untitled")
    doc.setdefault("settings", {})
    doc.setdefault("sources", {})
    doc.setdefault("analysis", {})
    doc.setdefault("measures", [])
    doc.setdefault("project_meta", {})
    return doc


def pack_zip(
    doc: dict[str, Any],
    *,
    markers: bytes,
    stem: bytes,
    markers_name: str = "markers",
    stem_name: str = "stem",
) -> bytes:
    sources = dict(doc.get("sources") or {})
    sources["markers_name"] = markers_name
    sources["stem_name"] = stem_name
    sources["markers_bytes"] = len(markers)
    sources["stem_bytes"] = len(stem)
    packed = dict(doc)
    packed["sources"] = sources
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(PROJECT_JSON, dumps(packed))
        zf.writestr(MEDIA_MARKERS, markers)
        zf.writestr(MEDIA_STEM, stem)
    return buf.getvalue()


def unpack_zip(raw: bytes) -> tuple[dict[str, Any], bytes, bytes]:
    with zipfile.ZipFile(BytesIO(raw)) as zf:
        names = zf.namelist()
        json_name = PROJECT_JSON if PROJECT_JSON in names else next(
            n for n in names if n.endswith(".json")
        )
        doc = loads(zf.read(json_name))
        markers = zf.read(MEDIA_MARKERS) if MEDIA_MARKERS in names else b""
        stem = zf.read(MEDIA_STEM) if MEDIA_STEM in names else b""
    return doc, markers, stem


def looks_like_project_zip(raw: bytes) -> bool:
    if len(raw) < 4 or raw[:2] != b"PK":
        return False
    try:
        with zipfile.ZipFile(BytesIO(raw)) as zf:
            names = zf.namelist()
        return PROJECT_JSON in names or any(n.endswith(".json") for n in names)
    except zipfile.BadZipFile:
        return False


def load_any(raw: bytes) -> tuple[dict[str, Any], bytes | None, bytes | None]:
    """Load a .splitsville zip or a bare project.json."""
    if looks_like_project_zip(raw):
        doc, markers, stem = unpack_zip(raw)
        return doc, markers, stem
    text = raw.decode("utf-8")
    doc = loads(text)
    markers = stem = None
    sources = doc.get("sources") or {}
    for key, dest in (("markers_path", "markers"), ("stem_path", "stem")):
        path = sources.get(key)
        if not path:
            continue
        p = Path(path).expanduser()
        if p.is_file():
            if dest == "markers":
                markers = p.read_bytes()
            else:
                stem = p.read_bytes()
    return doc, markers, stem
