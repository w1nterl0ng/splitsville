"""Synthetic click track + repeating-measure stem for the POC."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf


def _click(sr: int, dur: float = 0.012) -> np.ndarray:
    n = int(sr * dur)
    t = np.arange(n) / sr
    burst = np.sin(2 * np.pi * 4000 * t) * np.hanning(n)
    return burst.astype(np.float32)


def clicks_from_times(
    times,
    duration: float,
    sr: int,
) -> np.ndarray:
    """Render a mono click track from marker times, shaped (n_samples, 1)."""
    n = max(1, int(round(duration * sr)))
    track = np.zeros(n, dtype=np.float32)
    burst = _click(sr)
    for t in times:
        start = int(round(float(t) * sr))
        if start < 0 or start >= n:
            continue
        stop = min(n, start + burst.size)
        track[start:stop] += burst[: stop - start]
    return np.clip(track, -1.0, 1.0).reshape(-1, 1)


def _tone_chord(freqs: list[float], sr: int, dur: float) -> np.ndarray:
    t = np.arange(int(sr * dur)) / sr
    wave = np.zeros_like(t, dtype=np.float64)
    for f in freqs:
        wave += 0.28 * np.sin(2 * np.pi * f * t)
    attack = int(0.02 * sr)
    release = int(0.08 * sr)
    env = np.ones_like(t)
    env[:attack] = np.linspace(0, 1, attack)
    env[-release:] = np.linspace(1, 0, release)
    return (wave * env).astype(np.float32)


PATTERNS = {
    "A": [261.63, 329.63, 392.00],  # C
    "B": [196.00, 246.94, 392.00],  # G
    "C": [174.61, 220.00, 261.63],  # F
}


def make_demo(sr: int = 44100, bpm: float = 100.0, bars: int = 8) -> tuple[np.ndarray, np.ndarray, int, list[str]]:
    """8 bars at 4/4: A B A C A B A C — A/B/C should group together."""
    bar_dur = 4.0 * 60.0 / bpm
    sequence = ["A", "B", "A", "C", "A", "B", "A", "C"][:bars]
    n = int(round(bar_dur * bars * sr))
    click = np.zeros(n, dtype=np.float32)
    stem = np.zeros(n, dtype=np.float32)
    click_sample = _click(sr)

    for i, name in enumerate(sequence):
        start = int(round(i * bar_dur * sr))
        end = int(round((i + 1) * bar_dur * sr))
        chord = _tone_chord(PATTERNS[name], sr, (end - start) / sr)
        stem[start : start + chord.size] += chord[: end - start]
        stop = min(n, start + click_sample.size)
        click[start:stop] += click_sample[: stop - start]

    click = np.clip(click, -1.0, 1.0)
    stem = np.clip(stem, -1.0, 1.0)
    return click, stem, sr, sequence


def write_demo(out_dir: Path, sr: int = 44100) -> tuple[Path, Path, list[str]]:
    click, stem, sr, sequence = make_demo(sr=sr)
    out_dir.mkdir(parents=True, exist_ok=True)
    click_path = out_dir / "demo_clicks.wav"
    stem_path = out_dir / "demo_stem.wav"
    sf.write(click_path, click, sr)
    sf.write(stem_path, stem, sr)
    return click_path, stem_path, sequence
