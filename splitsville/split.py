"""Slice a stem at measure markers."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

_FFMPEG_EXTS = {".mp3", ".m4a", ".aac", ".mp4", ".mov", ".wma"}


def load_audio(source) -> tuple[np.ndarray, int]:
    """Load audio as float32 array shaped (n_samples, n_channels)."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.suffix.lower() in _FFMPEG_EXTS:
            return _ffmpeg_decode(path=path)
        try:
            data, sr = sf.read(str(path), always_2d=True, dtype="float32")
            return data, int(sr)
        except Exception:
            return _ffmpeg_decode(path=path)

    raw = source.read() if hasattr(source, "read") else bytes(source)
    try:
        data, sr = sf.read(io.BytesIO(raw), always_2d=True, dtype="float32")
        return data, int(sr)
    except Exception:
        return _ffmpeg_decode(raw=raw)


def _ffmpeg_decode(*, path: Path | None = None, raw: bytes | None = None) -> tuple[np.ndarray, int]:
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path) if path is not None else "pipe:0",
        "-f",
        "wav",
        "pipe:1",
    ]
    proc = subprocess.run(
        cmd,
        input=None if path is not None else raw,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(err or "ffmpeg failed to decode audio")
    data, sr = sf.read(io.BytesIO(proc.stdout), always_2d=True, dtype="float32")
    return data, int(sr)


def slice_stem(
    stem: np.ndarray,
    sr: int,
    measures: list[tuple[int, float, float]],
) -> list[np.ndarray]:
    n = stem.shape[0]
    slices: list[np.ndarray] = []
    for _, start, end in measures:
        a = max(0, min(n, int(round(start * sr))))
        b = max(a, min(n, int(round(end * sr))))
        slices.append(stem[a:b].copy())
    return slices


def write_slices(
    slices: list[np.ndarray],
    sr: int,
    out_dir: Path,
    prefix: str = "measure",
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, audio in enumerate(slices):
        path = out_dir / f"{prefix}_{i:03d}.wav"
        sf.write(path, audio, sr)
        paths.append(path)
    return paths
