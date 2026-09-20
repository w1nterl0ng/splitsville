"""Downsampled min/max envelopes for the live waveform view."""

from __future__ import annotations

import numpy as np


def peak_envelope(audio: np.ndarray, sr: int, peaks_per_sec: float = 100.0) -> dict:
    if audio.ndim == 1:
        audio = audio[:, None]
    hop = max(1, int(round(sr / peaks_per_sec)))
    n = max(1, audio.shape[0] // hop)
    trimmed = audio[: n * hop]
    channels = []
    count = min(2, trimmed.shape[1])
    for c in range(count):
        blocks = trimmed[:, c].reshape(n, hop)
        mx = np.clip(blocks.max(axis=1) * 127.0, -127, 127).astype(np.int16)
        mn = np.clip(blocks.min(axis=1) * 127.0, -127, 127).astype(np.int16)
        channels.append({"min": mn.tolist(), "max": mx.tolist()})
    if len(channels) == 1:
        channels.append(channels[0])
    return {
        "sr": int(sr),
        "hop": int(hop),
        "n": int(n),
        "ch": channels,
    }
