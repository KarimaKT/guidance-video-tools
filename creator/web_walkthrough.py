from __future__ import annotations

import re
from pathlib import Path

import yaml

from media_pipeline import run_command, validate_media
from video_creator import Scene, VideoCreator, VideoScript


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:48] or "step"


def _apply_action(page, url: str, action: str) -> None:
    action = action.strip()
    lower = action.lower()
    if lower == "goto":
        page.goto(url, wait_until="networkidle", timeout=60_000)
    elif lower.startswith("scroll:"):
        target = action.split(":", 1)[1].strip()
        try:
            fraction = float(target)
            page.evaluate("(f) => window.scrollTo({ top: document.body.scrollHeight * f, behavior: 'instant' })", fraction)
        except ValueError:
            page.evaluate("(y) => window.scrollTo({ top: Number(y), behavior: 'instant' })", target)
    elif lower.startswith("click:"):
        text = action.split(":", 1)[1].strip()
        page.get_by_text(text, exact=False).first.click(timeout=10_000)
    elif lower in {"wait", "pause"}:
        pass
    else:
        raise ValueError(f"Unsupported walkthrough action: {action}")
    page.wait_for_timeout(900)


def _format_step_marker(index: int) -> str:
    return f"{index:02d}"


def _annotate_screenshot(path: Path, *, label: str, index: int, total: int, marker: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, _ = img.size

    def font(size: int, bold: bool = False):
        candidates = [
            "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        ]
        for candidate in candidates:
            if Path(candidate).exists():
                return ImageFont.truetype(candidate, size)
        return ImageFont.load_default()

    title_font = font(34, bold=True)
    meta_font = font(22)
    label = re.sub(r"\s+", " ", label).strip()
    max_label = 54
    if len(label) > max_label:
        label = label[: max_label - 1].rstrip() + "..."

    x, y = 28, 28
    box_w, box_h = min(760, w - 56), 104
    draw.rounded_rectangle((x, y, x + box_w, y + box_h), radius=22, fill=(15, 23, 42, 224))
    draw.rounded_rectangle((x + 16, y + 18, x + 118, y + 52), radius=17, fill=(14, 165, 233, 255))
    draw.text((x + 34, y + 21), marker, fill=(255, 255, 255, 255), font=meta_font)
    draw.text((x + 138, y + 18), label, fill=(255, 255, 255, 255), font=title_font)
    draw.text((x + 138, y + 62), f"Step {index} of {total}", fill=(191, 219, 254, 255), font=meta_font)

    Image.alpha_composite(img, overlay).convert("RGB").save(path, quality=94)


def _write_plan(path: Path, title: str, url: str, max_screen_seconds: float, steps: list[dict], screenshots: list[Path]) -> None:
    data = {
        "title": title,
        "url": url,
        "max_screen_seconds": max_screen_seconds,
        "steps": [
            {
                **step,
                "screenshot": str(screenshot),
            }
            for step, screenshot in zip(steps, screenshots)
        ],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="utf-8")


def _write_description(path: Path, title: str, url: str, video_path: Path, steps: list[dict]) -> None:
    data = {
        "title": title,
        "url": url,
        "raw_video": str(video_path),
        "purpose": "Silent guided walkthrough footage for a later narrated demo assembly step.",
        "usage": [
            "Use this video as visual proof inside a Demo Video Creator scene.",
            "Keep narration in the surrounding script, not in the raw walkthrough asset.",
            "Use the step labels and narration notes below to write the composite demo talk track.",
        ],
        "steps": [
            {
                "label": step["label"],
                "action": step["action"],
                "narration_note": step.get("narration", ""),
            }
            for step in steps
        ],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="utf-8")


def capture_web_walkthrough(
    *,
    url: str,
    steps: list[dict],
    output_dir: str | Path,
    output_path: str | Path,
    title: str = "Web walkthrough",
    voice: str = "en-US-AriaNeural",
    voice_rate: str = "+10%",
    max_screen_seconds: float = 4.0,
    width: int = 1600,
    height: int = 1000,
    narrate: bool = True,
) -> dict:
    if not steps:
        raise ValueError("At least one walkthrough step is required.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    screenshot_dir = output_dir / "screens"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(output_path)

    screenshots: list[Path] = []
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        try:
            for idx, step in enumerate(steps, start=1):
                _apply_action(page, url, step["action"])
                screenshot = screenshot_dir / f"{idx:02d}-{_safe_slug(step['label'])}.png"
                page.screenshot(path=str(screenshot), full_page=False)
                _annotate_screenshot(
                    screenshot,
                    label=step["label"],
                    index=idx,
                    total=len(steps),
                    marker=_format_step_marker(idx),
                )
                screenshots.append(screenshot)
        finally:
            browser.close()

    script = VideoScript()
    script.title = title
    script.resolution = (width, height)
    script.fps = 25
    script.voice = voice
    script.voice_rate = voice_rate
    script.music_volume = 0

    for step, screenshot in zip(steps, screenshots):
        scene = Scene()
        scene.title = step["label"]
        scene.narration = step["narration"] if narrate else ""
        scene.visual = "image"
        scene.image_path = str(screenshot)
        scene.duration = min(max_screen_seconds, float(step.get("duration") or max_screen_seconds))
        scene.animation = "none"
        script.scenes.append(scene)

    render_path = output_path
    if not narrate:
        render_path = output_path.with_name(f"{output_path.stem}-with-silent-track{output_path.suffix}")

    VideoCreator(script=script).generate(str(render_path), verbose=False)
    if narrate:
        summary = validate_media(output_path)
    else:
        run_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(render_path),
                "-map",
                "0:v:0",
                "-c:v",
                "copy",
                "-an",
                str(output_path),
            ],
            f"strip audio from silent walkthrough {output_path}",
        )
        render_path.unlink(missing_ok=True)
        summary = validate_media(output_path, require_audio=False)

    plan_path = output_path.with_suffix(".walkthrough.yaml")
    description_path = output_path.with_suffix(".description.yaml")
    _write_plan(plan_path, title, url, max_screen_seconds, steps, screenshots)
    _write_description(description_path, title, url, output_path, steps)

    return {
        "video": str(output_path),
        "plan": str(plan_path),
        "description": str(description_path),
        "screenshots": [str(path) for path in screenshots],
        "summary": summary,
    }
