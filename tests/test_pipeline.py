from pathlib import Path

import numpy as np

from splitsville.clicks import detect_click_times, measures_from_clicks
from splitsville.match import group_matches, slice_similarity_matrix
from splitsville.pipeline import run_pipeline
from splitsville.split import slice_stem
from splitsville.synth import make_demo, write_demo


def test_detects_one_click_per_bar():
    click, stem, sr, sequence = make_demo()
    times = detect_click_times(click, sr, min_interval=0.6, threshold=0.25)
    assert len(times) == len(sequence)
    bar_dur = 4.0 * 60.0 / 100.0
    for i, t in enumerate(times):
        assert abs(t - i * bar_dur) < 0.03


def test_measures_cover_stem():
    click, stem, sr, sequence = make_demo()
    duration = stem.shape[0] / sr
    times = detect_click_times(click, sr)
    measures = measures_from_clicks(times, duration)
    assert len(measures) == len(sequence)
    assert measures[0][1] < 0.05
    assert abs(measures[-1][2] - duration) < 1e-3


def test_matching_groups_repeated_chords():
    click, stem, sr, sequence = make_demo()
    duration = stem.shape[0] / sr
    times = detect_click_times(click, sr)
    measures = measures_from_clicks(times, duration)
    slices = slice_stem(stem.reshape(-1, 1), sr, measures)
    sim = slice_similarity_matrix(slices, sr)
    groups = group_matches(sim, threshold=0.85)

    by_name: dict[str, list[int]] = {}
    for i, name in enumerate(sequence):
        by_name.setdefault(name, []).append(i)

    grouped = {frozenset(g) for g in groups}
    expected = {frozenset(v) for v in by_name.values() if len(v) >= 2}
    assert grouped == expected


def test_pipeline_writes_slices(tmp_path: Path):
    click_path, stem_path, sequence = write_demo(tmp_path / "demo")
    result = run_pipeline(click_path, stem_path, out_dir=tmp_path / "out")
    assert len(result.slices) == len(sequence)
    assert len(result.slice_paths) == len(sequence)
    assert all(p.exists() for p in result.slice_paths)
    assert np.isfinite(result.similarity).all()


def test_peak_envelope_has_stereo_lanes():
    from splitsville.waveform import peak_envelope

    click, stem, sr, _ = make_demo()
    peaks = peak_envelope(stem.reshape(-1, 1), sr, peaks_per_sec=50)
    assert len(peaks["ch"]) == 2
    assert peaks["n"] > 10
    assert len(peaks["ch"][0]["max"]) == peaks["n"]
