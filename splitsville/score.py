"""Interactive score-grid player: click a bar, play from there onward."""

from __future__ import annotations

import base64
from collections.abc import Callable
from pathlib import Path

import streamlit as st

GROUP_COLORS = [
    "#3b82f6",
    "#f59e0b",
    "#10b981",
    "#ef4444",
    "#a855f7",
    "#14b8a6",
    "#f97316",
    "#6366f1",
    "#84cc16",
    "#ec4899",
]


def sniff_mime(data: bytes) -> str:
    if data.startswith(b"RIFF"):
        return "audio/wav"
    if data.startswith(b"fLaC"):
        return "audio/flac"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    return "audio/mpeg"


_CSS = r"""
  :host, .sv-root { color: var(--st-text-color, #fafafa); font-family: "Source Sans Pro", ui-sans-serif, system-ui, sans-serif; }
  .sv-root { margin: 0; outline: none; }
  kbd {
    font: 11px ui-monospace, SFMono-Regular, Menlo, monospace;
    border: 1px solid #555;
    border-bottom-width: 2px;
    border-radius: 4px;
    padding: 0 4px;
    background: #1b1b21;
  }
  .toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
    margin-bottom: 8px;
    font-size: 13px;
  }
  .toolbar label { opacity: 0.85; }
  select, button {
    background: #262730;
    color: #fafafa;
    border: 1px solid #3d3d4a;
    border-radius: 6px;
    padding: 4px 8px;
  }
  button { cursor: pointer; }
  button:hover { border-color: #888; }
  .status { opacity: 0.8; }
  .wave-wrap {
    width: 100%;
    height: 198px;
    margin: 0 0 10px 0;
    border-radius: 6px;
    overflow: hidden;
    box-shadow: inset 0 0 0 1px rgba(0,0,0,0.35);
  }
  #wave { width: 100%; height: 198px; display: block; cursor: crosshair; }
  .body {
    display: flex;
    gap: 12px;
    align-items: flex-start;
  }
  .score {
    display: grid;
    gap: 5px;
    flex: 1 1 76%;
    min-width: 0;
  }
  .matches {
    flex: 0 0 26%;
    min-width: 188px;
    max-width: 360px;
    max-height: 560px;
    overflow-y: auto;
    padding: 8px;
    border-radius: 8px;
    background: rgba(255,255,255,0.04);
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.08);
  }
  .matches h3 { margin: 0 0 4px 0; font-size: 13px; font-weight: 650; }
  .matches .hint { margin: 0 0 8px 0; font-size: 11px; opacity: 0.7; line-height: 1.3; }
  .mrow {
    margin: 0 0 7px 0;
    padding: 6px;
    border-radius: 6px;
    border: 2px solid transparent;
    background: rgba(0,0,0,0.18);
    cursor: pointer;
  }
  .mrow.listening {
    border-color: #f4f4f5;
    box-shadow: 0 0 0 1px rgba(255,255,255,0.35);
  }
  .mrow.locked { opacity: 0.55; filter: grayscale(0.35); }
  .mrow .mlabel {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    font-weight: 650;
    margin-bottom: 4px;
  }
  .mrow .mlabel-right { display: flex; align-items: center; gap: 6px; }
  .mrow .mlabel .truth { opacity: 0.65; font-weight: 500; font-size: 10px; }
  .lockbtn {
    font-size: 11px;
    font-weight: 650;
    padding: 2px 7px;
    border-radius: 999px;
    background: #14532d;
    border-color: #166534;
  }
  .mrow.locked .lockbtn { background: #3f3f46; border-color: #52525b; }
  .phrase { display: flex; gap: 5px; }
  .mcol { flex: 1; min-width: 0; }
  .beats { display: flex; gap: 3px; height: 16px; }
  .beat { flex: 1; border-radius: 3px; min-width: 0; }
  .cell {
    min-height: 42px;
    border: 0;
    border-radius: 6px;
    cursor: pointer;
    color: #0b0b0b;
    font-weight: 650;
    font-size: 12px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    line-height: 1.15;
    box-shadow: inset 0 0 0 1px rgba(0,0,0,0.25);
  }
  .cell.ungrouped { background: #4b4b55; color: #eee; }
  .cell.playing { outline: 2px solid #fff; outline-offset: 1px; filter: brightness(1.12); }
  .cell .g { font-size: 10px; font-weight: 500; opacity: 0.8; }
  .cell.locked {
    opacity: 0.5;
    filter: grayscale(0.45);
    box-shadow: inset 0 0 0 2px #d4d4d8;
  }
  .cell .done { font-size: 9px; font-weight: 700; letter-spacing: 0.04em; opacity: 0.85; }
"""

