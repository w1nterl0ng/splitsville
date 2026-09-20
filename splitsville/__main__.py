from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect measure clicks, split a stem, and group matching bars."
    )
    parser.add_argument(
        "--click",
        required=True,
        help="Transcribe .xsc markers or a click track (WAV/FLAC/MP3)",
    )
    parser.add_argument("--stem", help="Stem (WAV/FLAC/MP3). Optional if the .xsc has SoundFileName.")
    parser.add_argument("--out", default="output", help="Output directory for sliced measures")
    parser.add_argument("--min-interval", type=float, default=0.6)
    parser.add_argument("--click-threshold", type=float, default=0.25)
    parser.add_argument("--match-threshold", type=float, default=0.85)
    args = parser.parse_args()

    out = Path(args.out)
    result = run_pipeline(
        args.click,
        args.stem,
        min_interval=args.min_interval,
        click_threshold=args.click_threshold,
        match_threshold=args.match_threshold,
        out_dir=out,
    )

    payload = {
        "click_times": result.click_times.tolist(),
        "measures": [
            {"index": i, "start": start, "end": end} for i, start, end in result.measures
        ],
        "groups": result.groups,
        "marker_source": result.marker_source,
        "beat_times": result.beat_times,
        "sound_path": result.sound_path,
    }
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "result.json"
    json_path.write_text(json.dumps(payload, indent=2))
    print(f"source: {result.marker_source}")
    print(f"measures: {len(result.measures)}")
    print(f"beats: {len(result.beat_times)}")
    if result.sound_path:
        print(f"sound: {result.sound_path}")
    print(f"matching groups: {result.groups}")
    print(f"wrote {json_path}")


if __name__ == "__main__":
    main()
