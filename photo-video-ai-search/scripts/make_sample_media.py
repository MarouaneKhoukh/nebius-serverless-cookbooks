#!/usr/bin/env python3
"""Create three clearly synthetic images. No downloads or model calls."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image, ImageDraw


def draw_scene(shape: str, color: str, center_x: int = 320) -> Image.Image:
    image = Image.new("RGB", (640, 480), "#f4f4ef")
    draw = ImageDraw.Draw(image)
    x, y, size = center_x, 235, 110
    if shape == "circle":
        draw.ellipse((x-size, y-size, x+size, y+size), fill=color)
    elif shape == "square":
        draw.rectangle((x-size, y-size, x+size, y+size), fill=color)
    else:
        draw.polygon([(x, y-size), (x-size, y+size), (x+size, y+size)], fill=color)
    draw.text((20, 20), "SYNTHETIC GEOMETRIC SAMPLE", fill="#222222")
    draw.text((20, 440), f"{color} {shape} on a light background", fill="#222222")
    return image


def generate(output: Path, include_video: bool = False) -> None:
    output = output.resolve()
    if output.exists():
        raise ValueError(f"Output already exists: {output}. Choose a new directory.")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".synthetic-media-", dir=output.parent))
    try:
        for shape, color in [("circle", "red"), ("square", "blue"), ("triangle", "green")]:
            draw_scene(shape, color).save(staging / f"synthetic_{color}_{shape}.png")
        if include_video:
            with tempfile.TemporaryDirectory(prefix="sample-video-frames-") as frames_dir:
                frames = Path(frames_dir)
                for index in range(24):
                    # Two unmistakably synthetic scenes, six seconds each at 2 fps.
                    shape, color = ("circle", "red") if index < 12 else ("triangle", "green")
                    x = 320 + int(120 * math.sin(index * math.pi / 12))
                    draw_scene(shape, color, x).save(frames / f"frame-{index:03d}.png")
                subprocess.run([
                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-framerate", "2", "-i", str(frames / "frame-%03d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", "-threads", "2",
                    "-movflags", "+faststart", str(staging / "synthetic_shapes_animation.mp4"),
                ], check=True, timeout=60, stdin=subprocess.DEVNULL)
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("sample_images"))
    parser.add_argument("--include-video", action="store_true",
                        help="Also create the historical 12-second clip (requires FFmpeg; not used by the image demo).")
    args = parser.parse_args()
    try:
        generate(args.output, include_video=args.include_video)
    except FileNotFoundError as exc:
        parser.exit(1, f"ffmpeg is required to create the sample video: {exc}\n")
    except (ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"Cannot create sample media: {exc}\n")
    suffix = " and the optional historical 12-second video" if args.include_video else ""
    print(f"Created 3 synthetic images{suffix} in {args.output.resolve()}")
    print("Suggested queries: red circle; blue square; green triangle.")
    print("These fixtures exercise the pipeline; they do not measure retrieval quality.")


if __name__ == "__main__":
    main()
