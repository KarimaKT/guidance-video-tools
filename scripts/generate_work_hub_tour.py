from __future__ import annotations

import asyncio
import math
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import edge_tts
from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "examples" / "web_walkthroughs" / "work-hub"
STAGING_DIR = OUT_DIR / "_staging"
SCREEN_DIR = STAGING_DIR / "screens"
SEGMENT_DIR = STAGING_DIR / "segments"
BASE_URLS = ("http://localhost:3100", "http://localhost:3000")
WIDTH = 1600
HEIGHT = 900
FPS = 30
SCREEN_SECONDS = 2.25


NARRATION = (
    "Introducing Work Hub: a Clawpilot dashboard for meetings, tasks, Connect evidence, and focused execution. "
    "It exists for the moments when the work is spread across Teams, Outlook, OneDrive, Planner, SharePoint, notes, and chat, but the person doing the work still needs one clear next move. "
    "The home page brings meeting load, open tasks, new recaps, app launch buttons, and priority signals into one place, while still linking back to the original Microsoft 365 artifacts. "
    "Meeting views turn recaps into searchable context, tasks, files, stakeholders, and follow-up queues, so yesterday's conversation becomes today's usable work surface. "
    "Connect Hub collates impact. Customers, slides, artifacts, kudos, talks, niches, verified claims, and drafts stay connected, so the user can summarize outcomes without rebuilding the evidence trail from memory. "
    "Focus Mode protects the actual work session. An intelligent assistant helps prioritize the next concrete item, organizes the context around it, and keeps the screen intentionally minimal so executive function is preserved for the work itself. "
    "The braindump area is a pressure valve: side thoughts, follow-ups, and distractions can be captured without derailing the focused task. "
    "The loop is simple: discover what matters, decide what deserves attention, focus without losing context, capture side thoughts safely, and reuse the evidence when impact needs to be explained."
)


def run(cmd: list[str], description: str) -> None:
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"{description} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


def font(size: int, bold: bool = False):
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def resolve_base_url() -> str:
    for url in BASE_URLS:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return url
        except OSError:
            continue
    raise RuntimeError(f"Work Hub is not reachable at any configured URL: {', '.join(BASE_URLS)}")


