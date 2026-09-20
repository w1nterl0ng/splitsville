from __future__ import annotations

import io
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st

from splitsville.pipeline import run_pipeline
from splitsville.score import render_score, sniff_mime
from splitsville.split import load_audio
from splitsville.synth import make_demo
from splitsville.waveform import peak_envelope

FIRE_CLICK = Path(
    "/Users/fredanderson/Music/Logic/fire-test-05/Bounces/"
    "fire-test-05-bass-di-gain-click-measures.mp3"
)
FIRE_STEM = Path(
    "/Users/fredanderson/Music/Logic/fire-test-05/Bounces/"
    "fire-test-05-bass-di-gain.mp3"
)

MAX_EMBED_AUDIO = 15_000_000


st.set_page_config(page_title="Splitsville POC", layout="wide")
st.title("Splitsville")
st.caption(
    "Load a measure click track, mark bars with transient detection, "
    "split a stem at those markers, then group matching measures."
)

with st.sidebar:
    st.header("Detection")
    min_interval = st.slider("Min measure length (s)", 0.3, 3.0, 0.6, 0.05)
    click_threshold = st.slider("Click threshold", 0.05, 0.8, 0.25, 0.01)
    match_threshold = st.slider("Match threshold", 0.50, 0.99, 0.85, 0.01)
    use_demo = st.button("Load synthetic demo", use_container_width=True)
    use_fire = st.button("Load fire-test-05 bass", use_container_width=True)


def _wav_bytes(audio: np.ndarray, sr: int) -> bytes:
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV")
    return buf.getvalue()


@st.cache_data(show_spinner="Detecting bars and matching…")
def analyze(
    click_bytes: bytes,
    stem_bytes: bytes,
    min_interval: float,
    click_threshold: float,
    match_threshold: float,
):
    result = run_pipeline(
        io.BytesIO(click_bytes),
        io.BytesIO(stem_bytes),
        min_interval=min_interval,
        click_threshold=click_threshold,
        match_threshold=match_threshold,
    )
    return {
        "click_times": result.click_times,
        "measures": result.measures,
        "groups": result.groups,
        "similarity": result.similarity,
        "stem_sr": result.stem_sr,
        "click_sr": result.click_sr,
    }


@st.cache_data(show_spinner=False)
def cached_load(audio_bytes: bytes):
    return load_audio(io.BytesIO(audio_bytes))


@st.cache_data(show_spinner=False)
def cached_peaks(audio_bytes: bytes):
    audio, sr = load_audio(io.BytesIO(audio_bytes))
    return peak_envelope(audio, sr)


col_click, col_stem = st.columns(2)
with col_click:
    click_file = st.file_uploader("Click track (WAV/FLAC/MP3)", type=["wav", "flac", "mp3"])
with col_stem:
    stem_file = st.file_uploader("Stem (WAV/FLAC/MP3)", type=["wav", "flac", "mp3"])

if use_demo:
    click, stem, sr, sequence = make_demo()
    wav = _wav_bytes(stem, sr)
    st.session_state["click_bytes"] = _wav_bytes(click, sr)
    st.session_state["stem_bytes"] = wav
    st.session_state["stem_play_bytes"] = wav
    st.session_state["demo_sequence"] = sequence
    st.success(f"Demo loaded: bars {''.join(sequence)} at {sr} Hz")

if use_fire:
    if not FIRE_CLICK.exists() or not FIRE_STEM.exists():
        st.error("fire-test-05 bounce files were not found.")
    else:
        with st.spinner("Decoding fire-test-05 MP3s…"):
            click, csr = load_audio(FIRE_CLICK)
            stem, ssr = load_audio(FIRE_STEM)
            st.session_state["click_bytes"] = _wav_bytes(click, csr)
            st.session_state["stem_bytes"] = _wav_bytes(stem, ssr)
            st.session_state["stem_play_bytes"] = FIRE_STEM.read_bytes()
        st.success(
            f"fire-test-05 loaded ({click.shape[0] / csr:.1f}s clicks, "
            f"{stem.shape[0] / ssr:.1f}s bass)"
        )

