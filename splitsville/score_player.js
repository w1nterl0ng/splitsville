export default function (component) {
  try {
    boot(component);
  } catch (err) {
    console.error("splitsville score", err);
  }
}

function boot(component) {
  const root = component.parentElement;
  if (!root || typeof root.querySelector !== "function") return;
  const incoming = component.data || {};
  if (root.__svReady) {
    if (incoming.measure_meta) root.__svApplyMeta(incoming.measure_meta);
    return;
  }
  const data = incoming.payload;
  const measureMeta = Object.assign({}, incoming.measure_meta || {});
  root.__svApplyMeta = (next) => {
    Object.keys(measureMeta).forEach((k) => delete measureMeta[k]);
    Object.assign(measureMeta, next || {});
    if (typeof render === "function") render();
  };
  if (incoming.audio) {
    const el = root.querySelector("#player");
    if (el) el.src = "data:" + incoming.mime + ";base64," + incoming.audio;
  }
  function isLocked(i) {
    const row = measureMeta[String(i)];
    return !!(row && row.locked);
  }
  function phraseLocked(start, n) {
    for (let k = 0; k < n; k++) if (!isLocked(start + k)) return false;
    return n > 0;
  }
  function togglePhraseLock(start, n, event) {
    if (event) event.stopPropagation();
    const next = !phraseLocked(start, n);
    for (let k = 0; k < n; k++) {
      const key = String(start + k);
      const row = Object.assign({ locked: false, status: "open", notes: "", tags: [], meta: {} }, measureMeta[key] || {});
      row.locked = next;
      row.status = next ? "done" : "open";
      measureMeta[key] = row;
    }
    component.setStateValue("measure_meta", Object.assign({}, measureMeta));
    render();
  }
    const score = root.querySelector("#score");
    const matches = root.querySelector("#matches");
    const player = root.querySelector("#player");
    const widthSel = root.querySelector("#width");
    const stopAfterSel = root.querySelector("#stopAfter");
    const speedSel = root.querySelector("#speed");
    const status = root.querySelector("#status");
    const shell = root.querySelector(".sv-root");
    if (!score || !player || !widthSel || !data || !shell) return;
    root.__svReady = true;
    function barLabel(i) {
      const labels = data.labels || [];
      return labels[i] || String(i + 1);
    }
    const canvas = root.querySelector("#wave");
    const ctx = canvas.getContext("2d");
    widthSel.value = String(data.defaultWidth);
    shell.tabIndex = 0;
    let playStart = 0;
    let viewOrigin = 0;
    let stopTime = null;
    let loop = null;
    let drag = null;
    let panelAnchor = 0;
    const WAVE_PAD = 14;
    const HANDLE_PX = 8;
    const MIN_LOOP = 0.08;

    function stopAfterCount() {
      return Number(stopAfterSel.value) || 0;
    }

    function applySpeed() {
      const rate = Number(speedSel.value) || 1;
      player.playbackRate = rate;
      player.preservesPitch = true;
      player.webkitPreservesPitch = true;
      player.mozPreservesPitch = true;
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
        const done = isLocked(i) ? `<span class="done">done</span>` : "";
        btn.innerHTML = `${barLabel(i)}${gLabel}${done}`;
        if (isLocked(i)) btn.classList.add("locked");
        btn.title = `Bar ${barLabel(i)}  ${data.starts[i].toFixed(2)}s` +
          (gi === undefined ? "" : `  group ${gi + 1}`) +
          (isLocked(i) ? "  done" : "");
        btn.addEventListener("click", () => playFrom(i));
        score.appendChild(btn);
      }
      renderMatchPanel();
      highlight();
      drawWave();
    }

    function barToken(i) {
      const g = data.groupOf[String(i)];
      return g === undefined ? "u:" + i : "g:" + g;
    }

    function phraseLength(anchor) {
      const n = stopAfterCount();
      const len = n > 0 ? n : 1;
      return Math.max(1, Math.min(len, data.n - anchor));
    }

    function phraseStarts(anchor) {
      const n = phraseLength(anchor);
      const pat = [];
      for (let k = 0; k < n; k++) pat.push(barToken(anchor + k));
      const starts = [];
      for (let i = 0; i <= data.n - n; i++) {
        let ok = true;
        for (let k = 0; k < n; k++) {
          if (barToken(i + k) !== pat[k]) {
            ok = false;
            break;
          }
        }
        if (ok) starts.push(i);
      }
      return { n, starts };
    }

    function beatStrip(idx, subdivN, isTruth) {
      const vals = ratingFor(idx, subdivN, isTruth);
      let html = `<div class="mcol"><div class="mlabel"><span>${barLabel(idx)}</span></div><div class="beats">`;
      for (const v of vals) {
        html += `<div class="beat" title="${v.toFixed(2)}" style="background:${confColor(v)}"></div>`;
      }
      return html + `</div></div>`;
    }

    function confColor(c) {
      // Same-music takes are ~0.90–0.99. Keep those green; reserve red for real riff changes.
      const x = Math.min(1, Math.max(0, (Number(c) - 0.80) / 0.18));
      const stops = x < 0.5
        ? [[239, 68, 68], [234, 179, 8], x * 2]
        : [[234, 179, 8], [34, 197, 94], (x - 0.5) * 2];
      const t = stops[2];
      const r = Math.round(stops[0][0] + (stops[1][0] - stops[0][0]) * t);
      const g = Math.round(stops[0][1] + (stops[1][1] - stops[0][1]) * t);
      const b = Math.round(stops[0][2] + (stops[1][2] - stops[0][2]) * t);
      return `rgb(${r}, ${g}, ${b})`;
    }

    function ratingFor(idx, n, isTruth) {
      if (isTruth) return Array.from({ length: n }, () => 1);
      const found = (data.subdivConf || {})[String(idx)];
      if (found && found.length) return found;
      return Array.from({ length: n }, () => 1);
    }

    function renderMatchPanel() {
      const { n, starts } = phraseStarts(panelAnchor);
      const truthStart = starts[0];
      const title = n === 1
        ? (data.groupOf[String(panelAnchor)] === undefined
          ? barLabel(panelAnchor)
          : `G${Number(data.groupOf[String(panelAnchor)]) + 1} vs ${barLabel(truthStart)}`)
        : `${n}-bar phrase`;
      const hint = n === 1
        ? "Each cell is a beat. Green matches the first bar in the group. Done marks a bar finished in Guitar Pro."
        : "Each row is the same " + n + " groups in a row. Green matches the first time that phrase appears. Done locks every bar in the row.";
      const listening = player.paused ? panelAnchor : currentBar();
      let html = `<h3>${title}</h3><p class="hint">${hint}</p>`;
      for (const start of starts) {
        const isTruth = start === truthStart;
        const on = listening >= start && listening < start + n;
        const locked = phraseLocked(start, n);
        const rowLabel = [];
        for (let k = 0; k < n; k++) rowLabel.push(barLabel(start + k));
        html += `<div class="mrow${on ? " listening" : ""}${locked ? " locked" : ""}" data-i="${start}">`;
        html += `<div class="mlabel"><span>${rowLabel.join("–")}</span><span class="mlabel-right">`;
        html += isTruth ? '<span class="truth">reference</span>' : "";
        html += `<button type="button" class="lockbtn" data-lock="${start}">${locked ? "Done" : "Mark done"}</button>`;
        html += `</span></div>`;
        html += `<div class="phrase">`;
        for (let k = 0; k < n; k++) {
          const idx = start + k;
          const subdivN = Math.max(1, (data.subdivs && data.subdivs[idx]) || 4);
          html += beatStrip(idx, subdivN, isTruth);
        }
        html += `</div></div>`;
      }
      matches.innerHTML = html;
      for (const row of matches.querySelectorAll(".mrow")) {
        row.addEventListener("click", () => playFrom(Number(row.dataset.i), true));
      }
      for (const btn of matches.querySelectorAll(".lockbtn")) {
        btn.addEventListener("click", (event) => {
          const start = Number(btn.dataset.lock);
          togglePhraseLock(start, phraseLength(start), event);
        });
      }
    }

    function playFrom(i, keepPanel) {
      loop = null;
      playStart = i;
      viewOrigin = i;
      if (!keepPanel) panelAnchor = i;
      stopTime = stopTimeFrom(i);
      player.currentTime = Math.max(0, data.starts[i] + 0.001);
      player.play();
      status.textContent = describePlay(i);
      renderMatchPanel();
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
      renderMatchPanel();
      highlight();
      drawWave();
    }

    function highlight() {
      const idx = player.paused ? -1 : currentBar();
      for (const btn of score.querySelectorAll(".cell")) {
        const i = Number(btn.dataset.i);
        btn.classList.toggle("playing", i === idx);
        btn.classList.toggle("locked", isLocked(i));
      }
      const listening = idx < 0 ? panelAnchor : idx;
      for (const row of matches.querySelectorAll(".mrow")) {
        const start = Number(row.dataset.i);
        const n = phraseLength(start);
        row.classList.toggle("listening", listening >= start && listening < start + n);
        row.classList.toggle("locked", phraseLocked(start, n));
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
    });

    canvas.addEventListener("pointercancel", () => { drag = null; });

    root.querySelector("#stop").addEventListener("click", () => halt("Stopped."));
    widthSel.addEventListener("change", render);
    stopAfterSel.addEventListener("change", () => setStopAfter(stopAfterCount()));
    speedSel.addEventListener("change", applySpeed);
    applySpeed();
    player.addEventListener("timeupdate", () => { checkLoop(); checkStop(); highlight(); });
    player.addEventListener("ended", () => { status.textContent = "Ended."; highlight(); });
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
}
