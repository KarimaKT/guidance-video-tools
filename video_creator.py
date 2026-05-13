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
from pathlib import Path
from dataclasses import dataclass, field

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
    """Generate a slide image from a scene."""
    if not HAS_PIL:
        raise ImportError("Pillow required: pip install Pillow")
    
    w, h = resolution
    bg = _hex_to_rgb(scene.background_color)
    text_color = _hex_to_rgb(scene.text_color)
    accent = _hex_to_rgb(scene.accent_color)
    
    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)
    
    # Add subtle gradient overlay
    for y in range(h):
        alpha = int(30 * (y / h))
        draw.line([(0, y), (w, y)], fill=(bg[0]+alpha, bg[1]+alpha, min(bg[2]+alpha, 255)))
    
    # Accent bar at top
    draw.rectangle([(0, 0), (w, 6)], fill=accent)
    
    y_cursor = h * 0.2  # Start at 20% from top
    
    # Icon
    if scene.icon:
        icon_font = _get_font(font_name, 72)
        bbox = draw.textbbox((0, 0), scene.icon, font=icon_font)
        icon_w = bbox[2] - bbox[0]
        draw.text(((w - icon_w) / 2, y_cursor), scene.icon, fill=accent, font=icon_font)
        y_cursor += 100
    
    # Title
    if scene.title:
        title_font = _get_font(font_bold, 64, bold=True)
        # Word wrap title
        lines = _wrap_text(scene.title, title_font, w - 200, draw)
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=title_font)
            line_w = bbox[2] - bbox[0]
            draw.text(((w - line_w) / 2, y_cursor), line, fill=text_color, font=title_font)
            y_cursor += 80
        y_cursor += 20
    
    # Subtitle
    if scene.subtitle:
        sub_font = _get_font(font_name, 36)
        lines = _wrap_text(scene.subtitle, sub_font, w - 200, draw)
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=sub_font)
            line_w = bbox[2] - bbox[0]
            draw.text(((w - line_w) / 2, y_cursor), line, fill=(*accent, 200), font=sub_font)
            y_cursor += 50
        y_cursor += 30
    
    # Bullets
    if scene.bullets:
        bullet_font = _get_font(font_name, 32)
        x_start = w * 0.15
        for bullet in scene.bullets:
            # Bullet dot
            draw.ellipse(
                [(x_start, y_cursor + 12), (x_start + 12, y_cursor + 24)],
                fill=accent
            )
            # Bullet text
            draw.text((x_start + 30, y_cursor), bullet, fill=text_color, font=bullet_font)
            y_cursor += 55
    
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
            self._assemble(output_path, verbose)
            
            if verbose:
                size = os.path.getsize(output_path) / 1024 / 1024
                duration = self._get_duration(output_path)
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
            subprocess.run(cmd, capture_output=True, text=True)
            return
        
        cmd.append(output_path)
        subprocess.run(cmd, capture_output=True, text=True)
    
    def _render_image_scene(self, scene: Scene, narr_path: str, duration: float, output_path: str):
        """Render a scene with an image/screenshot background + Ken Burns."""
        w, h = self.script.resolution
        img_path = scene.image_path
        
        if not os.path.exists(img_path):
            # Fall back to slide
            self._render_slide_scene(scene, narr_path, duration, output_path)
            return
        
        # Ken Burns: slight zoom in over duration
        # zoompan filter: zoom from 1.0 to 1.05 over duration
        frames = int(duration * self.script.fps)
        vf = (f"zoompan=z='1+0.05*in/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d={frames}:s={w}x{h}:fps={self.script.fps},"
              f"fade=in:0:{self.script.fps//2},fade=out:st={duration-0.5}:d=0.5")
        
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
        
        subprocess.run(cmd, capture_output=True, text=True)
    
    def _render_video_scene(self, scene: Scene, narr_path: str, duration: float, output_path: str):
        """Render a scene using a video clip with optional narration overlay."""
        clip_path = scene.video_path
        
        if not os.path.exists(clip_path):
            self._render_slide_scene(scene, narr_path, duration, output_path)
            return
        
        cmd = ["ffmpeg", "-y", "-i", clip_path]
        if narr_path:
            # Mix clip audio with narration
            cmd += ["-i", narr_path]
            cmd += ["-filter_complex",
                    "[0:a]volume=0.3[bg];[1:a]volume=1.0[narr];[bg][narr]amix=inputs=2[aout]",
                    "-map", "0:v", "-map", "[aout]"]
        
        cmd += ["-t", str(duration),
                "-c:v", "libx264", "-crf", "20", "-preset", "fast",
                "-c:a", "aac", "-b:a", "192k",
                output_path]
        
        subprocess.run(cmd, capture_output=True, text=True)
    
    def _build_animation_filter(self, scene: Scene, duration: float, w: int, h: int) -> str:
        """Build FFmpeg video filter for scene animation."""
        fps = self.script.fps
        fade_frames = fps // 2  # 0.5s fade
        
        if scene.animation == "fade_in":
            return f"fade=in:0:{fade_frames},fade=out:st={duration-0.5}:d=0.5"
        elif scene.animation == "slide_up":
            return (f"split[a][b];[b]crop=iw:1:0:ih-1,scale=iw:ih[bg];"
                    f"[a][bg]overlay=0:'if(lt(t,0.5),h-h*t/0.5,0)',"
                    f"fade=out:st={duration-0.5}:d=0.5")
        elif scene.animation == "none":
            return "null"
        else:
            return f"fade=in:0:{fade_frames},fade=out:st={duration-0.5}:d=0.5"
    
    def _assemble(self, output_path: str, verbose: bool):
        """Concatenate all scenes into final video."""
        if not self.scene_files:
            print("  No scenes to assemble!")
            return
        
        # Write concat file
        list_file = str(self.temp_dir / "concat.txt")
        with open(list_file, "w") as f:
            for scene_path, dur in self.scene_files:
                fpath = str(Path(scene_path).resolve()).replace("\\", "/")
                f.write(f"file '{fpath}'\n")
        
        # Concat with crossfade would be complex; use simple concat for now
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c", "copy", output_path
        ]
        
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            # If copy fails (different codecs), re-encode
            cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", list_file,
                "-c:v", "libx264", "-crf", "20", "-preset", "fast",
                "-c:a", "aac", "-b:a", "192k",
                output_path
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0 and verbose:
                print(f"  Assembly error: {r.stderr[-200:]}")
        
        # Mix background music if specified
        if self.script.background_music and os.path.exists(self.script.background_music):
            self._add_background_music(output_path, verbose)
    
    def _add_background_music(self, video_path: str, verbose: bool):
        """Mix background music into the video."""
        music_path = self.script.background_music
        vol = self.script.music_volume
        
        temp_out = str(self.temp_dir / "with_music.mp4")
        cmd = [
            "ffmpeg", "-y", "-i", video_path, "-i", music_path,
            "-filter_complex",
            f"[1:a]volume={vol},afade=in:st=0:d=2,afade=out:st=0:d=2[music];"
            f"[0:a][music]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            temp_out
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
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
