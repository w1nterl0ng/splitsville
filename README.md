# Splitsville

Streamlit app for turning a Transcribe `.xsc` map (or a click track) plus a stem into a color-coded score of matching measures. Use it while you notate in Guitar Pro: click a bar to hear it, then mark it **done** when that bar is finished.

## Setup

Python 3.11+, ffmpeg on your PATH (for MP3), and:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run the app

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501). After changing the score player (`splitsville/score.py` or `splitsville/score_player.js`), **restart** Streamlit; a browser refresh is not enough for that custom component.

## Deploy to Streamlit Community Cloud

The repo is already set up for [Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app): `app.py` is the entrypoint, `requirements.txt` lists Python packages, and `packages.txt` installs `ffmpeg` (MP3) plus `libsndfile1` (WAV/FLAC via soundfile).

1. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub.
2. **Create app**, then set repository `w1nterl0ng/splitsville`, branch `main`, main file `app.py`, Python 3.11+.
3. **Deploy**. The app URL will be `https://<name>.streamlit.app`. Pushes to `main` redeploy automatically.

On Cloud, an `.xsc` cannot pull a stem from a path on your Mac. Upload the stem (or a `.splitsville` session) in the app. Large stems may hit the free-tier memory limit or the in-browser player size cap.

## Workflow

1. **Markers** — upload a Transcribe `.xsc`. If `SoundFileName` / `SoundFileInfo` points at a file on disk, the stem is loaded automatically. Otherwise upload a click track (WAV/FLAC/MP3) and a stem.
2. **Match** — bars that sound alike share a color. Sidebar: min measure length, click threshold, match threshold, and instrument band (Auto / Bass / Guitar). Auto guesses from the stem spectrum.
3. **Listen** — click a cell to play from that bar. Uncheck **Auto-play** to click around the main grid without sound (right panel still updates). The match panel on the right always plays. Waveform drag loops like Logic. `Space` pause/resume, `Esc` clears the loop, `0`–`9` set stop-after N measures. Speed is 50–120% in the browser (`playbackRate`, pitch preserved).
4. **Guitar Pro** — on the right, **Mark done** greys that bar on the grid so you can track what is already notated. **Clear done** (top of the match panel, or in the sidebar) resets every bar to not done. Silent bars (whole rests) show a rest mark instead of a group color.
5. **Save / open** — **Save session** downloads a `.splitsville` zip (markers, stem, matching, per-measure metadata). Open it from the sidebar later without re-importing.

## Session file

A `.splitsville` file is a zip:

| Path | Contents |
|------|----------|
| `project.json` | Versioned document: settings, analysis, per-measure `{label, locked, status, notes, tags, meta}` plus `project_meta`. Extra JSON keys are kept for later fields. |
| `media/markers` | `.xsc` or click audio |
| `media/stem` | Stem used for matching and playback |

You can also open a bare `project.json` or a zip, as long as the media is inside or still reachable.

## Matching

Measures are grouped from a log-spectrogram similarity matrix (union-find). Bass uses roughly 40–400 Hz; guitar 80–2500 Hz. The right-hand panel rates each subdivision against the first bar in that group (green similar, red different). Phrase stacking appears when stop-after is 2 or more (n-grams of group IDs).

Tablature stays in Guitar Pro; this app is the map, listen, match, and progress tracker.

## CLI

Headless slice + match (writes `output/result.json` and sliced WAVs):

```bash
python -m splitsville --click map.xsc --stem stem.wav --out output
```

`--stem` is optional when the `.xsc` already names a sound file.

## Tests

```bash
pytest
```
