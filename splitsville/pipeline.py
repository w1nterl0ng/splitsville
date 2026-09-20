from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .clicks import detect_click_times, measures_from_clicks
from .match import (
    BAND_PRESETS,
    detect_band,
    feature_matrix,
    group_matches,
    group_subdiv_ratings,
    slice_similarity_matrix,
)
from .split import load_audio, slice_stem, write_slices
from .synth import clicks_from_times
from .xsc import beat_times, looks_like_xsc, parse_xsc, source_bytes


@dataclass
class PipelineResult:
    click_sr: int
    stem_sr: int
    click_times: np.ndarray
    measures: list[tuple[int, float, float]]
    slices: list[np.ndarray]
    features: np.ndarray
    similarity: np.ndarray
    groups: list[list[int]]
    click: np.ndarray
    labels: list[str] = field(default_factory=list)
    beat_times: list[float] = field(default_factory=list)
    marker_source: str = "audio"
    sound_path: str | None = None
    subdivs: list[int] = field(default_factory=list)
    subdiv_ratings: dict[int, list[float]] = field(default_factory=dict)
    band_name: str = "bass"
    fmin: float = 40.0
    fmax: float = 400.0
    slice_paths: list[Path] = field(default_factory=list)


def run_pipeline(
    click_source,
    stem_source=None,
    *,
    min_interval: float = 0.6,
    click_threshold: float = 0.25,
    match_threshold: float = 0.85,
    out_dir: Path | None = None,
    instrument: str = "auto",
) -> PipelineResult:
    marker_bytes = source_bytes(click_source)
    labels: list[str] = []
    beats: list[float] = []
    subdivs: list[int] = []
    sound_path: str | None = None
    xsc_doc = None

    if looks_like_xsc(marker_bytes):
        origin = click_source if isinstance(click_source, (str, Path)) else marker_bytes
        xsc_doc = parse_xsc(origin)
        if stem_source is None:
            if xsc_doc.sound_path is None or not xsc_doc.sound_path.exists():
                raise FileNotFoundError(
                    "XSC has no usable SoundFileName; pass a stem file as well."
                )
            stem_source = xsc_doc.sound_path
        sound_path = str(xsc_doc.sound_path) if xsc_doc.sound_path else None
    elif stem_source is None:
        raise FileNotFoundError("Stem is required when the marker source is audio.")

    stem, stem_sr = load_audio(stem_source)
    duration = stem.shape[0] / stem_sr

    if xsc_doc is not None:
        click_times = np.array([m.time for m in xsc_doc.markers], dtype=np.float64)
        labels = [m.label for m in xsc_doc.markers]
        subdivs = [max(1, m.subdivisions) for m in xsc_doc.markers]
        beats = beat_times(xsc_doc.markers, duration)
        click = clicks_from_times(click_times, duration, stem_sr)
        click_sr = stem_sr
        marker_source = "xsc"
    else:
        click, click_sr = load_audio(click_source)
        click_times = detect_click_times(
            click,
            click_sr,
            min_interval=min_interval,
            threshold=click_threshold,
        )
        marker_source = "audio"

    measures = measures_from_clicks(click_times, duration)
    if labels and len(labels) > len(measures):
        labels = labels[: len(measures)]
    if subdivs and len(subdivs) > len(measures):
        subdivs = subdivs[: len(measures)]
    if not subdivs:
        subdivs = [4] * len(measures)
    slices = slice_stem(stem, stem_sr, measures)
    instrument = (instrument or "auto").lower()
    if instrument in BAND_PRESETS:
        band_name = instrument
        fmin, fmax = BAND_PRESETS[instrument]
    else:
        band_name, fmin, fmax = detect_band(stem, stem_sr)
    features = feature_matrix(slices, stem_sr, fmin=fmin, fmax=fmax)
    similarity = slice_similarity_matrix(slices, stem_sr, fmin=fmin, fmax=fmax)
    groups = group_matches(similarity, threshold=match_threshold)
    subdiv_ratings = group_subdiv_ratings(
        slices, stem_sr, groups, subdivs, fmin=fmin, fmax=fmax
    )

    slice_paths: list[Path] = []
    if out_dir is not None:
        slice_paths = write_slices(slices, stem_sr, Path(out_dir) / "measures")

    return PipelineResult(
        click_sr=click_sr,
        stem_sr=stem_sr,
        click_times=click_times,
        measures=measures,
        slices=slices,
        features=features,
        similarity=similarity,
        groups=groups,
        click=click,
        labels=labels,
        beat_times=beats,
        marker_source=marker_source,
        sound_path=sound_path,
        subdivs=subdivs,
        subdiv_ratings=subdiv_ratings,
        band_name=band_name,
        fmin=fmin,
        fmax=fmax,
        slice_paths=slice_paths,
    )
