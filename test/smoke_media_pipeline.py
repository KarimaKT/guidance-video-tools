"""Synthetic smoke test for the shared FFmpeg media pipeline."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sanitizer"))

from clip_extractor import ClipSpec, extract_clip
from media_pipeline import concat_videos, render_segment, run_command, validate_media


def main() -> int:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("SKIP: ffmpeg/ffprobe not found")
        return 0

    with tempfile.TemporaryDirectory(prefix="cat_video_smoke_") as tmp:
        work = Path(tmp)
        source = work / "source.mp4"
        seg_a = work / "seg_a.mp4"
        seg_b = work / "seg_b.mp4"
        output = work / "concat.mp4"
        slide = work / "slide_scene.mp4"
        embedded = work / "embedded_video_scene.mp4"
        mixed = work / "mixed_concat.mp4"

        run_command(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=320x180:rate=30:duration=4",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=880:sample_rate=48000:duration=4",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                str(source),
            ],
            "create synthetic source",
        )

        render_segment(input_path=source, output_path=seg_a, start=0.25, end=1.75)
        render_segment(input_path=source, output_path=seg_b, start=2.0, end=3.5)
        summary = concat_videos([seg_a, seg_b], output)
        validate_media(output)
        run_command(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x111827:size=1280x720:rate=30:duration=2",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(slide),
            ],
            "create synthetic slide scene",
        )
        run_command(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=960x540:rate=25:duration=3",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=660:sample_rate=44100:duration=3",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(embedded),
            ],
            "create embedded video scene with different media shape",
        )
        mixed_summary = concat_videos([slide, embedded, slide], mixed)
        validate_media(mixed)
        extracted = extract_clip(
            video_path=source,
            clip=ClipSpec(id="smoke clip", title="Smoke Clip", start=0.5, end=1.5),
            output_dir=work / "clips",
        )

        if summary["audio_streams"] != 1 or summary["video_streams"] != 1:
            raise AssertionError(f"Unexpected stream counts: {summary}")
        if not 2.5 <= summary["duration"] <= 3.5:
            raise AssertionError(f"Unexpected output duration: {summary}")
        if not 6.5 <= mixed_summary["duration"] <= 7.5:
            raise AssertionError(f"Unexpected mixed concat duration: {mixed_summary}")
        if not Path(extracted["output_path"]).exists():
            raise AssertionError("Clip extractor did not create an output")

    print("media pipeline smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
