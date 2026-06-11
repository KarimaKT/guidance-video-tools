"""
Video Creator — Generate videos from scratch with narration
============================================================
Creates professional videos from a YAML script with:
- Neural text-to-speech narration (Microsoft Edge TTS)
- Animated text slides with branded backgrounds
- Image/screenshot scenes with Ken Burns effect
- Smooth transitions between scenes
- Background music mixing
- Auto-generated captions

Usage:
    from video_creator import VideoCreator

    creator = VideoCreator("script.yaml")
    creator.generate("output.mp4")

Or via CLI:
    python video_creator.py script.yaml output.mp4
"""

import asyncio
import subprocess
import json
import os
import shutil
import math
import sys
from pathlib import Path
from dataclasses import dataclass, field

SANITIZER_DIR = Path(__file__).resolve().parents[1] / "sanitizer"
if str(SANITIZER_DIR) not in sys.path:
    sys.path.insert(0, str(SANITIZER_DIR))

from media_pipeline import concat_videos, media_summary, run_command, validate_media

try:
    import edge_tts
    HAS_TTS = True
except ImportError:
    HAS_TTS = False

try:
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    from music import fetch_music
    HAS_MUSIC = True
except ImportError:
    HAS_MUSIC = False


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class Scene:
    """A single scene in the video."""
    narration: str = ""              # Text to narrate (TTS)
    visual: str = "slide"            # "slide", "image", "video", "blank"
    title: str = ""                  # Main text on slide
    subtitle: str = ""               # Secondary text
    bullets: list = field(default_factory=list)  # Bullet points
    image_path: str = ""             # Path to image/screenshot
    video_path: str = ""             # Path to video clip
    duration: float = 0              # Override duration (0 = auto from narration)
    transition: str = "fade"         # "fade", "cut", "crossfade"
    transition_duration: float = 0.5
    background_color: str = "#1a1a2e"  # Hex color
    text_color: str = "#ffffff"
    accent_color: str = "#4fc3f7"    # For highlights
    icon: str = ""                   # Emoji or icon character
    animation: str = "fade_in"       # "fade_in", "slide_up", "typewriter", "none"


@dataclass
class VideoScript:
    """Complete video script."""
    title: str = "Untitled"
    resolution: tuple = (1920, 1080)
    fps: int = 30
    voice: str = "en-US-AriaNeural"
    voice_rate: str = "+0%"          # Speed adjustment
    voice_pitch: str = "+0Hz"
    background_music: str = ""       # Path to background music
    music_volume: float = 0.15       # Background music volume (0-1)
    music_mood: str = ""             # Auto-fetch mood (tech, corporate, ambient, etc.)
    scenes: list = field(default_factory=list)
    font: str = "Segoe UI"
    font_bold: str = "Segoe UI Bold"


# ── Script Parser ────────────────────────────────────────────────────────────

def parse_script(yaml_path: str) -> VideoScript:
    """Parse a YAML video script."""
    if not HAS_YAML:
        raise ImportError("PyYAML required: pip install pyyaml")

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    script = VideoScript()
    script.title = data.get("title", "Untitled")

    res = data.get("resolution", "1920x1080")
    if isinstance(res, str):
        w, h = res.split("x")
        script.resolution = (int(w), int(h))

    script.fps = data.get("fps", 30)
    script.voice = data.get("voice", "en-US-AriaNeural")
    script.voice_rate = data.get("voice_rate", "+0%")
    script.voice_pitch = data.get("voice_pitch", "+0Hz")
    script.background_music = data.get("background_music", "")
    script.music_volume = data.get("music_volume", 0.15)
    script.music_mood = data.get("music_mood", "")
    script.font = data.get("font", "Segoe UI")
    script.font_bold = data.get("font_bold", "Segoe UI Bold")

    for scene_data in data.get("scenes", []):
        scene = Scene()
        scene.narration = scene_data.get("narration", scene_data.get("narrate", ""))
        scene.visual = scene_data.get("visual", "slide")
        scene.title = scene_data.get("title", "")
        scene.subtitle = scene_data.get("subtitle", "")
        scene.bullets = scene_data.get("bullets", [])
        scene.image_path = scene_data.get("image", "")
        scene.video_path = scene_data.get("video", "")
        scene.duration = scene_data.get("duration", 0)
        scene.transition = scene_data.get("transition", "fade")
        scene.transition_duration = scene_data.get("transition_duration", 0.5)
        scene.background_color = scene_data.get("background", scene_data.get("background_color", "#1a1a2e"))
        scene.text_color = scene_data.get("text_color", "#ffffff")
        scene.accent_color = scene_data.get("accent_color", "#4fc3f7")
        scene.icon = scene_data.get("icon", "")
        scene.animation = scene_data.get("animation", "fade_in")
        script.scenes.append(scene)

    return script


