"""Normalize local media into bounded images and native video clips.

Files published under ``data_dir/media`` are immutable, content-addressed assets.
Preparing a source finishes completely before any records are yielded. A failed
conversion removes its temporary files and leaves no partially published source.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Iterator
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | VIDEO_SUFFIXES
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_VIDEO_BYTES = 512 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_CLIP_BYTES = 8 * 1024 * 1024
PREPROCESS_VERSION = "media-v1-rgb1024-video448-2fps"


class MediaError(ValueError):
    """An unsupported, oversized, corrupt, or unconvertible media source."""


@dataclass(frozen=True)
class PreparedMedia:
    id: str
    kind: str
    title: str
    media_path: str
    thumbnail_path: str
    source_name: str
    start_seconds: float | None
    end_seconds: float | None
    source_hash: str


def _run(command: list[str], timeout: float) -> str:
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, check=True,
            timeout=timeout, stdin=subprocess.DEVNULL,
        )
        return completed.stdout
    except FileNotFoundError as exc:
        raise MediaError(
            f"{command[0]} is required for videos. Install ffmpeg (which includes ffprobe)."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{command[0]} exceeded its {timeout:g}-second conversion limit.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "conversion failed").strip()[-1500:]
        raise MediaError(f"{command[0]} could not process this media: {detail}") from exc


def _source_hash(source: Path, limit: int) -> str:
    if not source.is_file():
        raise MediaError(f"Source is not a regular file: {source}")
    if source.stat().st_size > limit:
        raise MediaError(f"{source.name} exceeds the {limit // (1024 * 1024)} MiB input limit.")
    digest = hashlib.sha256()
    read = 0
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            read += len(chunk)
            if read > limit:
                raise MediaError(f"{source.name} exceeds the input limit.")
            digest.update(chunk)
    if read == 0:
        raise MediaError(f"{source.name} is empty.")
    return digest.hexdigest()


def _save_image(source: Path, destination: Path, max_edge: int) -> None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as opened:
                if opened.width * opened.height > MAX_IMAGE_PIXELS:
                    raise MediaError(f"{source.name} exceeds the 40-megapixel decoded-image limit.")
                if getattr(opened, "is_animated", False):
                    raise MediaError("Animated images are unsupported; convert the animation to MP4.")
                oriented = ImageOps.exif_transpose(opened)
                oriented.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                if oriented.mode in ("RGBA", "LA") or "transparency" in oriented.info:
                    rgba = oriented.convert("RGBA")
                    result = Image.new("RGB", rgba.size, "white")
                    result.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    result = oriented.convert("RGB")
                # Fresh RGB pixels omit source EXIF, GPS, comments, and ICC metadata.
                result.save(destination, "JPEG", quality=88, optimize=True)
    except MediaError:
        raise
    except (UnidentifiedImageError, OSError, ValueError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise MediaError(f"Cannot decode {source.name} as a safe image: {exc}") from exc


def _video_duration(source: Path) -> float:
    raw = _run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration:format=duration",
        "-of", "json", str(source),
    ], 30)
    try:
        probe = json.loads(raw)
        stream = probe["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        # WebM/MKV streams often omit duration or report N/A even when the
        # enclosing container has a valid duration.
        duration = float("nan")
        for candidate in (stream.get("duration"), probe.get("format", {}).get("duration")):
            try:
                parsed = float(candidate)
            except (TypeError, ValueError):
                continue
            if math.isfinite(parsed) and parsed > 0:
                duration = parsed
                break
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MediaError(f"Cannot determine video dimensions and duration for {source.name}.") from exc
    if min(width, height) < 2 or width * height > 64_000_000:
        raise MediaError("Video dimensions must be at least 2 pixels and at most 64 megapixels.")
    if not math.isfinite(duration) or duration <= 0:
        raise MediaError("Video duration must be a finite positive number.")
    return duration


def _timestamp(seconds: float) -> str:
    minutes, remaining = divmod(seconds, 60)
    return f"{int(minutes):02d}:{remaining:04.1f}"


def _records(manifest: dict, target: Path, source: Path, data_dir: Path) -> list[PreparedMedia]:
    records = []
    for asset in manifest["assets"]:
        media_file = target / asset["media_file"]
        thumbnail_file = target / asset["thumbnail_file"]
        if not media_file.is_file() or not thumbnail_file.is_file():
            raise MediaError(f"Incomplete prepared-media cache at {target}; remove it and ingest again.")
        title = source.stem.replace("_", " ").replace("-", " ")
        if asset["kind"] == "video":
            title += f" · {_timestamp(asset['start_seconds'])}–{_timestamp(asset['end_seconds'])}"
        records.append(PreparedMedia(
            id=asset["id"], kind=asset["kind"], title=title,
            media_path=media_file.relative_to(data_dir).as_posix(),
            thumbnail_path=thumbnail_file.relative_to(data_dir).as_posix(),
            source_name=source.name,
            start_seconds=asset["start_seconds"], end_seconds=asset["end_seconds"],
            source_hash=manifest["source_hash"],
        ))
    return records


def prepare_file(
    source: Path, data_dir: Path, clip_seconds: float = 8.0,
    max_video_seconds: float = 120.0,
) -> Iterator[PreparedMedia]:
    """Yield prepared assets; filenames/titles are metadata, never embedding input.

    Images become RGB JPEGs with a 1024-pixel maximum edge. Videos become
    silent H.264/yuv420p MP4 clips at 2 fps with a 448-pixel maximum edge.
    A clip is at most 8 seconds / 8 MiB; a source is at most 120 seconds.
    IDs include source bytes, preprocessing version, and requested clip duration.
    """
    source, data_dir = Path(source).resolve(), Path(data_dir).resolve()
    if not math.isfinite(clip_seconds) or not 0 < clip_seconds <= 8:
        raise MediaError("clip_seconds must be greater than 0 and at most 8.")
    if not math.isfinite(max_video_seconds) or not 0 < max_video_seconds <= 120:
        raise MediaError("max_video_seconds must be greater than 0 and at most 120.")
    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise MediaError(f"Unsupported file {source.name}; use JPEG, PNG, WebP, MP4, MOV, MKV, or WebM.")
    is_video = suffix in VIDEO_SUFFIXES
    source_hash = _source_hash(source, MAX_VIDEO_BYTES if is_video else MAX_IMAGE_BYTES)
    key = hashlib.sha256(
        f"{PREPROCESS_VERSION}|{source_hash}|clip={clip_seconds:.9g}".encode()
    ).hexdigest()
    # Check the requested bound even when reusing an earlier conversion.
    duration = _video_duration(source) if is_video else None
    if duration is not None and duration > max_video_seconds + 1e-6:
        raise MediaError(
            f"{source.name} lasts {duration:.2f}s; the input limit is {max_video_seconds:g}s. "
            "Trim it before ingesting."
        )
    media_root = data_dir / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    target = media_root / key
    if target.exists():
        try:
            manifest = json.loads((target / "manifest.json").read_text())
            yield from _records(manifest, target, source, data_dir)
            return
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise MediaError(f"Invalid prepared-media cache at {target}; remove it and ingest again.") from exc
    staging = Path(tempfile.mkdtemp(prefix=".prepare-", dir=media_root))
    assets = []
    try:
        if not is_video:
            _save_image(source, staging / "image.jpg", 1024)
            _save_image(staging / "image.jpg", staging / "thumbnail.jpg", 480)
            assets.append(dict(id=key, kind="image", media_file="image.jpg",
                               thumbnail_file="thumbnail.jpg", start_seconds=None,
                               end_seconds=None))
        else:
            assert duration is not None
            count = max(1, math.ceil(duration / clip_seconds - 1e-9))
            for index in range(count):
                start, end = index * clip_seconds, min((index + 1) * clip_seconds, duration)
                stem = f"clip-{index:04d}"
                clip = staging / f"{stem}.mp4"
                thumbnail = staging / f"{stem}.jpg"
                _run([
                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{start:.9f}", "-i", str(source), "-t", f"{end-start:.9f}",
                    "-map", "0:v:0", "-an", "-sn", "-dn", "-map_metadata", "-1",
                    "-vf", "fps=2:eof_action=pass:round=up,scale='min(448,iw)':'min(448,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                    "-pix_fmt", "yuv420p", "-threads", "2", "-movflags", "+faststart", str(clip),
                ], 180)
                if not clip.exists() or not 0 < clip.stat().st_size <= MAX_CLIP_BYTES:
                    raise MediaError(f"Video clip {index + 1} is empty or exceeds the 8 MiB clip limit.")
                _run([
                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(clip), "-frames:v", "1", "-update", "1", str(thumbnail),
                ], 30)
                # Strip metadata from the thumbnail using the same image path.
                clean_thumbnail = staging / f"{stem}-clean.jpg"
                _save_image(thumbnail, clean_thumbnail, 480)
                clean_thumbnail.replace(thumbnail)
                assets.append(dict(
                    id=hashlib.sha256(f"{key}|{index}".encode()).hexdigest(),
                    kind="video", media_file=clip.name, thumbnail_file=thumbnail.name,
                    start_seconds=start, end_seconds=end,
                ))
        manifest = {"version": PREPROCESS_VERSION, "source_hash": source_hash, "assets": assets}
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        try:
            staging.rename(target)
        except OSError:
            if not target.is_dir():
                raise
            # Another ingestion may have atomically published this same content.
            manifest = json.loads((target / "manifest.json").read_text())
        yield from _records(manifest, target, source, data_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
