# 🎬 CAT Video Tools

**Power CAT Video Production Suite** — Two professional tools for creating and cleaning video content.

| Tool | What You Provide | What It Does |
|------|-----------------|--------------|
| **✂️ Meeting Sanitizer** | Recording + transcript + target speakers | Removes all non-target audio, masks participants, enhances audio |
| **🎥 Video Creator** | Topic/script + voice preference + duration | Generates narrated videos with professional slides from scratch |

## Quick Start

```bash
git clone https://github.com/KarimaKT/cat-video-tools
cd cat-video-tools
pip install -r requirements.txt

# Launch web UI (recommended)
streamlit run app.py

# Or use CLI
python sanitizer/sanitize.py --help
python creator/video_creator.py --help
```

### Prerequisites

- **Python 3.10+**
- **FFmpeg** — `winget install Gyan.FFmpeg` (Windows) or `brew install ffmpeg` (macOS)
- After installing FFmpeg on Windows, refresh PATH:
  ```powershell
  $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
  ```

---

## ✂️ Meeting Sanitizer

**You provide:** A recording, a transcript, and which speakers to keep.  
**I do the rest.** No manual editing needed.

### What Gets Removed Automatically

| Type | Examples |
|------|----------|
| Non-target speech | Anyone not in your speaker list |
| Admin reactions | "Shall we mute you?", "Am I muted?", "Can you hear me?" |
| Post-disturbance filler | "Amazing.", "All right.", "OK so..." after interruptions |
| Recording logistics | "We were sharing the recording", "Questions in the chat" |
| Visual artifacts | Non-target participant tiles, name bars |

### Usage

**Web UI:**
```bash
streamlit run app.py  # then select "Meeting Sanitizer"
```

**CLI:**
```bash
# Initialize from template
python sanitizer/sanitize.py --init ai_webinar

# Audit (review edit plan without rendering)
python sanitizer/sanitize.py my_project.yaml --audit

# Render
python sanitizer/sanitize.py my_project.yaml
```

**Python API:**
```python
from meeting_editor import MeetingEditor

editor = MeetingEditor("recording.mp4", "transcript.vtt", ["Alice", "Bob"])
editor.analyze()
editor.audit()
editor.process("output.mp4")
```

---

## 🎥 Video Creator

**You provide:** A topic, key points, duration, and voice preference.  
**I do the rest.** Professional narrated video generated automatically.

### What Gets Generated

| Element | How |
|---------|-----|
| Professional slides | Gradient backgrounds, typography, icons, bullet points |
| Neural narration | Microsoft Edge TTS — natural voices, many languages |
| Transitions | Fade in/out between scenes |
| Background music | Auto-fetched from Pixabay (optional, royalty-free) |
| Final video | Assembled MP4 ready to upload |

### Usage

**Web UI:**
```bash
streamlit run app.py  # then select "Video Creator"
```

**CLI:**
```bash
python creator/video_creator.py script.yaml output.mp4
```

**YAML script format:**
```yaml
title: "My Explainer"
voice: "en-US-AriaNeural"
voice_rate: "+10%"

scenes:
  - title: "Introduction"
    narration: "Welcome to this overview of..."
    bullets: ["Point one", "Point two"]
    accent_color: "#4fc3f7"
```

### Available Voices

| Voice | Gender | Style |
|-------|--------|-------|
| `en-US-AriaNeural` | Female | Conversational |
| `en-US-JennyNeural` | Female | Professional |
| `en-US-GuyNeural` | Male | Casual |
| `en-US-AndrewNeural` | Male | Warm |
| `en-GB-SoniaNeural` | Female | British |

---

## Project Structure

```
cat-video-tools/
├── app.py                       # Streamlit web UI
├── requirements.txt
├── sanitizer/
│   ├── meeting_editor.py        # Core meeting sanitizer engine
│   ├── sanitize.py              # CLI entry point
│   ├── instructions.py          # YAML config/template system
│   └── templates/
│       └── ai_webinar.yaml      # AI webinar cleanup template
├── creator/
│   ├── video_creator.py         # Core video generation engine
│   ├── music.py                 # Auto background music (Pixabay)
│   └── templates/
│       └── video_script.yaml    # Starter video script template
└── examples/
    ├── sanitizer_demo.yaml      # Demo: sanitizer feature video
    └── creator_demo.yaml        # Demo: video creator feature video
```

## Auto Background Music

The Video Creator can automatically fetch royalty-free background music from Pixabay.

```bash
# Set your free API key (get one at https://pixabay.com/api/docs/)
export PIXABAY_API_KEY=your_key_here

# Then in your script:
background_music: "auto"
music_mood: "tech"       # corporate, ambient, upbeat, cinematic, chill, minimal
```

## License

MIT