_HTML = r"""
<div class="sv-root" tabindex="0">
  <div class="toolbar">
    <label>Bars per row
      <select id="width">
        <option value="8">8</option>
        <option value="12">12</option>
        <option value="16">16</option>
      </select>
    </label>
    <label>Stop after
      <select id="stopAfter">
        <option value="0">0 — don’t stop</option>
        <option value="1">1</option>
        <option value="2">2</option>
        <option value="3">3</option>
        <option value="4">4</option>
        <option value="5">5</option>
        <option value="6">6</option>
        <option value="7">7</option>
        <option value="8">8</option>
        <option value="9">9</option>
      </select>
      measure(s)
    </label>
    <label>Speed
      <select id="speed">
        <option value="0.5">50%</option>
        <option value="0.75">75%</option>
        <option value="0.9">90%</option>
        <option value="1" selected>100%</option>
        <option value="1.2">120%</option>
      </select>
    </label>
    <button id="stop" type="button">Stop</button>
    <span class="status" id="status">Click a bar to play. Drag on the wave to loop. <kbd>Space</kbd> pause/resume. <kbd>Esc</kbd> clears the loop. Keys <kbd>0</kbd>–<kbd>9</kbd> set stop-after. Mark done when the bar is finished in Guitar Pro.</span>
  </div>
  <div class="wave-wrap"><canvas id="wave"></canvas></div>
  <div class="body">
    <div id="score" class="score"></div>
    <aside id="matches" class="matches"></aside>
  </div>
  <audio id="player" preload="auto"></audio>
</div>
"""

# Prefix so Streamlit's inline-JS hash changes when the player script does.
_JS = (
    "/* splitsville-score-js v4 */\n"
    + Path(__file__).with_name("score_player.js").read_text()
)

_SCORE = st.components.v2.component(
    "splitsville_score",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


def render_score(
    *,
    audio_bytes: bytes,
    measures: list[tuple[int, float, float]],
    groups: list[list[int]],
    mime: str | None = None,
    default_width: int = 16,
    click_peaks: dict | None = None,
    stem_peaks: dict | None = None,
    labels: list[str] | None = None,
    beats: list[float] | None = None,
    subdivs: list[int] | None = None,
    subdiv_ratings: dict[int, list[float]] | None = None,
    measure_meta: dict[str, dict] | None = None,
    key: str = "score_player",
    on_measure_meta_change: Callable[[], None] | None = None,
) -> object:
    if not measures or not audio_bytes:
        return None

    mime = mime or sniff_mime(audio_bytes)
    group_of = {}
    for gi, group in enumerate(groups):
        for idx in group:
            group_of[idx] = gi

    starts = [float(m[1]) for m in measures]
    ends = [float(m[2]) for m in measures]
    payload = {
        "n": len(measures),
        "starts": starts,
        "ends": ends,
        "end": float(measures[-1][2]),
        "groupOf": {str(k): v for k, v in group_of.items()},
        "colors": GROUP_COLORS,
        "defaultWidth": int(default_width),
        "clickPeaks": click_peaks,
        "stemPeaks": stem_peaks,
        "labels": list(labels or []),
        "beats": [float(t) for t in (beats or [])],
        "groups": [list(g) for g in groups],
        "subdivs": [int(n) for n in (subdivs or [])],
        "subdivConf": {
            str(idx): [float(v) for v in vals]
            for idx, vals in (subdiv_ratings or {}).items()
        },
    }
    meta = {str(k): dict(v) for k, v in (measure_meta or {}).items()}
    if on_measure_meta_change is None:
        on_measure_meta_change = lambda: None
    return _SCORE(
        data={
            "payload": payload,
            "mime": mime,
            "audio": base64.b64encode(audio_bytes).decode("ascii"),
            "measure_meta": meta,
        },
        key=key,
        default={"measure_meta": meta},
        on_measure_meta_change=on_measure_meta_change,
        width="stretch",
    )
