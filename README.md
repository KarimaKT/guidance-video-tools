# Teams Meeting Sanitizer

Professional, transcript-driven editor for cleaning up Teams/Zoom meeting recordings before publishing. Automatically detects and removes non-target speakers, admin chatter, and meeting artifacts — producing broadcast-ready video with zero manual intervention.

## What It Does

Given a recording + VTT transcript + list of speakers to keep:

1. **Analyzes** the transcript — identifies non-target speakers, admin chatter, and disturbances
2. **Detects** the video layout — side panel position, camera tiles, name bars (via pixel analysis)
3. **Cuts** disturbance zones entirely — not just mutes; removes the dead air too
4. **Masks** non-target participant tiles with black overlays
5. **Enhances** audio — noise reduction + loudness normalization

### What Gets Cut

| Type | Examples |
|------|----------|
| **Non-target speech** | Anyone not in your `keep_speakers` list |
| **Admin reactions** | "Shall we mute you?", "Am I muted?", "Can you hear me?" |
| **Post-disturbance filler** | "Amazing.", "All right.", "OK so..." after interruptions |
| **Recording logistics** | "We were sharing the recording", "Questions in the chat" |
| **Short filler** | Sub-2s utterances adjacent to non-target speech |

## Setup

### 1. Install FFmpeg

```powershell
# Windows
winget install Gyan.FFmpeg

# Refresh PATH:
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

# Verify:
ffmpeg -version
```

```bash
# macOS
brew install ffmpeg

# Linux
sudo apt install ffmpeg
```

### 2. Install Python dependencies

```bash
pip install Pillow numpy pyyaml
```

> Python 3.10+ required.

## Quick Start

### 1. Create a project config

```bash
python sanitize.py --init ai_webinar
# Creates ai_webinar_project.yaml — edit with your paths and speakers
```

### 2. Audit the edit plan

```bash
python sanitize.py my_project.yaml --audit
```

Review the output — it shows every disturbance found, what gets cut, and the final segment plan.

### 3. Render

```bash
python sanitize.py my_project.yaml
```

## Templates

Templates provide reusable defaults for different meeting types. List available templates:

```bash
python sanitize.py --templates
```

### Built-in Templates

| Template | Description |
|----------|-------------|
| `ai_webinar` | AI-focused webinar cleanup — Copilot Studio, Dataverse, Power Platform, Azure AI |

### Creating Your Own Template

Create a YAML file in `templates/`:

```yaml
# templates/my_template.yaml
description: "My custom meeting template"

settings:
  crf: 22
  audio_enhance: true
  disturbance_detection:
    admin_patterns:
      - "mute"
      - "can you hear"
    reaction_patterns:
      - "amazing"
      - "all right"
```

Then reference it in your project config:

```yaml
template: my_template
video: "recording.mp4"
vtt: "transcript.vtt"
keep_speakers: ["Alice", "Bob"]
```

## Edit Instructions (YAML Config)

Each project uses a YAML config file:

```yaml
template: ai_webinar                    # inherit template defaults

video: "path/to/recording.mp4"
vtt: "path/to/transcript.vtt"
output: "path/to/output.mp4"

keep_speakers:
  - "Presenter Name 1"
  - "Presenter Name 2"

# Optional: select specific time ranges (seconds)
segments:
  - start: 369
    end: 4017
    note: "Main presentation"
  - start: 4271
    end: 4291
    note: "Closing remarks"

# Optional: override masks for specific segments
layout_overrides:
  - segment: 1
    masks:
      - { x: 1690, y: 0, w: 230, h: 1080, label: "attendee circles" }

# Optional: override quality settings
settings:
  crf: 22
  audio_enhance: true
```

## Workflow: Iterate Until Perfect

