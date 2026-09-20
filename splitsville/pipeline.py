from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .clicks import detect_click_times, measures_from_clicks
from .match import feature_matrix, group_matches, slice_similarity_matrix
from .split import load_audio, slice_stem, write_slices


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
    slice_paths: list[Path] = field(default_factory=list)


def run_pipeline(
    click_source,
    stem_source,
    *,
    min_interval: float = 0.6,
    click_threshold: float = 0.25,
    match_threshold: float = 0.85,
    out_dir: Path | None = None,
) -> PipelineResult:
    click, click_sr = load_audio(click_source)
    stem, stem_sr = load_audio(stem_source)
    duration = stem.shape[0] / stem_sr

    click_times = detect_click_times(
        click,
        click_sr,
        min_interval=min_interval,
        threshold=click_threshold,
    )
    measures = measures_from_clicks(click_times, duration)
    slices = slice_stem(stem, stem_sr, measures)
    features = feature_matrix(slices, stem_sr)
    similarity = slice_similarity_matrix(slices, stem_sr)
    groups = group_matches(similarity, threshold=match_threshold)

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
        slice_paths=slice_paths,
    )
