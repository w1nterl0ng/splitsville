from __future__ import annotations

import io
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st

from splitsville.pipeline import run_pipeline
from splitsville.project import (
    apply_lock_map,
    load_any,
    measure_meta_list,
    meta_by_index,
    new_document,
    pack_zip,
)
from splitsville.score import render_score, sniff_mime
from splitsville.split import load_audio
from splitsville.waveform import peak_envelope
from splitsville.xsc import looks_like_xsc, parse_xsc

MAX_EMBED_AUDIO = 15_000_000
MATCHER_VERSION = 6


st.set_page_config(page_title="Splitsville", layout="wide")
if "pending_project_name" in st.session_state:
    st.session_state["project_name"] = st.session_state.pop("pending_project_name")
st.title("Splitsville")
st.caption(
    "Open a saved session, or load Transcribe markers plus a stem. "
    "Matching groups live in the score; mark a bar done when it is finished in Guitar Pro."
)

with st.sidebar:
    st.header("Session")
    project_name = st.text_input("Name", value="Untitled", key="project_name")
    project_file = st.file_uploader(
        "Open session",
        type=["splitsville", "zip", "json"],
        help="A .splitsville zip is self-contained (markers + stem + metadata).",
    )
    st.header("Detection")
    min_interval = st.slider("Min measure length (s)", 0.3, 3.0, 0.6, 0.05)
    click_threshold = st.slider("Click threshold", 0.05, 0.8, 0.25, 0.01)
    match_threshold = st.slider("Match threshold", 0.50, 0.99, 0.85, 0.01)
    instrument = st.segmented_control(
        "Instrument band",
        options=["Auto", "Bass", "Guitar"],
        default="Auto",
        required=True,
        help="Auto guesses from the stem spectrum. Override if the guess is wrong.",
    )


def _wav_bytes(audio: np.ndarray, sr: int) -> bytes:
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV")
    return buf.getvalue()


def _settings() -> dict:
    return {
        "min_interval": float(min_interval),
        "click_threshold": float(click_threshold),
        "match_threshold": float(match_threshold),
        "instrument": (instrument or "Auto").lower(),
        "matcher_version": MATCHER_VERSION,
    }


@st.cache_data(show_spinner="Detecting bars and matching…")
def analyze(
    click_bytes: bytes,
    stem_bytes: bytes,
    min_interval: float,
    click_threshold: float,
    match_threshold: float,
    matcher_version: int = MATCHER_VERSION,
    instrument: str = "auto",
):
    result = run_pipeline(
        io.BytesIO(click_bytes),
        io.BytesIO(stem_bytes),
        min_interval=min_interval,
        click_threshold=click_threshold,
        match_threshold=match_threshold,
        instrument=instrument,
    )
    return {
        "click_times": result.click_times,
        "measures": result.measures,
        "groups": result.groups,
        "similarity": result.similarity,
        "stem_sr": result.stem_sr,
        "click_sr": result.click_sr,
        "labels": result.labels,
        "beat_times": result.beat_times,
        "marker_source": result.marker_source,
        "click_peaks": peak_envelope(result.click, result.click_sr),
        "sound_path": result.sound_path,
        "matcher_version": matcher_version,
        "subdivs": result.subdivs,
        "subdiv_ratings": {str(k): v for k, v in result.subdiv_ratings.items()},
        "band_name": result.band_name,
        "fmin": result.fmin,
        "fmax": result.fmax,
    }


@st.cache_data(show_spinner=False)
def cached_load(audio_bytes: bytes):
    return load_audio(io.BytesIO(audio_bytes))


@st.cache_data(show_spinner=False)
def cached_peaks(audio_bytes: bytes):
    audio, sr = load_audio(io.BytesIO(audio_bytes))
    return peak_envelope(audio, sr)


def _restore_analysis(blob: dict) -> dict:
    out = dict(blob)
    if "similarity" in out:
        out["similarity"] = np.asarray(out["similarity"])
    if "click_times" in out:
        out["click_times"] = np.asarray(out["click_times"], dtype=float)
    if "measures" in out:
        out["measures"] = [tuple(m) for m in out["measures"]]
    ratings = out.get("subdiv_ratings") or {}
    out["subdiv_ratings"] = {str(k): v for k, v in ratings.items()}
    return out