# ── TTS Engine ───────────────────────────────────────────────────────────────

async def _generate_tts(text: str, output_path: str, voice: str,
                        rate: str = "+0%", pitch: str = "+0Hz") -> float:
    """Generate TTS audio and return duration in seconds."""
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(output_path)

    # Get duration via ffprobe
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", output_path],
        capture_output=True, text=True
    )
    return float(r.stdout.strip()) if r.stdout.strip() else 0


def generate_narration(text: str, output_path: str, voice: str = "en-US-AriaNeural",
                       rate: str = "+0%", pitch: str = "+0Hz") -> float:
    """Synchronous wrapper for TTS generation. Returns duration."""
    if not HAS_TTS:
        raise ImportError("edge-tts required: pip install edge-tts")
    return asyncio.run(_generate_tts(text, output_path, voice, rate, pitch))


# ── Visual Generators ────────────────────────────────────────────────────────

def _hex_to_rgb(hex_color: str) -> tuple:
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _find_font(name: str, size: int):
    """Find a font, falling back to defaults."""
    # Windows font paths
    font_paths = [
        f"C:/Windows/Fonts/{name.lower().replace(' ', '')}.ttf",
        f"C:/Windows/Fonts/{name.lower().replace(' ', '')}b.ttf",
        f"C:/Windows/Fonts/segoeui.ttf",
        f"C:/Windows/Fonts/arial.ttf",
    ]

    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                continue

    return ImageFont.load_default()


def _get_font(name: str, size: int, bold: bool = False):
    """Get a font by name and size."""
    if bold:
        name = name + " Bold" if "Bold" not in name else name

    # Try system font lookup
    font_map = {
        "Segoe UI": "segoeui.ttf",
        "Segoe UI Bold": "segoeuib.ttf",
        "Segoe UI Light": "segoeuil.ttf",
        "Arial": "arial.ttf",
        "Arial Bold": "arialbd.ttf",
        "Calibri": "calibri.ttf",
        "Calibri Bold": "calibrib.ttf",
    }

    filename = font_map.get(name, name.lower().replace(" ", "") + ".ttf")
    path = f"C:/Windows/Fonts/{filename}"

    if os.path.exists(path):
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            pass

    # Fallback
    for fallback in ["segoeui.ttf", "arial.ttf"]:
        path = f"C:/Windows/Fonts/{fallback}"
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                continue

    return ImageFont.load_default()


