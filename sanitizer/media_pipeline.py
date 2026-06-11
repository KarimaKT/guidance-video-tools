"""Shared FFmpeg media helpers for reliable video rendering."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


class MediaPipelineError(RuntimeError):
    """Raised when FFmpeg/ffprobe media processing fails."""


def run_command(cmd: list[str], label: str) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr[-3000:] if result.stderr else ""
        raise MediaPipelineError(f"{label} failed with exit code {result.returncode}\n{stderr}")
    return result


def ffprobe(path: str | Path) -> dict:
    result = run_command(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        f"ffprobe {path}",
    )
    return json.loads(result.stdout) if result.stdout else {}


def media_summary(path: str | Path) -> dict:
    info = ffprobe(path)
    streams = info.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    duration = float(info.get("format", {}).get("duration") or 0)
    return {
        "duration": duration,
        "video_streams": len(video_streams),
        "audio_streams": len(audio_streams),
        "video_codec": video_streams[0].get("codec_name") if video_streams else "",
        "audio_codec": audio_streams[0].get("codec_name") if audio_streams else "",
    }


def validate_media(path: str | Path, *, require_audio: bool = True) -> dict:
    target = Path(path)
    if not target.exists() or target.stat().st_size == 0:
        raise MediaPipelineError(f"Output was not created or is empty: {target}")

    summary = media_summary(target)
    if summary["video_streams"] < 1:
        raise MediaPipelineError(f"Output has no video stream: {target}")
    if require_audio and summary["audio_streams"] < 1:
        raise MediaPipelineError(f"Output has no audio stream: {target}")
    if summary["duration"] <= 0:
        raise MediaPipelineError(f"Output has invalid duration: {target}")
    return summary


def render_segment(
    *,
    input_path: str | Path,
    output_path: str | Path,
    start: float,
    end: float,
    video_filters: list[str] | None = None,
    audio_filters: list[str] | None = None,
    crf: int = 22,
    preset: str = "medium",
    audio_bitrate: str = "192k",
) -> dict:
    """Render a frame-accurate segment with normalized audio/video settings."""
    if end <= start:
        raise ValueError(f"Invalid segment range: start={start}, end={end}")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
    ]

    vf = ",".join(video_filters or ["null"])
    af = ",".join(audio_filters or ["anull"])

    cmd += [
        "-vf",
        vf,
        "-af",
        af,
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(output),
    ]
    run_command(cmd, f"render segment {start:.3f}-{end:.3f}")
    return validate_media(output)


def concat_videos(
    input_paths: list[str | Path],
    output_path: str | Path,
    *,
    crf: int = 22,
    preset: str = "medium",
    audio_bitrate: str = "192k",
) -> dict:
    """Concatenate videos by re-encoding to avoid stream mismatch/copy corruption."""
    if not input_paths:
        raise ValueError("No input videos were provided for concat")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    first_streams = ffprobe(input_paths[0]).get("streams", [])
    first_video = next((s for s in first_streams if s.get("codec_type") == "video"), {})
    target_width = int(first_video.get("width") or 1280)
    target_height = int(first_video.get("height") or 720)

    cmd = ["ffmpeg", "-y"]
    for path in input_paths:
        cmd.extend(["-i", str(Path(path).resolve())])

    filters = []
    concat_inputs = []
    for idx in range(len(input_paths)):
        filters.append(
            f"[{idx}:v]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,"
            "setsar=1,setpts=PTS-STARTPTS"
            f"[v{idx}]"
        )
        filters.append(f"[{idx}:a]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{idx}]")
        concat_inputs.append(f"[v{idx}][a{idx}]")

    filter_complex = ";".join(filters + [f"{''.join(concat_inputs)}concat=n={len(input_paths)}:v=1:a=1[vout][aout]"])
    cmd.extend([
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(output),
    ])
    run_command(cmd, f"concat {len(input_paths)} videos")
    summary = validate_media(output)
    expected_duration = sum(media_summary(path)["duration"] for path in input_paths)
    tolerance = max(1.0, expected_duration * 0.03)
    if abs(summary["duration"] - expected_duration) > tolerance:
        raise MediaPipelineError(
            "Concatenated video duration does not match inputs: "
            f"expected about {expected_duration:.2f}s, got {summary['duration']:.2f}s"
        )
    return summary