def _load_stem_path(path: Path) -> None:
    audio, sr = load_audio(path)
    st.session_state["stem_bytes"] = _wav_bytes(audio, sr)
    st.session_state["stem_play_bytes"] = Path(path).read_bytes()
    st.session_state["stem_source_name"] = path.name


def _open_project(raw: bytes, filename: str) -> None:
    doc, markers, stem = load_any(raw)
    st.session_state["project_doc"] = doc
    st.session_state["pending_project_name"] = doc.get("name") or Path(filename).stem
    if markers:
        st.session_state["click_bytes"] = markers
        st.session_state["markers_name"] = (doc.get("sources") or {}).get("markers_name") or "markers"
    if stem:
        st.session_state["stem_bytes"] = stem
        st.session_state["stem_play_bytes"] = stem
        st.session_state["stem_source_name"] = (doc.get("sources") or {}).get("stem_name") or "stem"
    if doc.get("measures"):
        st.session_state["measure_rows"] = list(doc["measures"])
    saved = doc.get("analysis") or {}
    saved_settings = doc.get("settings") or {}
    if saved.get("measures") and saved_settings.get("matcher_version") == MATCHER_VERSION:
        st.session_state["saved_analysis"] = saved
        st.session_state["saved_settings"] = saved_settings
    else:
        st.session_state.pop("saved_analysis", None)
        st.session_state.pop("saved_settings", None)
    st.session_state.pop("score_player", None)


if project_file is not None:
    digest = (project_file.name, project_file.size)
    if st.session_state.get("project_digest") != digest:
        try:
            _open_project(project_file.getvalue(), project_file.name)
            st.session_state["project_digest"] = digest
            st.rerun()
        except Exception as exc:
            st.error(f"Could not open session ({exc}).")

col_click, col_stem = st.columns(2)
with col_click:
    click_file = st.file_uploader(
        "Markers or click track (XSC / WAV / FLAC / MP3)",
        type=["xsc", "wav", "flac", "mp3"],
        key="markers_upload",
    )
with col_stem:
    stem_file = st.file_uploader("Stem (WAV/FLAC/MP3)", type=["wav", "flac", "mp3"], key="stem_upload")


if click_file is not None:
    st.session_state["click_bytes"] = click_file.getvalue()
    st.session_state["markers_name"] = click_file.name
    if looks_like_xsc(st.session_state["click_bytes"]) and stem_file is None and "stem_bytes" not in st.session_state:
        doc = parse_xsc(st.session_state["click_bytes"])
        if doc.sound_path is not None and doc.sound_path.exists():
            _load_stem_path(doc.sound_path)
            st.caption(f"Stem from XSC: `{doc.sound_path}`")
if stem_file is not None:
    raw = stem_file.getvalue()
    st.session_state["stem_bytes"] = raw
    st.session_state["stem_play_bytes"] = raw
    st.session_state["stem_source_name"] = stem_file.name

click_bytes = st.session_state.get("click_bytes")
stem_bytes = st.session_state.get("stem_bytes")
play_bytes = st.session_state.get("stem_play_bytes", stem_bytes)

