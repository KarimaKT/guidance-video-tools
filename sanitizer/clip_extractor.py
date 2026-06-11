"""Intentional clip extraction built on the shared validated media pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    from .media_pipeline import render_segment, validate_media
except ImportError:
    from media_pipeline import render_segment, validate_media


@dataclass
class ClipSpec:
    id: str
    title: str
    start: float
    end: float
    category: str = ""
    description: str = ""
    manual: bool = False
    tags: list[str] = field(default_factory=list)


def safe_clip_id(value: str) -> str:
    safe = "".join(c.lower() if c.isalnum() else "-" for c in value.strip())
    safe = "-".join(part for part in safe.split("-") if part)
    return safe[:80] or "clip"


def extract_clip(
    *,
    video_path: str | Path,
    clip: ClipSpec,
    output_dir: str | Path,
    crf: int = 20,
    audio_enhance: bool = True,
) -> dict:
    """Extract a single validated clip with normalized audio/video settings."""
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"{safe_clip_id(clip.id)}.mp4"

    audio_filters = []
    if audio_enhance:
        audio_filters.extend([
            "highpass=f=80",
            "lowpass=f=12000",
            "afftdn=nf=-25",
            "loudnorm=I=-14:TP=-1:LRA=11",
        ])

    summary = render_segment(
        input_path=video_path,
        output_path=output_path,
        start=clip.start,
        end=clip.end,
        audio_filters=audio_filters,
        crf=crf,
    )
    validate_media(output_path)
    return {
        "clip": clip,
        "output_path": str(output_path),
        "summary": summary,
    }


def extract_clips(
    *,
    video_path: str | Path,
    clips: list[ClipSpec],
    output_dir: str | Path,
    crf: int = 20,
    audio_enhance: bool = True,
) -> list[dict]:
    return [
        extract_clip(
            video_path=video_path,
            clip=clip,
            output_dir=output_dir,
            crf=crf,
            audio_enhance=audio_enhance,
        )
        for clip in clips
    ]
