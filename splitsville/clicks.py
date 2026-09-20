"""Transient / click detection for a measure click track."""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, filtfilt, find_peaks


def _highpass(y: np.ndarray, sr: int, cutoff_hz: float = 3500.0) -> np.ndarray:
    nyquist = sr / 2.0
    cutoff = min(cutoff_hz, nyquist * 0.9)
    b, a = butter(2, cutoff / nyquist, btype="high")
    return filtfilt(b, a, y.astype(np.float64))


def click_envelope(y: np.ndarray, sr: int, smooth_ms: float = 8.0) -> np.ndarray:
    if y.ndim > 1:
        y = np.mean(y, axis=1)
    y = y - np.mean(y)
    hp = _highpass(y, sr)
    env = np.abs(hp)
    win = max(1, int(sr * smooth_ms / 1000.0))
    kernel = np.ones(win, dtype=np.float64) / win
    return np.convolve(env, kernel, mode="same")


def detect_click_times(
    y: np.ndarray,
    sr: int,
    min_interval: float = 0.6,
    threshold: float = 0.25,
) -> np.ndarray:
    """Return click times in seconds from a measure click track."""
    env = click_envelope(y, sr)
    peak = float(np.max(env))
    if peak <= 1e-12:
        return np.array([], dtype=np.float64)

    hop = max(1, sr // 400)
    env_ds = env[::hop]
    return _peaks_from_envelope(
        env_ds, sr, hop, peak, min_interval=min_interval, threshold=threshold
    )


def _peaks_from_envelope(
    env_ds: np.ndarray,
    sr: int,
    hop: int,
    peak: float,
    *,
    min_interval: float,
    threshold: float,
) -> np.ndarray:
    height = threshold * peak
    distance = max(1, int(min_interval * sr / hop))
    peaks, _ = find_peaks(env_ds, height=height, distance=distance)
    return peaks.astype(np.float64) * hop / sr


def measures_from_clicks(
    click_times: np.ndarray,
    duration: float,
) -> list[tuple[int, float, float]]:
    """Build [start, end) measure windows from downbeat clicks."""
    clicks = np.asarray(click_times, dtype=np.float64)
    clicks = clicks[(clicks >= 0) & (clicks < duration)]
    clicks = np.unique(np.round(clicks, 6))
    if clicks.size == 0:
        return []

    bounds = list(clicks)
    if bounds[-1] < duration - 1e-4:
        bounds.append(duration)

    measures: list[tuple[int, float, float]] = []
    for i in range(len(bounds) - 1):
        start, end = float(bounds[i]), float(bounds[i + 1])
        if end - start > 1e-4:
            measures.append((i, start, end))
    return measures