def wrap_text(draw: ImageDraw.ImageDraw, text: str, text_font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join([*current, word])
        if draw.textbbox((0, 0), candidate, font=text_font)[2] <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def make_slide(path: Path, title: str, subtitle: str, cards: list[tuple[str, str]]) -> None:
    img = Image.new("RGB", (WIDTH, HEIGHT), "#0f172a")
    draw = ImageDraw.Draw(img)
    for x in range(WIDTH):
        shade = int(18 + 24 * x / WIDTH)
        draw.line((x, 0, x, HEIGHT), fill=(15, 23, 42 + shade // 3))

    title_font = font(62, True)
    subtitle_font = font(30)
    card_title_font = font(26, True)
    card_body_font = font(22)

    draw.rounded_rectangle((58, 56, 334, 104), radius=24, fill="#38bdf8")
    draw.text((82, 65), "WORK HUB TOUR", fill="white", font=font(22, True))
    draw.text((58, 160), title, fill="white", font=title_font)
    y = 250
    for line in wrap_text(draw, subtitle, subtitle_font, 1350):
        draw.text((62, y), line, fill="#cbd5e1", font=subtitle_font)
        y += 42

    card_w = 700
    card_h = 128
    x_positions = [62, 820]
    y_positions = [420, 590]
    for idx, (heading, body) in enumerate(cards[:4]):
        x = x_positions[idx % 2]
        cy = y_positions[idx // 2]
        draw.rounded_rectangle((x, cy, x + card_w, cy + card_h), radius=28, fill="#111827", outline="#334155", width=2)
        draw.text((x + 28, cy + 22), heading, fill="#7dd3fc", font=card_title_font)
        text_y = cy + 62
        for line in wrap_text(draw, body, card_body_font, card_w - 56)[:2]:
            draw.text((x + 28, text_y), line, fill="#e5e7eb", font=card_body_font)
            text_y += 30
    img.save(path, quality=95)


def annotate(path: Path, label: str, index: int, total: int) -> None:
    img = Image.open(path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    marker = f"{math.floor((index - 1) * SCREEN_SECONDS // 60):02d}:{math.floor((index - 1) * SCREEN_SECONDS % 60):02d}"
    x, y = 24, 24
    box_w, box_h = 720, 92
    draw.rounded_rectangle((x, y, x + box_w, y + box_h), radius=22, fill=(15, 23, 42, 226))
    draw.rounded_rectangle((x + 16, y + 18, x + 112, y + 52), radius=17, fill=(14, 165, 233, 255))
    draw.text((x + 34, y + 22), marker, fill="white", font=font(20, True))
    safe_label = re.sub(r"\s+", " ", label).strip()[:58]
    draw.text((x + 132, y + 16), safe_label, fill="white", font=font(28, True))
    draw.text((x + 132, y + 56), f"Beat {index} of {total}", fill="#bfdbfe", font=font(18))
    Image.alpha_composite(img, overlay).convert("RGB").save(path, quality=94)


def click_text(page, text: str, *, exact: bool = False) -> None:
    locator = page.get_by_text(text, exact=exact).first
    locator.click(timeout=10_000)
    page.wait_for_timeout(900)


def scroll_to(page, fraction: float) -> None:
    page.evaluate("(f) => window.scrollTo({ top: document.body.scrollHeight * f, behavior: 'instant' })", fraction)
    page.wait_for_timeout(550)


def capture_live_app() -> list[Path]:
    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
    SCREEN_DIR.mkdir(parents=True)
    SEGMENT_DIR.mkdir(parents=True)

    screens: list[Path] = []

    def add_static(title: str, subtitle: str, cards: list[tuple[str, str]]) -> None:
        path = SCREEN_DIR / f"{len(screens) + 1:02d}-slide.png"
        make_slide(path, title, subtitle, cards)
        screens.append(path)

    add_static(
        "Work Hub in under two minutes",
        "A focused work surface for meetings, Connect evidence, created apps, and protected execution time.",
        [
            ("One work surface", "Meetings, tasks, files, stakeholders, and app launchers stay close together."),
            ("Connect evidence", "Impact signals are collated, verified, and kept ready for summary."),
            ("Focus Mode", "The assistant prioritizes the next concrete item and keeps the session uncluttered."),
            ("Braindump", "Side thoughts are captured safely without breaking the main work thread."),
        ],
    )

    base_url = resolve_base_url()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)

        def shot(label: str) -> None:
            path = SCREEN_DIR / f"{len(screens) + 1:02d}-{re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')[:42]}.png"
            page.screenshot(path=str(path), full_page=False)
            screens.append(path)

        try:
            page.goto(base_url, wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(1200)
            shot("Dashboard daily operating picture")
            scroll_to(page, 0.34)
            shot("Created apps launcher")
            scroll_to(page, 0.62)
            shot("Reuse M365, add structured intelligence")

            page.goto(base_url, wait_until="networkidle", timeout=60_000)
            click_text(page, "New Recaps")
            shot("Meeting recaps become searchable work")
            scroll_to(page, 0.35)
            shot("Meeting cards carry links and summaries")
            click_text(page, "High Relevance")
            shot("High relevance filters the noisy backlog")
            click_text(page, "Action Required")
            shot("Action-required meetings surface follow-up")
            click_text(page, "Shared Files")
            shot("Shared files stay close to meetings")
            click_text(page, "Tasks")
            shot("Tasks turn recaps into execution")
            click_text(page, "All Projects")
            shot("Projects organize ongoing work")
            click_text(page, "Customer Projects")
            shot("Customer projects separate field work")
            click_text(page, "Stakeholders")
            shot("Stakeholders keep relationship context")
            click_text(page, "Resource Library")
            shot("Resources preserve reusable links")

            click_text(page, "Workspace")
            shot("Connect workspace starts with readiness")
            scroll_to(page, 0.25)
            shot("Connect readiness checklist")
            scroll_to(page, 0.55)
            shot("Kudos customers and content pipeline")
            click_text(page, "Customer Evidence")
            shot("Customer evidence by engagement")
            scroll_to(page, 0.38)
            shot("Use cases and customer proof")
            click_text(page, "Impact Log")
            shot("Impact log connects work to outcomes")
            click_text(page, "Kudos")
            shot("Kudos preserves recognition signals")
            click_text(page, "Content & Talks")
            shot("Talks and content capture reach")
            click_text(page, "Workspace")
            click_text(page, "Slides & Artifacts")
            shot("Slides and artifacts stay linked")
            click_text(page, "Evidence")
            shot("Verified claims and source types")
            scroll_to(page, 0.45)
            shot("Evidence provenance before final text")
            click_text(page, "Promotion Draft")
            shot("Promotion draft assembled from evidence")

            click_text(page, "People to Connect With")
            shot("People to connect with")
            click_text(page, "Product Planning")
            shot("Product planning tracks app priorities")
            click_text(page, "Questions")
            shot("Questions bar keeps blockers explicit")

            click_text(page, "Focus Mode")
            shot("Focus mode one-click start")
            try:
                click_text(page, "Go", exact=True)
                page.wait_for_timeout(1800)
                shot("Focus mode chooses the next concrete task")
                shot("Minimal execution screen")
                click_text(page, "Quick capture")
                shot("Quick capture saves digressions")
            except PlaywrightTimeoutError:
                shot("Focus mode setup captured")
        finally:
            browser.close()

    add_static(
        "Discover. Decide. Focus. Reuse.",
        "Work Hub turns scattered M365 signals and local artifacts into a repeatable operating loop for high-judgment work.",
        [
            ("Discover", "Meeting recaps, files, people, and questions in one place."),
            ("Decide", "Connect evidence and promotion material connected to sources."),
            ("Focus", "A minimal task-first flow with quick capture."),
            ("Reuse", "App launchers, resources, and structured SQLite-backed history."),
        ],
    )

    for idx, screen in enumerate(screens, start=1):
        annotate(screen, screen.stem.split("-", 1)[-1].replace("-", " ").title(), idx, len(screens))

    return screens


async def make_narration(path: Path) -> None:
    communicate = edge_tts.Communicate(NARRATION, "en-US-AriaNeural", rate="+18%")
    await communicate.save(str(path))


def media_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip() or 0)


def build_video(screens: list[Path]) -> Path:
    audio_path = STAGING_DIR / "work-hub-tour-narration.mp3"
    asyncio.run(make_narration(audio_path))
    audio_duration = media_duration(audio_path)
    per_screen = max(1.85, min(2.35, (audio_duration + 1.5) / len(screens)))
    video_duration = per_screen * len(screens)

    if video_duration < audio_duration + 0.5:
        per_screen = (audio_duration + 1.0) / len(screens)

    concat_file = SEGMENT_DIR / "segments.txt"
    with concat_file.open("w", encoding="utf-8") as f:
        for idx, screen in enumerate(screens, start=1):
            segment = SEGMENT_DIR / f"segment-{idx:02d}.mp4"
            vf = (
                f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
                f"format=yuv420p,fps={FPS}"
            )
            run(
                [
                    "ffmpeg",
                    "-y",
                    "-loop",
                    "1",
                    "-i",
                    str(screen),
                    "-t",
                    f"{per_screen:.3f}",
                    "-vf",
                    vf,
                    "-c:v",
                    "libx264",
                    "-crf",
                    "20",
                    "-preset",
                    "veryfast",
                    "-an",
                    str(segment),
                ],
                f"render segment {idx}",
            )
            f.write(f"file '{segment.as_posix()}'\n")

    silent_video = STAGING_DIR / "work-hub-tour-silent.mp4"
    run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(silent_video)],
        "concat slideshow",
    )

    staged_output = STAGING_DIR / "work-hub-connect-focus-tour.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(silent_video),
            "-i",
            str(audio_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(staged_output),
        ],
        "mux narrated video",
    )

    duration = media_duration(staged_output)
    if duration > 120:
        raise RuntimeError(f"Generated video is too long: {duration:.1f}s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUT_DIR / "work-hub-connect-focus-tour.mp4"
    shutil.copy2(staged_output, output)
    print(f"Generated {output}")
    print(f"Duration: {duration:.1f}s")
    print(f"Screens: {len(screens)} at ~{per_screen:.2f}s each")
    return output


def main() -> None:
    screens = capture_live_app()
    build_video(screens)


if __name__ == "__main__":
    sys.exit(main())