def generate_slide(scene: Scene, resolution: tuple, output_path: str,
                   font_name: str = "Segoe UI", font_bold: str = "Segoe UI Bold"):
    """Generate a professional slide image from a scene."""
    if not HAS_PIL:
        raise ImportError("Pillow required: pip install Pillow")

    w, h = resolution
    bg = _hex_to_rgb(scene.background_color)
    text_color = _hex_to_rgb(scene.text_color)
    accent = _hex_to_rgb(scene.accent_color)

    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)

    # Professional gradient background (radial-ish from center-bottom)
    for y in range(h):
        t = y / h
        # Darker at top, slightly lighter toward bottom-center
        r = int(bg[0] * (0.7 + 0.3 * t))
        g = int(bg[1] * (0.7 + 0.3 * t))
        b = int(min(bg[2] * (0.8 + 0.4 * t), 255))
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    # Subtle grid/dot pattern (adds depth)
    for gx in range(0, w, 80):
        for gy in range(0, h, 80):
            dot_alpha = 15 + int(10 * (gy / h))
            draw.ellipse([(gx-1, gy-1), (gx+1, gy+1)],
                        fill=(bg[0]+dot_alpha, bg[1]+dot_alpha, min(bg[2]+dot_alpha, 255)))

    # Accent gradient bar at top (fades from full to transparent)
    for x in range(w):
        fade = 1.0 - abs(x - w/2) / (w/2) * 0.3  # stronger in center
        bar_color = (int(accent[0]*fade), int(accent[1]*fade), int(accent[2]*fade))
        draw.line([(x, 0), (x, 4)], fill=bar_color)

    # Glowing accent circle (top-right corner, subtle)
    glow_x, glow_y = int(w * 0.85), int(h * 0.15)
    for radius in range(120, 0, -2):
        alpha = max(0, int(8 * (1 - radius/120)))
        glow_color = (min(bg[0]+alpha, 255), min(bg[1]+alpha, 255), min(bg[2]+int(alpha*2), 255))
        draw.ellipse([(glow_x-radius, glow_y-radius), (glow_x+radius, glow_y+radius)],
                    outline=glow_color)

    y_cursor = h * 0.18  # Start at 18% from top

    # Icon (with subtle glow behind it)
    if scene.icon:
        icon_font = _get_font(font_name, 80)
        bbox = draw.textbbox((0, 0), scene.icon, font=icon_font)
        icon_w = bbox[2] - bbox[0]
        ix = (w - icon_w) / 2
        # Glow circle behind icon
        for r in range(50, 0, -1):
            alpha = int(3 * (1 - r/50))
            gc = (min(accent[0]//4+alpha, 255), min(accent[1]//4+alpha, 255), min(accent[2]//4+alpha, 255))
            draw.ellipse([(ix+icon_w//2-r, y_cursor+40-r), (ix+icon_w//2+r, y_cursor+40+r)], outline=gc)
        draw.text((ix, y_cursor), scene.icon, fill=accent, font=icon_font)
        y_cursor += 120

    # Title (larger, with accent underline)
    if scene.title:
        title_font = _get_font(font_bold, 62, bold=True)
        lines = _wrap_text(scene.title, title_font, w - 240, draw)
        title_start_y = y_cursor
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=title_font)
            line_w = bbox[2] - bbox[0]
            draw.text(((w - line_w) / 2, y_cursor), line, fill=text_color, font=title_font)
            y_cursor += 78
        # Accent underline below title
        line_y = int(y_cursor + 8)
        line_w = min(200, w // 4)
        draw.rectangle([(w//2 - line_w//2, line_y), (w//2 + line_w//2, line_y + 3)], fill=accent)
        y_cursor += 35

    # Subtitle
    if scene.subtitle:
        sub_font = _get_font(font_name, 32)
        lines = _wrap_text(scene.subtitle, sub_font, w - 240, draw)
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=sub_font)
            line_w = bbox[2] - bbox[0]
            # Slightly transparent accent color for subtitle
            sub_color = (
                int(accent[0]*0.8 + text_color[0]*0.2),
                int(accent[1]*0.8 + text_color[1]*0.2),
                int(accent[2]*0.8 + text_color[2]*0.2),
            )
            draw.text(((w - line_w) / 2, y_cursor), line, fill=sub_color, font=sub_font)
            y_cursor += 45
        y_cursor += 25

    # Bullets (with accent dots and proper spacing)
    if scene.bullets:
        bullet_font = _get_font(font_name, 30)
        x_start = int(w * 0.15)
        max_bullet_w = int(w * 0.7)
        for bullet in scene.bullets:
            # Accent bullet marker (rounded square)
            bx = x_start
            by = int(y_cursor + 10)
            draw.rounded_rectangle([(bx, by), (bx+10, by+10)], radius=3, fill=accent)
            # Bullet text (with wrapping)
            bullet_lines = _wrap_text(bullet, bullet_font, max_bullet_w, draw)
            for bl in bullet_lines:
                draw.text((x_start + 25, y_cursor), bl, fill=text_color, font=bullet_font)
                y_cursor += 42
            y_cursor += 10

    # Bottom accent line
    draw.rectangle([(0, h-3), (w, h)], fill=(accent[0]//3, accent[1]//3, accent[2]//3))

    img.save(output_path, quality=95)
    return output_path


def _wrap_text(text: str, font, max_width: int, draw) -> list[str]:
    """Wrap text to fit within max_width."""
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)
    return lines


# ── Video Assembly ───────────────────────────────────────────────────────────

class VideoCreator:
    """Generates complete videos from YAML scripts."""

    def __init__(self, script_path: str = None, script: VideoScript = None):
        if script:
            self.script = script
        elif script_path:
            self.script = parse_script(script_path)
        else:
            raise ValueError("Provide either script_path or script")

        self.temp_dir = None
        self.scene_files = []  # [(video_path, duration), ...]

    def generate(self, output_path: str, verbose: bool = True):
        """Generate the complete video."""
        out_dir = Path(output_path).parent
        out_dir.mkdir(parents=True, exist_ok=True)

        import uuid
        self.temp_dir = out_dir / f"_vid_temp_{uuid.uuid4().hex[:8]}"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            if verbose:
                print("=" * 60)
                print(f"GENERATING VIDEO: {self.script.title}")
                print("=" * 60)
                print(f"  Resolution: {self.script.resolution[0]}x{self.script.resolution[1]}")
                print(f"  Voice: {self.script.voice}")
                print(f"  Scenes: {len(self.script.scenes)}")

            # Step 1: Generate narration for all scenes
            if verbose:
                print("\n── Generating narration ──")
            narration_files = self._generate_all_narration(verbose)

            # Step 2: Generate visuals for all scenes
            if verbose:
                print("\n── Generating visuals ──")
            self._generate_all_scenes(narration_files, verbose)

            # Step 3: Concatenate all scenes
            if verbose:
                print("\n── Assembling video ──")

            # Auto-fetch background music if mood is set and no explicit path
            if not self.script.background_music and self.script.music_mood and HAS_MUSIC:
                total_dur = sum(d for _, d in self.scene_files)
                if verbose:
                    print(f"  ♪ Auto-fetching {self.script.music_mood} background music...")
                track = fetch_music(
                    mood=self.script.music_mood,
                    duration_range=(max(30, total_dur - 30), total_dur + 60),
                    verbose=verbose,
                )
                if track:
                    self.script.background_music = track

            self._assemble(output_path, verbose)

            if verbose:
                summary = validate_media(output_path)
                size = os.path.getsize(output_path) / 1024 / 1024
                duration = summary["duration"]
                print(f"\n  ✅ DONE: {output_path}")
                print(f"     Duration: {duration:.1f}s | Size: {size:.1f} MB")

            return output_path

        finally:
            # Cleanup
            if self.temp_dir and self.temp_dir.exists():
                shutil.rmtree(str(self.temp_dir), ignore_errors=True)

    def _generate_all_narration(self, verbose: bool) -> list[str]:
        """Generate TTS audio for all scenes. Returns list of audio file paths."""
        narration_files = []

        for i, scene in enumerate(self.script.scenes):
            if scene.narration:
                audio_path = str(self.temp_dir / f"narr_{i:02d}.mp3")
                dur = generate_narration(
                    scene.narration, audio_path,
                    voice=self.script.voice,
                    rate=self.script.voice_rate,
                    pitch=self.script.voice_pitch,
                )
                narration_files.append(audio_path)
                if verbose:
                    print(f"  Scene {i+1}: {dur:.1f}s — \"{scene.narration[:50]}...\"")
            else:
                narration_files.append(None)
                if verbose:
                    print(f"  Scene {i+1}: (no narration)")

        return narration_files

    def _generate_all_scenes(self, narration_files: list, verbose: bool):
        """Generate video for each scene (visual + audio)."""
        self.scene_files = []

        for i, scene in enumerate(self.script.scenes):
            scene_path = str(self.temp_dir / f"scene_{i:02d}.mp4")
            narr_path = narration_files[i]

            # Determine duration
            if scene.duration > 0:
                duration = scene.duration
            elif scene.visual == "video" and scene.video_path:
                duration = self._get_duration(scene.video_path)
            elif narr_path:
                duration = self._get_duration(narr_path) + 0.5  # padding
            else:
                duration = 3.0  # default

            # Generate visual
            if scene.visual == "slide":
                self._render_slide_scene(scene, narr_path, duration, scene_path)
            elif scene.visual == "image" and scene.image_path:
                self._render_image_scene(scene, narr_path, duration, scene_path)
            elif scene.visual == "video" and scene.video_path:
                self._render_video_scene(scene, narr_path, duration, scene_path)
            else:
                self._render_slide_scene(scene, narr_path, duration, scene_path)

            self.scene_files.append((scene_path, duration))

            if verbose:
                size = os.path.getsize(scene_path) / 1024 / 1024 if os.path.exists(scene_path) else 0
                print(f"  Scene {i+1}: {duration:.1f}s ({size:.1f} MB) — {scene.visual}: \"{scene.title[:40]}\"")

    def _render_slide_scene(self, scene: Scene, narr_path: str, duration: float, output_path: str):
        """Render a text slide scene with optional narration."""
        w, h = self.script.resolution

        # Generate the slide image
        slide_path = str(self.temp_dir / f"_slide_{Path(output_path).stem}.png")
        generate_slide(scene, self.script.resolution, slide_path,
                      self.script.font, self.script.font_bold)

        # Build FFmpeg command: image → video with animation
        vf = self._build_animation_filter(scene, duration, w, h)

        cmd = ["ffmpeg", "-y", "-loop", "1", "-i", slide_path]

        if narr_path:
            cmd += ["-i", narr_path]

        cmd += ["-vf", vf]
        cmd += ["-t", str(duration)]
        cmd += ["-c:v", "libx264", "-crf", "20", "-preset", "fast",
                "-pix_fmt", "yuv420p"]

        if narr_path:
            cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
        else:
            # Generate silent audio track
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
            cmd = self._insert_before(cmd, "-t", ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])
            # Simpler approach: just add silent audio
            cmd = [
                "ffmpeg", "-y", "-loop", "1", "-i", slide_path,
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-vf", vf,
                "-t", str(duration),
                "-c:v", "libx264", "-crf", "20", "-preset", "fast",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-shortest",
                output_path
            ]
            run_command(cmd, f"render silent slide scene {output_path}")
            validate_media(output_path)
            return

        cmd.append(output_path)
        run_command(cmd, f"render slide scene {output_path}")
        validate_media(output_path)

    def _render_image_scene(self, scene: Scene, narr_path: str, duration: float, output_path: str):
        """Render a scene with an image/screenshot background + Ken Burns."""
        w, h = self.script.resolution
        img_path = scene.image_path

        if not os.path.exists(img_path):
            # Fall back to slide
            self._render_slide_scene(scene, narr_path, duration, output_path)
            return

        # Ken Burns: slight zoom in over duration. Keep it clean; scene cuts are
        # handled by assembly, not per-scene fade filters.
        frames = int(duration * self.script.fps)
        vf = (f"zoompan=z='1+0.05*in/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s={w}x{h}:fps={self.script.fps},format=yuv420p")

        cmd = ["ffmpeg", "-y", "-i", img_path]
        if narr_path:
            cmd += ["-i", narr_path]
        else:
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]

        cmd += ["-vf", vf, "-t", str(duration),
                "-c:v", "libx264", "-crf", "20", "-preset", "fast",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-shortest",
                output_path]

        run_command(cmd, f"render image scene {output_path}")
        validate_media(output_path)

    def _render_video_scene(self, scene: Scene, narr_path: str, duration: float, output_path: str):
        """Render a scene using a video clip with optional narration overlay."""
        clip_path = scene.video_path

        if not os.path.exists(clip_path):
            self._render_slide_scene(scene, narr_path, duration, output_path)
            return

        w, h = self.script.resolution
        video_filter = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={self.script.fps},setpts=PTS-STARTPTS"
        has_clip_audio = media_summary(clip_path)["audio_streams"] > 0
        cmd = ["ffmpeg", "-y", "-i", clip_path]
        if narr_path:
            cmd += ["-i", narr_path]
            if has_clip_audio:
                cmd += ["-filter_complex",
                        f"[0:v]{video_filter}[vout];[0:a]volume=0.3,asetpts=PTS-STARTPTS[bg];[1:a]volume=1.0,asetpts=PTS-STARTPTS[narr];[bg][narr]amix=inputs=2:duration=first[aout]",
                        "-map", "[vout]", "-map", "[aout]"]
            else:
                cmd += ["-filter_complex",
                        f"[0:v]{video_filter}[vout];[1:a]volume=1.0,asetpts=PTS-STARTPTS[aout]",
                        "-map", "[vout]", "-map", "[aout]"]
        else:
            if has_clip_audio:
                cmd += ["-vf", video_filter, "-af", "asetpts=PTS-STARTPTS"]
            else:
                cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                        "-filter_complex", f"[0:v]{video_filter}[vout]",
                        "-map", "[vout]", "-map", "1:a"]

        cmd += ["-t", str(duration),
                "-c:v", "libx264", "-crf", "20", "-preset", "fast",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                output_path]

        run_command(cmd, f"render video scene {output_path}")
        validate_media(output_path)

    def _build_animation_filter(self, scene: Scene, duration: float, w: int, h: int) -> str:
        """Build FFmpeg video filter for scene animation."""
        # Professional demos should feel like intentional slide cuts, not flashy
        # per-scene fades. Keep legacy animation names accepted in YAML, but do
        # not translate them into fade/overlay filters by default.
        return "null"

    def _assemble(self, output_path: str, verbose: bool):
        """Concatenate all scenes into final video."""
        if not self.scene_files:
            print("  No scenes to assemble!")
            return

        scene_paths = [scene_path for scene_path, _ in self.scene_files]
        concat_videos(scene_paths, output_path, crf=20, preset="fast")

        # Mix background music if specified
        if self.script.background_music and os.path.exists(self.script.background_music):
            self._add_background_music(output_path, verbose)

    def _add_background_music(self, video_path: str, verbose: bool):
        """Mix background music into the video."""
        music_path = self.script.background_music
        vol = self.script.music_volume

        temp_out = str(self.temp_dir / "with_music.mp4")
        vid_dur = self._get_duration(video_path)
        fade_out_start = max(0, vid_dur - 3)
        cmd = [
            "ffmpeg", "-y", "-i", video_path, "-i", music_path,
            "-filter_complex",
            f"[1:a]volume={vol},afade=in:st=0:d=2,afade=out:st={fade_out_start}:d=3[music];"
            f"[0:a][music]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            temp_out
        ]
        run_command(cmd, f"mix background music into {video_path}")
        validate_media(temp_out)
        shutil.move(temp_out, video_path)
        if verbose:
            print(f"  + Background music mixed")

    @staticmethod
    def _insert_before(cmd: list, marker: str, items: list) -> list:
        """Insert items before a marker in a command list."""
        try:
            idx = cmd.index(marker)
            return cmd[:idx] + items + cmd[idx:]
        except ValueError:
            return cmd + items

    @staticmethod
    def _get_duration(path: str) -> float:
        """Get duration of audio/video file."""
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True
        )
        try:
            return float(r.stdout.strip())
        except (ValueError, TypeError):
            return 0


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python video_creator.py <script.yaml> [output.mp4]")
        print("\nGenerates a video from a YAML script with TTS narration.")
        sys.exit(1)

    script_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "output.mp4"

    creator = VideoCreator(script_path)
    creator.generate(output_path)