if click_file is not None:
    st.session_state["click_bytes"] = click_file.getvalue()
if stem_file is not None:
    raw = stem_file.getvalue()
    st.session_state["stem_bytes"] = raw
    st.session_state["stem_play_bytes"] = raw

click_bytes = st.session_state.get("click_bytes")
stem_bytes = st.session_state.get("stem_bytes")
play_bytes = st.session_state.get("stem_play_bytes", stem_bytes)

if click_bytes and stem_bytes:
    analysis = analyze(
        click_bytes,
        stem_bytes,
        min_interval,
        click_threshold,
        match_threshold,
    )
    measures = analysis["measures"]
    groups = analysis["groups"]
    click_times = analysis["click_times"]

    stem, stem_sr = cached_load(stem_bytes)
    click, click_sr = cached_load(click_bytes)

    st.subheader("Score")
    st.caption(
        "Each cell is a measure. Matching groups share a color. "
        "Click a cell to play that bar and continue from there. "
        "The waveform shows the playing window (stop-after N bars, or 4 if you chose 0)."
    )
    if play_bytes and len(play_bytes) <= MAX_EMBED_AUDIO:
        render_score(
            audio_bytes=play_bytes,
            measures=measures,
            groups=groups,
            mime=sniff_mime(play_bytes),
            default_width=8 if len(measures) <= 8 else 16,
            click_peaks=cached_peaks(click_bytes),
            stem_peaks=cached_peaks(stem_bytes),
        )
    else:
        st.warning("Stem is too large to embed in the score player. Use the audio control below.")

    st.subheader("Measure markers")
    st.write(
        f"{len(click_times)} clicks → {len(measures)} measures. "
        f"Times (s): {', '.join(f'{t:.3f}' for t in click_times[:24])}"
        + (" …" if len(click_times) > 24 else "")
    )

    fig, axes = plt.subplots(2, 1, figsize=(12, 4), sharex=True)
    click_mono = click.mean(axis=1)
    t_click = np.arange(click_mono.size) / click_sr
    axes[0].plot(t_click, click_mono, color="#444", linewidth=0.6)
    for t in click_times:
        axes[0].axvline(t, color="#d62728", alpha=0.7, linewidth=1)
    axes[0].set_ylabel("Clicks")
    axes[0].set_yticks([])

    stem_mono = stem.mean(axis=1)
    t_stem = np.arange(stem_mono.size) / stem_sr
    axes[1].plot(t_stem, stem_mono, color="#1f77b4", linewidth=0.6)
    palette = plt.cm.tab10.colors
    group_of = {}
    for gi, group in enumerate(groups):
        for idx in group:
            group_of[idx] = gi
    for i, start, end in measures:
        color = palette[group_of[i] % 10] if i in group_of else (0.7, 0.7, 0.7)
        axes[1].axvspan(start, end, color=color, alpha=0.25)
        axes[1].axvline(start, color="#333", linewidth=0.6, alpha=0.8)
    axes[1].set_ylabel("Stem")
    axes[1].set_xlabel("Time (s)")
    axes[1].set_yticks([])
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    left, right = st.columns((1, 1))
    with left:
        st.subheader("Matching groups")
        if groups:
            for gi, group in enumerate(groups, start=1):
                labels = ", ".join(f"bar {i + 1}" for i in group)
                st.write(f"**Group {gi}:** {labels}")
        else:
            st.info("No pairs above the match threshold. Lower it in the sidebar.")

        similarity = analysis["similarity"]
        if similarity.size:
            fig2, ax2 = plt.subplots(figsize=(5, 4))
            im = ax2.imshow(similarity, origin="upper", vmin=0, vmax=1, cmap="magma")
            ax2.set_title("Measure similarity")
            ax2.set_xlabel("Bar")
            ax2.set_ylabel("Bar")
            fig2.colorbar(im, ax=ax2, fraction=0.046)
            st.pyplot(fig2)
            plt.close(fig2)

    with right:
        st.subheader("Full stem")
        st.audio(play_bytes)
else:
    st.info("Upload a click track and a stem, or load the synthetic demo from the sidebar.")
