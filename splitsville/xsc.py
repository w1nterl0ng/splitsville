"""Parse Transcribe! .xsc marker maps."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class XscMarker:
    kind: str
    label: str
    subdivisions: int
    time: float


@dataclass(frozen=True)
class XscDocument:
    markers: list[XscMarker]
    sound_path: Path | None = None
    sample_rate: int | None = None
    duration: float | None = None


def looks_like_xsc(data: bytes) -> bool:
    head = data.lstrip()[:64]
    return head.startswith(b"Transcribe!") or b"SectionStart,Markers" in data[:8000]


def source_bytes(source) -> bytes:
    if isinstance(source, (str, Path)):
        return Path(source).read_bytes()
    if hasattr(source, "read"):
        pos = source.tell() if hasattr(source, "tell") else None
        data = source.read()
        if pos is not None and hasattr(source, "seek"):
            try:
                source.seek(pos)
            except Exception:
                pass
        return data
    return bytes(source)


def parse_timestamp(value: str) -> float:
    parts = value.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"unrecognized Transcribe timestamp: {value!r}")
    hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_xsc(source) -> XscDocument:
    origin = Path(source) if isinstance(source, (str, Path)) else None
    raw = source if isinstance(source, (bytes, bytearray)) else source_bytes(source)
    text = raw.decode("utf-8", errors="replace")
    in_markers = False
    inherited = 4
    markers: list[XscMarker] = []
    sound_path: Path | None = None
    sample_rate: int | None = None
    duration: float | None = None

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("SoundFileName,"):
            fields = [part.strip() for part in line.split(",")]
            if len(fields) >= 2:
                sound_path = _resolve_sound_path(fields[-1], fields[1], origin)
            continue
        if line.startswith("SoundFileInfo,"):
            fields = [part.strip() for part in line.split(",")]
            if len(fields) >= 4:
                try:
                    sample_rate = int(fields[-3])
                    duration = float(fields[-1])
                except ValueError:
                    pass
            continue
        if line == "SectionStart,Markers":
            in_markers = True
            continue
        if in_markers and line.startswith("SectionEnd"):
            in_markers = False
            continue
        if not in_markers or not line or line.startswith("Howmany"):
            continue
        fields = [part.strip() for part in line.split(",")]
        kind = fields[0]
        if kind not in {"S", "M"} or len(fields) < 6:
            continue
        subdiv = int(fields[4])
        if subdiv <= 0:
            subdiv = inherited
        else:
            inherited = subdiv
        markers.append(
            XscMarker(
                kind=kind,
                label=fields[3],
                subdivisions=subdiv,
                time=parse_timestamp(fields[5]),
            )
        )
    markers.sort(key=lambda m: m.time)
    return XscDocument(
        markers=markers,
        sound_path=sound_path,
        sample_rate=sample_rate,
        duration=duration,
    )


def parse_xsc_markers(source) -> list[XscMarker]:
    return parse_xsc(source).markers


def beat_times(markers: list[XscMarker], duration: float) -> list[float]:
    """Interior beat times from each measure's subdivision count."""
    beats: list[float] = []
    for i, marker in enumerate(markers):
        start = marker.time
        end = markers[i + 1].time if i + 1 < len(markers) else duration
        count = max(1, marker.subdivisions)
        span = end - start
        if span <= 1e-4:
            continue
        step = span / count
        for k in range(1, count):
            beats.append(start + k * step)
    return beats


def _resolve_sound_path(raw_path: str, filename: str, origin: Path | None) -> Path:
    path = Path(raw_path)
    if path.exists():
        return path
    if origin is not None:
        beside = origin.parent / filename
        if beside.exists():
            return beside
        beside = origin.parent / path.name
        if beside.exists():
            return beside
    return path
