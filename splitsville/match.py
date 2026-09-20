"""Classical DSP features and measure-to-measure matching."""

from __future__ import annotations

import numpy as np
from scipy.signal import stft

# Bump this when matcher behavior changes so Streamlit's analyze cache invalidates.
MATCHER_VERSION = 2

BAND_PRESETS = {
    "bass": (40.0, 400.0),
    "guitar": (80.0, 2500.0),
}


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


def spectral_median_hz(y: np.ndarray, sr: int) -> float:
    """Frequency at 50% of mean spectral energy (first ~40s)."""
    y = _mono(y)
    n = min(y.size, int(sr * 40))
    freqs, mag = _stft_mag(y[:n], sr, n_fft=4096, hop=1024)
    energy = np.mean(mag, axis=1) + 1e-12
    cdf = np.cumsum(energy)
    cdf /= cdf[-1]
    return float(freqs[min(int(np.searchsorted(cdf, 0.5)), freqs.size - 1)])


def detect_band(y: np.ndarray, sr: int) -> tuple[str, float, float]:
    """Guess bass vs guitar from where the spectrum's energy sits."""
    median = spectral_median_hz(y, sr)
    name = "bass" if median < 280.0 else "guitar"
    fmin, fmax = BAND_PRESETS[name]
    return name, fmin, fmax


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


def amplitude_shape(y: np.ndarray, n_bins: int = 48) -> np.ndarray:
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


def bass_logspec(
    y: np.ndarray,
    sr: int,
    n_time: int = 32,
    n_bins: int = 48,
    n_fft: int = 8192,
    hop: int = 512,
    fmin: float = 40.0,
    fmax: float = 400.0,
) -> np.ndarray:
    """Time-normalized log-frequency spectrogram in an instrument band."""
    freqs, mag = _stft_mag(y, sr, n_fft, hop)
    fmax = min(fmax, sr / 2.0 - 1.0)
    mask = (freqs >= fmin) & (freqs <= fmax)
    if not np.any(mask):
        return np.zeros(n_time * n_bins, dtype=np.float64)
    mag = mag[mask]
    freqs = freqs[mask]
    edges = np.geomspace(fmin, fmax, n_bins + 1)
    bands = np.zeros((n_bins, mag.shape[1]), dtype=np.float64)
    for i in range(n_bins):
        band = (freqs >= edges[i]) & (freqs < edges[i + 1])
        if np.any(band):
            bands[i] = mag[band].mean(axis=0)
    t_old = np.linspace(0.0, 1.0, max(bands.shape[1], 1))
    t_new = np.linspace(0.0, 1.0, n_time)
    out = np.vstack([np.interp(t_new, t_old, row) for row in bands])
    out = np.log1p(out * 1000.0)
    out -= out.mean(axis=0, keepdims=True)
    norm = np.linalg.norm(out)
    if norm > 1e-12:
        out = out / norm
    return out.ravel()


def rms_level(y: np.ndarray) -> float:
    y = _mono(y).astype(np.float64)
    if y.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(y * y)))


def measure_features(
    y: np.ndarray,
    sr: int,
    fmin: float = 40.0,
    fmax: float = 400.0,
) -> np.ndarray:
    return np.concatenate([bass_logspec(y, sr, fmin=fmin, fmax=fmax), amplitude_shape(y)])


def feature_matrix(
    slices: list[np.ndarray],
    sr: int,
    fmin: float = 40.0,
    fmax: float = 400.0,
) -> np.ndarray:
    if not slices:
        return np.zeros((0, 0), dtype=np.float64)
    rows = [measure_features(chunk, sr, fmin=fmin, fmax=fmax) for chunk in slices]
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


def slice_similarity_matrix(
    slices: list[np.ndarray],
    sr: int,
    envelope_weight: float = 0.3,
    min_duration_ratio: float = 0.85,
    chroma_weight: float | None = None,
    fmin: float = 40.0,
    fmax: float = 400.0,
) -> np.ndarray:
    """Match bars by spectrogram shape in an instrument band, plus envelope."""
    n = len(slices)
    if n == 0:
        return np.zeros((0, 0), dtype=np.float64)
    if chroma_weight is not None:
        envelope_weight = float(chroma_weight)

    specs = np.vstack([bass_logspec(chunk, sr, fmin=fmin, fmax=fmax) for chunk in slices])
    spec_sim = np.clip(specs @ specs.T, 0.0, 1.0)
    np.fill_diagonal(spec_sim, 1.0)

    amps = np.vstack([amplitude_shape(chunk) for chunk in slices])
    amp_sim = cosine_similarity_matrix(amps)

    ew = float(np.clip(envelope_weight, 0.0, 1.0))
    sim = (1.0 - ew) * spec_sim + ew * amp_sim

    durs = np.array([chunk.shape[0] / float(sr) for chunk in slices], dtype=np.float64)
    longest = np.maximum(durs[:, None], durs[None, :])
    shortest = np.minimum(durs[:, None], durs[None, :])
    ratio = np.divide(shortest, longest, out=np.ones((n, n)), where=longest > 1e-9)
    sim = np.where(ratio >= min_duration_ratio, sim, 0.0)

    silent = np.array([rms_level(chunk) < 1e-4 for chunk in slices])
    if np.any(silent):
        sim[silent, :] = 0.0
        sim[:, silent] = 0.0
    np.fill_diagonal(sim, 1.0)
    return np.clip(sim, 0.0, 1.0)


def split_equal(y: np.ndarray, n: int) -> list[np.ndarray]:
    count = max(1, int(n))
    length = int(y.shape[0])
    parts: list[np.ndarray] = []
    for k in range(count):
        start = int(round(k * length / count))
        stop = int(round((k + 1) * length / count))
        if stop <= start:
            stop = min(length, start + 1)
        parts.append(y[start:stop])
    return parts


def chunk_similarity(
    a: np.ndarray,
    b: np.ndarray,
    sr: int,
    fmin: float = 40.0,
    fmax: float = 400.0,
) -> float:
    """Same-music rating for one beat in the active instrument band."""
    if a.size == 0 or b.size == 0:
        return 0.0
    va = bass_logspec(a, sr, n_time=8, n_bins=24, n_fft=2048, hop=256, fmin=fmin, fmax=fmax)
    vb = bass_logspec(b, sr, n_time=8, n_bins=24, n_fft=2048, hop=256, fmin=fmin, fmax=fmax)
    return float(np.clip(va @ vb, 0.0, 1.0))


def group_subdiv_ratings(
    slices: list[np.ndarray],
    sr: int,
    groups: list[list[int]],
    subdivs: list[int],
    fmin: float = 40.0,
    fmax: float = 400.0,
) -> dict[int, list[float]]:
    """Per-beat confidence of each grouped bar against the first bar in its group."""
    ratings: dict[int, list[float]] = {}
    for group in groups:
        if not group:
            continue
        truth = group[0]
        n = max(1, subdivs[truth] if truth < len(subdivs) else 4)
        truth_parts = split_equal(slices[truth], n)
        ratings[truth] = [1.0] * n
        for idx in group[1:]:
            parts = split_equal(slices[idx], n)
            ratings[idx] = [
                chunk_similarity(t_part, o_part, sr, fmin=fmin, fmax=fmax)
                for t_part, o_part in zip(truth_parts, parts)
            ]
    return ratings


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
