#!/usr/bin/env python3
"""
Take a still photo on Raspberry Pi (libcamera) using Picamera2.
Designed for autofocus-capable modules like Arducam OwlSight 64MP.

Notes:
- Uses picam2.autofocus_cycle() helper (recommended in Picamera2 docs).
- Defaults to a "reasonable" still size. You can pass a size explicitly.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

from picamera2 import Picamera2
from libcamera import controls


def parse_size(s: str) -> tuple[int, int]:
    """
    Parse WIDTHxHEIGHT, e.g. 4624x3472
    """
    try:
        w_str, h_str = s.lower().split("x")
        w, h = int(w_str), int(h_str)
        if w <= 0 or h <= 0:
            raise ValueError
        return (w, h)
    except Exception:
        raise argparse.ArgumentTypeError("Size must be like WIDTHxHEIGHT (e.g. 4624x3472)") from None


def default_output_path() -> Path:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(f"owlsight_{ts}.jpg")


def take_photo(
    output: Path,
    size: tuple[int, int],
    preview_seconds: float = 0.0,
    do_autofocus: bool = True,
) -> None:
    picam2 = Picamera2()

    # Still config at requested output size.
    # (If your exact 64MP full-res mode is heavy on Pi 4, use a smaller size.)
    still_config = picam2.create_still_configuration(
        main={"size": size},
        buffer_count=2,
    )
    picam2.configure(still_config)

    picam2.start()

    # Give AE/AWB a moment to settle.
    time.sleep(0.5)

    # Optional preview warm-up (no GUI required; it's just waiting while streaming).
    if preview_seconds > 0:
        time.sleep(preview_seconds)

    # Autofocus cycle (blocks until done) if supported and requested.
    if do_autofocus:
        cam_controls = picam2.camera_controls
        if "AfMode" in cam_controls:
            # Recommended helper function from Picamera2 manual.
            success = picam2.autofocus_cycle()
            if not success:
                print("[warn] Autofocus cycle reported failure; capturing anyway.", file=sys.stderr)
        else:
            print("[warn] Camera does not advertise autofocus controls; skipping AF.", file=sys.stderr)

    output.parent.mkdir(parents=True, exist_ok=True)
    picam2.capture_file(str(output))

    picam2.stop()
    print(f"[ok] Saved: {output.resolve()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Take a photo with Arducam OwlSight / libcamera using Picamera2.")
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=default_output_path(),
        help="Output JPG path (default: timestamped in current directory).",
    )
    parser.add_argument(
        "--size",
        type=parse_size,
        default=(4624, 3472),
        help="Still size as WIDTHxHEIGHT. Default is 4624x3472 (often a good balance on Pi 4).",
    )
    parser.add_argument(
        "--preview-seconds",
        type=float,
        default=0.0,
        help="Seconds to wait while camera runs before focusing/capturing (helps exposure settle).",
    )
    parser.add_argument(
        "--no-af",
        action="store_true",
        help="Disable autofocus cycle.",
    )

    args = parser.parse_args()

    take_photo(
        output=args.output,
        size=args.size,
        preview_seconds=max(0.0, args.preview_seconds),
        do_autofocus=not args.no_af,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())