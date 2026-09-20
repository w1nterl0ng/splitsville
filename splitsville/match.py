"""Classical DSP features and measure-to-measure matching."""

from __future__ import annotations

import numpy as np
from scipy.signal import stft


def _mono(y: np.ndarray) -> np.ndarray:
    if y.ndim == 2:
        return np.mean(y, axis=1)
    return y


def _stft_mag(y: np.ndarray, sr: int, n_fft: int, hop: int) -> tuple[np.ndarray, np.ndarray]:
    y = _mono(y).astype(np.float64)
    if y.size < n_fft:
        y = np.pad(y, (0, n_fft - y.size))
    freqs, _, zxx = stft(y, fs=sr, nperseg=n_fft, noverlap=n_fft - hop, boundary=None)
    return freqs, np.abs(zxx)


def chroma_mean(y: np.ndarray, sr: int, n_fft: int = 2048, hop: int = 512) -> np.ndarray:
    freqs, mag = _stft_mag(y, sr, n_fft, hop)
    chroma = np.zeros(12, dtype=np.float64)
    for i, freq in enumerate(freqs):
        if freq < 30:
            continue
        midi = 69.0 + 12.0 * np.log2(freq / 440.0)
        pc = int(np.round(midi)) % 12
        chroma[pc] += float(np.mean(mag[i]))
    norm = np.linalg.norm(chroma)
    if norm > 1e-12:
        chroma /= norm
    return chroma


def band_energies(y: np.ndarray, sr: int, n_bands: int = 8) -> np.ndarray:
    freqs, mag = _stft_mag(y, sr, 2048, 1024)
    mag = np.mean(mag, axis=1)
    edges = np.geomspace(40, min(sr / 2 - 1, 8000), n_bands + 1)
    bands = np.zeros(n_bands, dtype=np.float64)
    for i in range(n_bands):
        mask = (freqs >= edges[i]) & (freqs < edges[i + 1])
        if np.any(mask):
            bands[i] = float(np.mean(mag[mask]))
    norm = np.linalg.norm(bands)
    if norm > 1e-12:
        bands /= norm
    return bands


def amplitude_shape(y: np.ndarray, n_bins: int = 32) -> np.ndarray:
    y = np.abs(_mono(y).astype(np.float64))
    if y.size == 0:
        return np.zeros(n_bins, dtype=np.float64)
    win = max(1, y.size // 200)
    kernel = np.ones(win) / win
    smooth = np.convolve(y, kernel, mode="same")
    idx = np.linspace(0, smooth.size - 1, n_bins)
    shape = np.interp(idx, np.arange(smooth.size), smooth)
    norm = np.linalg.norm(shape)
    if norm > 1e-12:
        shape /= norm
    return shape


def pitch_contour(y: np.ndarray, sr: int, n_frames: int = 24) -> np.ndarray:
    """Dominant bass-range frequency per frame, resampled to a fixed length."""
    freqs, mag = _stft_mag(y, sr, n_fft=8192, hop=1024)
    mask = (freqs >= 28.0) & (freqs <= 400.0)
    if not np.any(mask) or mag.size == 0:
        return np.zeros(n_frames, dtype=np.float64)
    sub = mag[mask]
    peak = np.argmax(sub, axis=0)
    f0 = freqs[mask][peak]
    energy = sub.max(axis=0)
    cutoff = 0.02 * (float(np.max(energy)) + 1e-12)
    f0 = np.where(energy >= cutoff, f0, np.nan)
    t_old = np.linspace(0.0, 1.0, f0.size)
    valid = np.isfinite(f0)
    if not np.any(valid):
        return np.zeros(n_frames, dtype=np.float64)
    filled = np.interp(t_old, t_old[valid], f0[valid])
    t_new = np.linspace(0.0, 1.0, n_frames)
    return np.interp(t_new, t_old, filled)


def rms_level(y: np.ndarray) -> float:
    y = _mono(y).astype(np.float64)
    if y.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(y * y)))


def measure_features(y: np.ndarray, sr: int) -> np.ndarray:
    contour = pitch_contour(y, sr)
    logc = np.log(np.maximum(contour, 30.0))
    shape = logc - np.mean(logc)
    sn = np.linalg.norm(shape)
    if sn > 1e-8:
        shape = shape / sn
    return np.concatenate([[np.mean(logc)], shape, chroma_mean(y, sr)])


def feature_matrix(slices: list[np.ndarray], sr: int) -> np.ndarray:
    if not slices:
        return np.zeros((0, 0), dtype=np.float64)
    rows = [measure_features(chunk, sr) for chunk in slices]
    return np.vstack(rows)


def cosine_similarity_matrix(features: np.ndarray) -> np.ndarray:
    n = features.shape[0]
    if n == 0:
        return np.zeros((0, 0), dtype=np.float64)
    norms = np.linalg.norm(features, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    unit = features / norms
    sim = unit @ unit.T
    np.fill_diagonal(sim, 1.0)
    return np.clip(sim, -1.0, 1.0)


def _mean_pitch_similarity(means: np.ndarray, sigma: float = 0.08) -> np.ndarray:
    delta = means[:, None] - means[None, :]
    return np.exp(-(delta * delta) / (2.0 * sigma * sigma))


def slice_similarity_matrix(
    slices: list[np.ndarray],
    sr: int,
    chroma_weight: float = 0.3,
) -> np.ndarray:
    """Match bars by bass pitch mean + riff shape, with chroma as a backup."""
    n = len(slices)
    if n == 0:
        return np.zeros((0, 0), dtype=np.float64)

    contours = np.vstack([pitch_contour(chunk, sr) for chunk in slices])
    logc = np.log(np.maximum(contours, 30.0))
    means = np.mean(logc, axis=1)
    shapes = logc - means[:, None]
    shape_norm = np.linalg.norm(shapes, axis=1)
    flat = shape_norm < 1e-8
    unit_shape = np.zeros_like(shapes)
    unit_shape[~flat] = shapes[~flat] / shape_norm[~flat, None]
    contour_sim = unit_shape @ unit_shape.T
    contour_sim[flat[:, None] & flat[None, :]] = 1.0
    contour_sim = np.clip(contour_sim, 0.0, 1.0)
    np.fill_diagonal(contour_sim, 1.0)

    chroma = np.vstack([chroma_mean(chunk, sr) for chunk in slices])
    chroma_sim = cosine_similarity_matrix(chroma)
    mean_sim = _mean_pitch_similarity(means)

    cw = float(np.clip(chroma_weight, 0.0, 1.0))
    remaining = 1.0 - cw
    sim = 0.55 * remaining * mean_sim + 0.45 * remaining * contour_sim + cw * chroma_sim

    silent = np.array([rms_level(chunk) < 1e-4 for chunk in slices])
    if np.any(silent):
        sim[silent, :] = 0.0
        sim[:, silent] = 0.0
        np.fill_diagonal(sim, 1.0)
    return np.clip(sim, 0.0, 1.0)


def group_matches(sim: np.ndarray, threshold: float = 0.85) -> list[list[int]]:
    n = sim.shape[0]
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if sim[i, j] >= threshold:
                union(i, j)

    buckets: dict[int, list[int]] = {}
    for i in range(n):
        buckets.setdefault(find(i), []).append(i)
    groups = [sorted(g) for g in buckets.values() if len(g) >= 2]
    groups.sort(key=lambda g: g[0])
    return groups
