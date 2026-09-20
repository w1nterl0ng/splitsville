"""Interactive score-grid HTML player: click a bar, play from there onward."""

from __future__ import annotations

import base64
import json

import streamlit.components.v1 as components

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
) -> None:
    if not measures or not audio_bytes:
        return

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
    }
    b64 = base64.b64encode(audio_bytes).decode("ascii")
    html = _TEMPLATE.replace("__PAYLOAD__", json.dumps(payload)).replace("__MIME__", mime).replace(
        "__AUDIO__", b64
    )
    rows_guess = max(1, (len(measures) + default_width - 1) // default_width)
    height = min(920, 300 + rows_guess * 52)
    components.html(html, height=height, scrolling=True)


_TEMPLATE = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  :root { color-scheme: dark; }
  body {
    margin: 0;
    font-family: "Source Sans Pro", ui-sans-serif, system-ui, sans-serif;
    background: transparent;
    color: #fafafa;
    outline: none;
  }
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
  .score { display: grid; gap: 5px; }
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
  .cell.playing {
    outline: 2px solid #fff;
    outline-offset: 1px;
    filter: brightness(1.12);
  }
  .cell .g { font-size: 10px; font-weight: 500; opacity: 0.8; }
</style>
</head>
<body>
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
    <button id="stop" type="button">Stop</button>
    <span class="status" id="status">Click a bar to play. Drag on the wave to loop. <kbd>Space</kbd> pause/resume. <kbd>Esc</kbd> clears the loop. Keys <kbd>0</kbd>–<kbd>9</kbd> set stop-after.</span>
  </div>
  <div class="wave-wrap"><canvas id="wave"></canvas></div>
  <div id="score" class="score"></div>
  <audio id="player" preload="auto" src="data:__MIME__;base64,__AUDIO__"></audio>
  <script>
    const data = __PAYLOAD__;
    const score = document.getElementById("score");
    const player = document.getElementById("player");
    const widthSel = document.getElementById("width");
    const stopAfterSel = document.getElementById("stopAfter");
    const status = document.getElementById("status");
    function barLabel(i) {
      const labels = data.labels || [];
      return labels[i] || String(i + 1);
    }
    const canvas = document.getElementById("wave");
    const ctx = canvas.getContext("2d");
    widthSel.value = String(data.defaultWidth);
    document.body.tabIndex = 0;
    let playStart = 0;
    let viewOrigin = 0;
    let stopTime = null;
    let loop = null;
    let drag = null;
    const WAVE_PAD = 14;
    const HANDLE_PX = 8;
    const MIN_LOOP = 0.08;

    function stopAfterCount() {
      return Number(stopAfterSel.value) || 0;
    }

    function viewBarCount() {
      const n = stopAfterCount();
      return n > 0 ? n : 4;
    }

    function stopTimeFrom(startIndex) {
      const n = stopAfterCount();
      if (n <= 0) return null;
      const last = Math.min(startIndex + n, data.n) - 1;
      return data.ends[last];
    }

    function describePlay(startIndex) {
      const n = stopAfterCount();
      if (n <= 0) return `Playing from bar ${startIndex + 1} through the end.`;
      const last = Math.min(startIndex + n, data.n);
      if (n === 1) return `Playing bar ${startIndex + 1} only.`;
      return `Playing bars ${startIndex + 1}–${last}, then stop.`;
    }

    function currentBar() {
      const t = player.currentTime;
      let idx = -1;
      for (let i = 0; i < data.starts.length; i++) {
        if (t + 0.02 >= data.starts[i]) idx = i;
      }
      if (t >= data.end) return -1;
      return idx;
    }

    function viewWindow() {
      const viewN = viewBarCount();
      const n = stopAfterCount();
      let startIdx = n > 0 ? playStart : viewOrigin;
      if (n <= 0 && !player.paused) {
        const cur = currentBar();
        if (cur >= startIdx + viewN) viewOrigin = cur;
        startIdx = viewOrigin;
      }
      startIdx = Math.max(0, Math.min(startIdx, Math.max(0, data.n - 1)));
      const endIdx = Math.min(startIdx + viewN, data.n);
      return {
        startIdx,
        endIdx,
        t0: data.starts[startIdx],
        t1: data.ends[endIdx - 1],
      };
    }

    function timeToPeak(peaks, t) {
      if (!peaks) return 0;
      const i = Math.floor((t * peaks.sr) / peaks.hop);
      return Math.max(0, Math.min(peaks.n - 1, i));
    }

    function drawLane(mn, mx, i0, i1, x, y, w, h, color) {
      const mid = y + h / 2;
      const amp = h * 0.46;
      const span = Math.max(1, i1 - i0);
      ctx.beginPath();
      for (let px = 0; px < w; px++) {
        const i = i0 + Math.floor(px * span / w);
        const v = (mx[i] / 127) * amp;
        if (px === 0) ctx.moveTo(x + px, mid - v);
        else ctx.lineTo(x + px, mid - v);
      }
      for (let px = w - 1; px >= 0; px--) {
        const i = i0 + Math.floor(px * span / w);
        const v = (mn[i] / 127) * amp;
        ctx.lineTo(x + px, mid - v);
      }
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = "rgba(40,28,8,0.35)";
      ctx.beginPath();
      ctx.moveTo(x, mid);
      ctx.lineTo(x + w, mid);
      ctx.stroke();
    }

    function sizeCanvas() {
      const dpr = window.devicePixelRatio || 1;
      const w = Math.max(320, canvas.clientWidth || canvas.parentElement.clientWidth || 640);
      const h = 198;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return { w, h };
    }

    function drawWave() {
      const { w, h } = sizeCanvas();
      const win = viewWindow();
      const dur = Math.max(0.05, win.t1 - win.t0);
      ctx.fillStyle = "#e6c57a";
      ctx.fillRect(0, 0, w, h);
      const pad = WAVE_PAD;
      const innerW = Math.max(1, w - pad * 2);
      const x0 = pad;

      const flagH = 22;
      const clickH = 40;
      const gap = 3;
      const stemH = (h - flagH - clickH - gap * 3) / 2;

      if (data.clickPeaks) {
        drawLane(
          data.clickPeaks.ch[0].min, data.clickPeaks.ch[0].max,
          timeToPeak(data.clickPeaks, win.t0),
          timeToPeak(data.clickPeaks, win.t1),
          x0, flagH, innerW, clickH, "#6a2a12"
        );
      }
      if (data.stemPeaks) {
        const y0 = flagH + clickH + gap;
        drawLane(
          data.stemPeaks.ch[0].min, data.stemPeaks.ch[0].max,
          timeToPeak(data.stemPeaks, win.t0),
          timeToPeak(data.stemPeaks, win.t1),
          x0, y0, innerW, stemH, "#5c4310"
        );
        drawLane(
          data.stemPeaks.ch[1].min, data.stemPeaks.ch[1].max,
          timeToPeak(data.stemPeaks, win.t0),
          timeToPeak(data.stemPeaks, win.t1),
          x0, y0 + stemH + gap, innerW, stemH, "#5c4310"
        );
      }

      ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
      ctx.textAlign = "center";
      for (let i = win.startIdx; i < win.endIdx; i++) {
        const x = x0 + ((data.starts[i] - win.t0) / dur) * innerW;
        ctx.fillStyle = "rgba(40,28,8,0.22)";
        ctx.fillRect(x, flagH, 1, h - flagH);
        const label = barLabel(i);
        const tw = Math.max(22, ctx.measureText(label).width + 10);
        ctx.fillStyle = "#3d8f45";
        ctx.beginPath();
        ctx.moveTo(x - tw / 2, 2);
        ctx.lineTo(x + tw / 2, 2);
        ctx.lineTo(x + tw / 2, 14);
        ctx.lineTo(x, 20);
        ctx.lineTo(x - tw / 2, 14);
        ctx.closePath();
        ctx.fill();
        ctx.fillStyle = "#f4fff4";
        ctx.fillText(label, x, 13);
      }

      const beats = data.beats || [];
      for (const bt of beats) {
        if (bt < win.t0 - 0.01 || bt > win.t1 + 0.01) continue;
        const x = x0 + ((bt - win.t0) / dur) * innerW;
        ctx.fillStyle = "rgba(198,40,40,0.22)";
        ctx.fillRect(x, flagH, 1, h - flagH);
        ctx.fillStyle = "#c62828";
        ctx.fillRect(x, 14, 2, 12);
      }

      if (loop) {
        const x1 = x0 + ((loop.start - win.t0) / dur) * innerW;
        const x2 = x0 + ((loop.end - win.t0) / dur) * innerW;
        const left = Math.min(x1, x2);
        const right = Math.max(x1, x2);
        ctx.fillStyle = "rgba(28, 72, 210, 0.42)";
        ctx.fillRect(left, flagH, Math.max(1, right - left), h - flagH);
        ctx.fillStyle = "#1d4ed8";
        ctx.fillRect(left - 2, flagH, 4, h - flagH);
        ctx.fillRect(right - 2, flagH, 4, h - flagH);
      }

      const t = player.currentTime;
      if (t >= win.t0 && t <= win.t1 + 0.01) {
        const px = x0 + ((t - win.t0) / dur) * innerW;
        ctx.strokeStyle = "#c41e3a";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(px, 0);
        ctx.lineTo(px, h);
        ctx.stroke();
      }
    }

    function render() {
      const w = Number(widthSel.value);
      score.style.gridTemplateColumns = `repeat(${w}, minmax(0, 1fr))`;
      score.innerHTML = "";
      for (let i = 0; i < data.n; i++) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "cell";
        btn.dataset.i = String(i);
        const gi = data.groupOf[String(i)];
        if (gi === undefined) {
          btn.classList.add("ungrouped");
        } else {
          btn.style.background = data.colors[gi % data.colors.length];
        }
        const gLabel = gi === undefined ? "" : `<span class="g">G${gi + 1}</span>`;
        btn.innerHTML = `${barLabel(i)}${gLabel}`;
        btn.title = `Bar ${barLabel(i)}  ${data.starts[i].toFixed(2)}s` +
          (gi === undefined ? "" : `  group ${gi + 1}`);
        btn.addEventListener("click", () => playFrom(i));
        score.appendChild(btn);
      }
      highlight();
      drawWave();
    }

    function playFrom(i) {
      loop = null;
      playStart = i;
      viewOrigin = i;
      stopTime = stopTimeFrom(i);
      player.currentTime = Math.max(0, data.starts[i] + 0.001);
      player.play();
      status.textContent = describePlay(i);
      document.body.focus();
      highlight();
      drawWave();
    }

    function halt(reason) {
      player.pause();
      status.textContent = reason;
      highlight();
      drawWave();
    }

    function togglePause() {
      if (!player.paused) {
        halt("Paused.");
        return;
      }
      if (loop) {
        if (player.currentTime < loop.start - 0.02 || player.currentTime >= loop.end - 0.02) {
          player.currentTime = loop.start + 0.001;
        }
        player.play();
        status.textContent = "Looping selection.";
        highlight();
        drawWave();
        return;
      }
      if (stopTime != null && player.currentTime >= stopTime - 0.05) {
        stopTime = null;
      }
      if (player.ended || player.currentTime >= data.end - 0.02) {
        player.currentTime = Math.max(0, data.starts[playStart] + 0.001);
        stopTime = stopTimeFrom(playStart);
      }
      player.play();
      status.textContent = stopTime == null
        ? "Resumed."
        : describePlay(playStart);
      highlight();
      drawWave();
    }

    function checkLoop() {
      if (!loop || player.paused) return;
      if (player.currentTime >= loop.end - 0.02 || player.currentTime < loop.start - 0.02) {
        player.currentTime = loop.start + 0.001;
      }
    }

    function checkStop() {
      if (loop) return;
      if (stopTime == null || player.paused) return;
      if (player.currentTime >= stopTime - 0.02) {
        player.currentTime = stopTime;
        halt("Stopped after " + stopAfterCount() + " measure" + (stopAfterCount() === 1 ? "" : "s") + ".");
      }
    }

    function setStopAfter(n) {
      stopAfterSel.value = String(n);
      stopTime = player.paused ? null : stopTimeFrom(playStart);
      if (!player.paused && stopTime != null && player.currentTime >= stopTime - 0.02) {
        halt("Stopped after " + n + " measure" + (n === 1 ? "" : "s") + ".");
        return;
      }
      status.textContent = n === 0
        ? "Stop-after off (play through)."
        : "Stop after " + n + " measure" + (n === 1 ? "" : "s") + ".";
      if (!player.paused) status.textContent = describePlay(playStart);
      drawWave();
    }

    function highlight() {
      const idx = player.paused ? -1 : currentBar();
      for (const btn of score.querySelectorAll(".cell")) {
        btn.classList.toggle("playing", Number(btn.dataset.i) === idx);
      }
    }

    function waveLayout() {
      const rect = canvas.getBoundingClientRect();
      const win = viewWindow();
      const innerW = Math.max(1, rect.width - WAVE_PAD * 2);
      return {
        rect,
        win,
        innerW,
        x0: WAVE_PAD,
        dur: Math.max(0.05, win.t1 - win.t0),
      };
    }

    function timeFromClientX(clientX) {
      const L = waveLayout();
      const x = clientX - L.rect.left;
      const frac = (x - L.x0) / L.innerW;
      const t = L.win.t0 + frac * L.dur;
      return Math.max(L.win.t0, Math.min(L.win.t1, t));
    }

    function xFromTime(t) {
      const L = waveLayout();
      return L.x0 + ((t - L.win.t0) / L.dur) * L.innerW;
    }

    function hitLoop(clientX) {
      if (!loop) return null;
      const x = clientX - waveLayout().rect.left;
      const xL = xFromTime(loop.start);
      const xR = xFromTime(loop.end);
      if (Math.abs(x - xL) <= HANDLE_PX) return "resizeL";
      if (Math.abs(x - xR) <= HANDLE_PX) return "resizeR";
      if (x > Math.min(xL, xR) && x < Math.max(xL, xR)) return "move";
      return null;
    }

    function normalizeLoop(start, end) {
      const L = waveLayout();
      let a = Math.min(start, end);
      let b = Math.max(start, end);
      if (b - a < MIN_LOOP) b = a + MIN_LOOP;
      a = Math.max(L.win.t0, Math.min(a, L.win.t1 - MIN_LOOP));
      b = Math.max(a + MIN_LOOP, Math.min(b, L.win.t1));
      return { start: a, end: b };
    }

    function setLoopCursor(clientX) {
      const hit = hitLoop(clientX);
      canvas.style.cursor = hit === "resizeL" || hit === "resizeR"
        ? "ew-resize"
        : hit === "move"
          ? "grab"
          : "crosshair";
    }

    function activateLoop(next, playFromStart) {
      loop = next;
      stopTime = null;
      if (playFromStart || player.currentTime < loop.start || player.currentTime >= loop.end) {
        player.currentTime = loop.start + 0.001;
      }
      player.play();
      status.textContent = "Looping selection. Drag edges to resize, drag the blue region to move. Esc clears.";
      document.body.focus();
    }

    canvas.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      try { canvas.setPointerCapture(event.pointerId); } catch (err) {}
      const t = timeFromClientX(event.clientX);
      const hit = hitLoop(event.clientX);
      if (hit === "resizeL" || hit === "resizeR") {
        drag = { mode: hit, start: loop.start, end: loop.end };
        canvas.style.cursor = "ew-resize";
      } else if (hit === "move") {
        drag = { mode: "move", start: loop.start, end: loop.end, grab: t - loop.start };
        canvas.style.cursor = "grabbing";
      } else {
        drag = { mode: "create", anchor: t, startX: event.clientX };
        loop = null;
      }
    });

    canvas.addEventListener("pointermove", (event) => {
      if (!drag) {
        setLoopCursor(event.clientX);
        return;
      }
      const t = timeFromClientX(event.clientX);
      const L = waveLayout();
      if (drag.mode === "create") {
        loop = normalizeLoop(drag.anchor, t);
      } else if (drag.mode === "resizeL") {
        loop = normalizeLoop(t, drag.end);
      } else if (drag.mode === "resizeR") {
        loop = normalizeLoop(drag.start, t);
      } else if (drag.mode === "move") {
        const dur = drag.end - drag.start;
        let start = t - drag.grab;
        start = Math.max(L.win.t0, Math.min(start, L.win.t1 - dur));
        loop = { start, end: start + dur };
      }
      drawWave();
    });

    canvas.addEventListener("pointerup", (event) => {
      if (!drag) return;
      const t = timeFromClientX(event.clientX);
      if (drag.mode === "create") {
        const moved = Math.abs(event.clientX - drag.startX) > 4;
        if (!moved || !loop || loop.end - loop.start < MIN_LOOP) {
          loop = null;
          player.currentTime = t;
          if (player.paused) player.play();
          status.textContent = "Playing from click.";
        } else {
          activateLoop(loop, true);
        }
      } else if (loop) {
        activateLoop(loop, false);
      }
      drag = null;
      setLoopCursor(event.clientX);
      document.body.focus();
    });

    canvas.addEventListener("pointercancel", () => { drag = null; });

    document.getElementById("stop").addEventListener("click", () => halt("Stopped."));
    widthSel.addEventListener("change", render);
    stopAfterSel.addEventListener("change", () => setStopAfter(stopAfterCount()));
    player.addEventListener("timeupdate", () => { checkLoop(); checkStop(); highlight(); });
    player.addEventListener("ended", () => { status.textContent = "Ended."; highlight(); });
    document.body.addEventListener("mouseenter", () => document.body.focus());
    window.addEventListener("keydown", (event) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const tag = (event.target && event.target.tagName) || "";
      if (event.code === "Space" || event.key === " ") {
        if (tag === "SELECT" || tag === "INPUT") return;
        event.preventDefault();
        togglePause();
        return;
      }
      if (event.code === "Escape") {
        event.preventDefault();
        loop = null;
        status.textContent = "Loop cleared.";
        drawWave();
        return;
      }
      const digit = event.code.startsWith("Digit")
        ? event.code.slice(5)
        : event.code.startsWith("Numpad") && event.code.length === 7
          ? event.code.slice(6)
          : null;
      if (digit === null || digit < "0" || digit > "9") return;
      event.preventDefault();
      setStopAfter(Number(digit));
    }, true);
    window.addEventListener("resize", drawWave);
    function tick() {
      checkLoop();
      checkStop();
      highlight();
      drawWave();
      requestAnimationFrame(tick);
    }
    render();
    requestAnimationFrame(tick);
    document.body.focus();
  </script>
</body>
</html>
"""