if click_bytes and stem_bytes:
    settings = _settings()
    saved_analysis = st.session_state.get("saved_analysis")
    saved_settings = st.session_state.get("saved_settings")
    if saved_analysis and saved_settings == settings:
        analysis = _restore_analysis(saved_analysis)
    else:
        analysis = analyze(
            click_bytes,
            stem_bytes,
            min_interval,
            click_threshold,
            match_threshold,
            MATCHER_VERSION,
            settings["instrument"],
        )
        st.session_state.pop("saved_analysis", None)

    measures = analysis["measures"]
    groups = analysis["groups"]
    click_times = analysis["click_times"]
    bar_labels = analysis.get("labels") or []

    n = len(measures)
    rows = st.session_state.get("measure_rows")
    if not isinstance(rows, list) or len(rows) != n:
        rows = measure_meta_list(n, bar_labels)
        st.session_state["measure_rows"] = rows
    prev = st.session_state.get("score_player")
    if isinstance(prev, dict) and prev.get("measure_meta"):
        rows = apply_lock_map(rows, prev["measure_meta"])
        st.session_state["measure_rows"] = rows

    stem, stem_sr = cached_load(stem_bytes)
    if looks_like_xsc(click_bytes):
        click = None
        click_sr = analysis["click_sr"]
        click_peaks = analysis["click_peaks"]
    else:
        click, click_sr = cached_load(click_bytes)
        click_peaks = cached_peaks(click_bytes)

    done_n = sum(1 for r in rows if r.get("locked"))
    st.subheader("Score")
    st.caption(
        "Each cell is a measure. Matching groups share a color. "
        "Click a cell to play. Mark **done** on the right when that bar is finished in Guitar Pro. "
        f"{done_n}/{n} done."
    )
    if play_bytes and len(play_bytes) <= MAX_EMBED_AUDIO:
        render_score(
            audio_bytes=play_bytes,
            measures=measures,
            groups=groups,
            mime=sniff_mime(play_bytes),
            default_width=8 if n <= 8 else 16,
            click_peaks=click_peaks,
            stem_peaks=cached_peaks(stem_bytes),
            labels=bar_labels,
            beats=analysis.get("beat_times") or [],
            subdivs=analysis.get("subdivs") or [],
            subdiv_ratings={
                int(k): v for k, v in (analysis.get("subdiv_ratings") or {}).items()
            },
            measure_meta=meta_by_index(rows),
            key="score_player",
        )
    else:
        st.warning("Stem is too large to embed in the score player. Use the audio control below.")

    zip_doc = new_document(
        name=st.session_state.get("project_name") or project_name or "Untitled",
        settings=settings,
        sources={
            "markers_path": analysis.get("sound_path"),
        },
        analysis=analysis,
        measures=st.session_state["measure_rows"],
    )
    zip_doc["project_meta"] = (st.session_state.get("project_doc") or {}).get("project_meta") or {}
    zip_bytes = pack_zip(
        zip_doc,
        markers=click_bytes,
        stem=play_bytes or stem_bytes,
        markers_name=st.session_state.get("markers_name") or "markers",
        stem_name=st.session_state.get("stem_source_name") or "stem",
    )
    safe_name = "".join(
        ch if ch.isalnum() or ch in "-_." else "-"
        for ch in (st.session_state.get("project_name") or "splitsville")
    )
    st.download_button(
        "Save session",
        data=zip_bytes,
        file_name=f"{safe_name}.splitsville",
        mime="application/zip",
        width="stretch",
        help="Zip of markers, stem, matching, and per-measure metadata (done/locked, notes, tags, extra).",
    )

    st.subheader("Measure markers")
    beat_times = analysis.get("beat_times") or []
    st.write(
        f"{len(click_times)} {analysis.get('marker_source', 'audio')} markers → "
        f"{len(measures)} measures, {len(beat_times)} interior beats. "
        f"Times (s): {', '.join(f'{t:.3f}' for t in click_times[:24])}"
        + (" …" if len(click_times) > 24 else "")
    )
    if analysis.get("sound_path"):
        st.caption(f"XSC SoundFileName: `{analysis['sound_path']}`")
    st.caption(
        f"Instrument band: {analysis.get('band_name', 'bass')} "
        f"({analysis.get('fmin', 40):.0f}–{analysis.get('fmax', 400):.0f} Hz)"
    )

    fig, axes = plt.subplots(2, 1, figsize=(12, 4), sharex=True)
    if click is not None:
        click_mono = click.mean(axis=1)
        t_click = np.arange(click_mono.size) / click_sr
        axes[0].plot(t_click, click_mono, color="#444", linewidth=0.6)
    for t in click_times:
        axes[0].axvline(t, color="#d62728", alpha=0.7, linewidth=1)
    for t in beat_times:
        axes[0].axvline(t, color="#c62828", alpha=0.35, linewidth=0.6)
        axes[1].axvline(t, color="#c62828", alpha=0.25, linewidth=0.5)
    axes[0].set_ylabel("Markers")
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
                names = [bar_labels[i] if i < len(bar_labels) else f"bar {i + 1}" for i in group]
                st.write(f"**Group {gi}:** {', '.join(names)}")
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
    st.info(
        "Open a `.splitsville` session from the sidebar, or upload a Transcribe .xsc "
        "(stem path is read from SoundFileName) / a click track plus stem, then save."
    )