```
┌─────────────┐     ┌───────────┐     ┌──────────┐
│ Edit YAML   │ ──► │ --audit   │ ──► │ Review   │
│ config      │     │           │     │ plan     │
└─────────────┘     └───────────┘     └──────────┘
       ▲                                    │
       │            ┌───────────┐           │
       └────────────│ Adjust    │ ◄─────────┘
                    │ segments  │
                    └───────────┘

When satisfied:
    python sanitize.py project.yaml    # renders final video
```

## CLI Reference

```
python sanitize.py <config.yaml>              # Full render
python sanitize.py <config.yaml> --audit      # Audit only (no render)
python sanitize.py <config.yaml> --verify 300 # Extract masked frame at 5:00
python sanitize.py <config.yaml> --crf 18     # Override quality
python sanitize.py <config.yaml> --no-audio-enhance
python sanitize.py --templates                 # List templates
python sanitize.py --init <template>           # Generate starter config
```

## Python API

```python
from meeting_editor import MeetingEditor, Rect

editor = MeetingEditor(
    video_path="recording.mp4",
    vtt_path="transcript.vtt",
    keep_speakers=["Alice Smith", "Bob Jones"],
    segments=[(369, 4017), (4271, 4291)],
)

editor.analyze()              # parse + detect + auto-split
editor.audit()                # review the plan
editor.verify_frame(300)      # check masks at 5:00
editor.process("output.mp4")  # render
```

## Audio Enhancement

Applied by default (`--no-audio-enhance` to disable):

| Filter | Purpose |
|--------|---------|
| `highpass=f=80` | Remove low-frequency rumble |
| `afftdn=nf=-20` | FFT-based noise reduction |
| `loudnorm=I=-14:TP=-1:LRA=11` | Broadcast-standard loudness normalization |

## CRF Quality Guide

| CRF | Quality | Use Case |
|-----|---------|----------|
| 18 | Visually lossless | Archive / master copy |
| 22 | High quality | **Default** — publishing |
| 28 | Medium | Quick preview / draft |

## Troubleshooting

**FFmpeg not found** — Refresh PATH after install:
```powershell
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
```

**Wrong speaker names** — Run `--audit` to see detected names:
```bash
python sanitize.py project.yaml --audit
```

**Masks in wrong position** — Extract test frames:
```bash
python sanitize.py project.yaml --verify 300
python sanitize.py project.yaml --verify 4275
```

**PIL/numpy not installed** — Layout auto-detection is skipped; provide masks manually via `layout_overrides`.

## License

MIT

---

## Video Creator

Also included: a **video-from-scratch generator** that creates narrated videos from YAML scripts.

### Quick Start

```bash
# Generate a video from a script
python video_creator.py examples/demo_video.yaml output.mp4
```

### What It Does

| Feature | How |
|---------|-----|
| Neural narration | Microsoft Edge TTS (free, high-quality, many voices) |
| Animated slides | Branded backgrounds, titles, bullets, icons |
| Image scenes | Ken Burns zoom effect on screenshots |
| Transitions | Fade in/out between scenes |
| Background music | Optional mix at configurable volume |

### Script Format

```yaml
title: "My Explainer Video"
voice: "en-US-AriaNeural"
voice_rate: "+10%"

scenes:
  - title: "Introduction"
    bullets: ["Point 1", "Point 2"]
    narration: "Welcome to this overview..."
    accent_color: "#4fc3f7"

  - title: "Key Feature"
    icon: "🚀"
    image: "screenshot.png"     # optional image background
    narration: "Here's how it works..."
```

### Available Voices

| Voice | Gender | Locale |
|-------|--------|--------|
| `en-US-AriaNeural` | Female | US |
| `en-US-JennyNeural` | Female | US |
| `en-US-GuyNeural` | Male | US |
| `en-US-AndrewNeural` | Male | US |
| `en-GB-SoniaNeural` | Female | UK |
| `en-AU-NatashaNeural` | Female | AU |

Full list: `python -c "import asyncio, edge_tts; asyncio.run(edge_tts.list_voices())"`

### Extra Dependency

```bash
pip install edge-tts
```
