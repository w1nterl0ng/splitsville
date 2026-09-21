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


def test_silent_flags_marks_empty_bar():
    from splitsville.match import silent_flags

    sr = 22050
    t = np.arange(int(sr * 0.8)) / sr
    tone = (0.2 * np.sin(2 * np.pi * 110 * t)).astype(np.float32).reshape(-1, 1)
    rest = np.zeros_like(tone)
    hush = (1e-6 * np.sin(2 * np.pi * 110 * t)).astype(np.float32).reshape(-1, 1)
    flags = silent_flags([tone, rest, hush, tone])
    assert flags == [False, True, True, False]


def test_duration_gate_rejects_short_bar():
    click, stem, sr, sequence = make_demo()
    duration = stem.shape[0] / sr
    times = detect_click_times(click, sr)
    measures = measures_from_clicks(times, duration)
    slices = slice_stem(stem.reshape(-1, 1), sr, measures)
    half = slices[0][: slices[0].shape[0] // 2]
    sim = slice_similarity_matrix([slices[0], slices[2], half], sr)
    assert sim[0, 1] >= 0.85
    assert sim[0, 2] < 0.2
    assert sim[1, 2] < 0.2


def test_subdiv_ratings_flag_changed_last_beat():
    from splitsville.match import group_subdiv_ratings

    sr = 22050
    n = sr
    t = np.arange(n) / sr
    same = np.sin(2 * np.pi * 110 * t).astype(np.float32).reshape(-1, 1)
    varied = same.copy()
    varied[int(0.75 * n) :] = np.sin(2 * np.pi * 196 * t[int(0.75 * n) :]).reshape(-1, 1)
    ratings = group_subdiv_ratings([same, varied], sr, [[0, 1]], [4, 4])
    assert ratings[0] == [1.0, 1.0, 1.0, 1.0]
    assert ratings[1][0] > 0.9
    assert ratings[1][3] < 0.8
    assert ratings[1][3] < ratings[1][0]


def test_detect_band_low_vs_high_tone():
    from splitsville.match import detect_band

    sr = 22050
    t = np.arange(int(sr * 2)) / sr
    bass = np.sin(2 * np.pi * 80 * t).astype(np.float32).reshape(-1, 1)
    guitar = np.sin(2 * np.pi * 800 * t).astype(np.float32).reshape(-1, 1)
    bname, bmin, bmax = detect_band(bass, sr)
    gname, gmin, gmax = detect_band(guitar, sr)
    assert bname == "bass"
    assert bmax <= 400
    assert gname == "guitar"
    assert gmax >= 2000


def test_pipeline_reports_silent_bar():
    click, stem, sr, sequence = make_demo()
    bar = stem.size // len(sequence)
    stem = stem.copy()
    stem[3 * bar : 4 * bar] = 0
    import soundfile as sf
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        click_path = d / "click.wav"
        stem_path = d / "stem.wav"
        sf.write(click_path, click, sr)
        sf.write(stem_path, stem, sr)
        result = run_pipeline(click_path, stem_path)
    assert len(result.silent) == len(sequence)
    assert result.silent[3] is True
    assert result.silent[0] is False


def test_pipeline_writes_slices(tmp_path: Path):
    click_path, stem_path, sequence = write_demo(tmp_path / "demo")
    result = run_pipeline(click_path, stem_path, out_dir=tmp_path / "out")
    assert len(result.slices) == len(sequence)
    assert len(result.slice_paths) == len(sequence)
    assert all(p.exists() for p in result.slice_paths)
    assert np.isfinite(result.similarity).all()


from splitsville.xsc import beat_times, parse_timestamp, parse_xsc, parse_xsc_markers


def test_peak_envelope_has_stereo_lanes():
    from splitsville.waveform import peak_envelope

    click, stem, sr, _ = make_demo()
    peaks = peak_envelope(stem.reshape(-1, 1), sr, peaks_per_sec=50)
    assert len(peaks["ch"]) == 2
    assert peaks["n"] > 10
    assert len(peaks["ch"][0]["max"]) == peaks["n"]


def test_parse_xsc_measure_times():
    path = Path(__file__).parent / "fixtures" / "markers.xsc"
    markers = parse_xsc_markers(path)
    assert [m.label for m in markers] == ["A1", "A2", "A9", "B10"]
    assert markers[0].kind == "S"
    assert markers[2].time == parse_timestamp("0:00:15.964375")
    assert abs(markers[2].time - 15.964375) < 1e-9
    assert markers[2].subdivisions == 2
    assert markers[1].subdivisions == 4
    assert markers[3].kind == "S"
    doc = parse_xsc(path)
    assert doc.sound_path is not None
    assert doc.sound_path.name == "does-not-exist.wav"
    assert doc.sample_rate == 44100
    beats = beat_times(markers, 20.0)
    assert abs(beats[0] - 0.5) < 1e-9
    assert abs(beats[1] - 1.0) < 1e-9
    assert abs(beats[2] - 1.5) < 1e-9
    a9_beats = [b for b in beats if 15.9 < b < 17.3]
    assert len(a9_beats) == 1
    assert abs(a9_beats[0] - (15.964375 + (17.262774 - 15.964375) / 2)) < 1e-6


def test_pipeline_accepts_xsc_markers(tmp_path: Path):
    import soundfile as sf

    _click, stem, sr, sequence = make_demo()
    duration = stem.shape[-1] / sr if stem.ndim == 1 else stem.shape[0] / sr
    times = [i * (duration / len(sequence)) for i in range(len(sequence))]
    xsc = tmp_path / "map.xsc"
    lines = ["SectionStart,Markers", f"Howmany,{len(times)}"]
    for i, t in enumerate(times):
        kind = "S" if i == 0 else "M"
        lines.append(f"{kind},-1,1,A{i + 1},4,0:00:{t:09.6f},")
    lines.append("SectionEnd,Markers")
    xsc.write_text("Transcribe! test\n" + "\n".join(lines) + "\n")
    stem_path = tmp_path / "stem.wav"
    sf.write(stem_path, stem, sr)
    result = run_pipeline(xsc, stem_path)
    assert result.marker_source == "xsc"
    assert len(result.click_times) == len(sequence)
    assert result.labels[0] == "A1"
    assert abs(result.click_times[0]) < 0.02
    assert len(result.beat_times) == 3 * len(sequence)


def test_pipeline_loads_stem_from_xsc_soundfilename(tmp_path: Path):
    import soundfile as sf

    _click, stem, sr, sequence = make_demo()
    duration = stem.shape[-1] / sr if stem.ndim == 1 else stem.shape[0] / sr
    times = [i * (duration / len(sequence)) for i in range(len(sequence))]
    stem_path = tmp_path / "from-xsc.wav"
    sf.write(stem_path, stem, sr)
    xsc = tmp_path / "map.xsc"
    lines = [
        "Transcribe! test",
        f"SoundFileName,{stem_path.name},MacOSX,{stem_path}",
        "SoundFileInfo,WAV,WAV,1,100,44100,44100,1.000000",
        "SectionStart,Markers",
        f"Howmany,{len(times)}",
    ]
    for i, t in enumerate(times):
        kind = "S" if i == 0 else "M"
        lines.append(f"{kind},-1,1,A{i + 1},4,0:00:{t:09.6f},")
    lines.append("SectionEnd,Markers")
    xsc.write_text("\n".join(lines) + "\n")
    result = run_pipeline(xsc)
    assert result.sound_path == str(stem_path)
    assert len(result.measures) == len(sequence)
    assert len(result.beat_times) == 3 * len(sequence)
