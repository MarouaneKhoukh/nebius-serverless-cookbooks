"""Offline media checks; real ffmpeg runs, no embedding service or GPU."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from media_search.media import MediaError, prepare_file


class ImagePreparationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"

    def tearDown(self):
        self.temp.cleanup()

    def test_exif_orientation_rgb_metadata_and_reuse(self):
        source = self.root / "portrait.jpg"
        exif = Image.Exif()
        exif[274] = 6  # Rotate a 1600x800 source 90 degrees clockwise.
        exif[270] = "metadata must not reach the normalized image"
        Image.new("RGB", (1600, 800), "red").save(source, exif=exif)
        first = list(prepare_file(source, self.data))[0]
        with Image.open(self.data / first.media_path) as image:
            self.assertEqual(image.size, (512, 1024))
            self.assertEqual(image.mode, "RGB")
            self.assertFalse(image.getexif())
        with Image.open(self.data / first.thumbnail_path) as thumbnail:
            self.assertEqual(thumbnail.size, (240, 480))
        original_mtime = (self.data / first.media_path).stat().st_mtime_ns
        second = list(prepare_file(source, self.data))[0]
        self.assertEqual(first, second)
        self.assertEqual(original_mtime, (self.data / second.media_path).stat().st_mtime_ns)
        self.assertTrue(first.media_path.startswith("media/"))
        self.assertIsNone(first.start_seconds)
        self.assertIsNone(first.end_seconds)

    def test_transparency_white_background_and_content_identity(self):
        source = self.root / "alpha.png"
        Image.new("RGBA", (20, 20), (255, 0, 0, 0)).save(source)
        first = list(prepare_file(source, self.data))[0]
        renamed = self.root / "different_name.png"
        shutil.copyfile(source, renamed)
        second = list(prepare_file(renamed, self.data))[0]
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.source_name, "different_name.png")
        self.assertEqual(second.title, "different name")
        with Image.open(self.data / first.media_path) as result:
            self.assertEqual(result.getpixel((10, 10)), (255, 255, 255))
        different_setting = list(prepare_file(source, self.data, clip_seconds=4))[0]
        self.assertNotEqual(first.id, different_setting.id)

    def test_bad_image_does_not_publish_partial_cache(self):
        source = self.root / "broken.jpg"
        source.write_text("not an image")
        with self.assertRaisesRegex(MediaError, "Cannot decode"):
            list(prepare_file(source, self.data))
        self.assertEqual(list((self.data / "media").iterdir()), [])

    def test_file_and_pixel_limits(self):
        source = self.root / "small.png"
        Image.new("RGB", (10, 10), "blue").save(source)
        with patch("media_search.media.MAX_IMAGE_BYTES", 1):
            with self.assertRaisesRegex(MediaError, "input limit"):
                list(prepare_file(source, self.data))
        with patch("media_search.media.MAX_IMAGE_PIXELS", 10):
            with self.assertRaisesRegex(MediaError, "megapixel"):
                list(prepare_file(source, self.data))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
class VideoPreparationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.video = self.root / "test.mp4"
        subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=red:s=640x360:r=8:d=12",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "2",
            "-c:a", "aac", "-shortest", str(self.video),
        ], check=True, timeout=30, stdin=subprocess.DEVNULL)

    def tearDown(self):
        self.temp.cleanup()

    def probe(self, path):
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
        ], capture_output=True, text=True, check=True, timeout=10)
        return json.loads(result.stdout)

    def test_native_video_split_timestamps_and_constraints(self):
        records = list(prepare_file(self.video, self.data))
        self.assertEqual(len(records), 2)
        self.assertEqual([(r.start_seconds, r.end_seconds) for r in records], [(0, 8), (8, 12)])
        self.assertEqual(len({r.id for r in records}), 2)
        for index, record in enumerate(records):
            path = self.data / record.media_path
            probe = self.probe(path)
            self.assertEqual(len(probe["streams"]), 1)
            stream = probe["streams"][0]
            self.assertEqual(stream["codec_name"], "h264")
            self.assertEqual(stream["pix_fmt"], "yuv420p")
            self.assertEqual(stream["avg_frame_rate"], "2/1")
            self.assertLessEqual(max(stream["width"], stream["height"]), 448)
            self.assertAlmostEqual(float(probe["format"]["duration"]), 8 if index == 0 else 4, places=1)
            self.assertLessEqual(path.stat().st_size, 8 * 1024 * 1024)
            with Image.open(self.data / record.thumbnail_path) as thumbnail:
                self.assertLessEqual(max(thumbnail.size), 480)
        self.assertEqual(records, list(prepare_file(self.video, self.data)))

    def test_duration_bound_checked_before_publishing(self):
        with self.assertRaisesRegex(MediaError, "Trim it"):
            list(prepare_file(self.video, self.data, max_video_seconds=10))
        self.assertFalse((self.data / "media").exists())

    def test_failed_later_clip_leaves_no_partially_published_source(self):
        from media_search import media
        real_run = media._run
        clip_calls = 0

        def fail_second_clip(command, timeout):
            nonlocal clip_calls
            if command[0] == "ffmpeg" and "libx264" in command:
                clip_calls += 1
                if clip_calls == 2:
                    raise MediaError("intentional conversion failure")
            return real_run(command, timeout)

        with patch("media_search.media._run", side_effect=fail_second_clip):
            with self.assertRaisesRegex(MediaError, "intentional"):
                list(prepare_file(self.video, self.data))
        self.assertEqual(list((self.data / "media").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
