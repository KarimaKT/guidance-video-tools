# Meeting Sanitizer — Internals & Operational Learnings

This document captures the implementation details and hard-won learnings from the
meeting editor engine (`sanitizer/meeting_editor.py`). Keep this updated when the
engine changes.

---

## Design principles

- **CUT, don't mute.** Dead air from muted participants is obvious and unprofessional.
  Disturbance zones are removed entirely so the timeline stays tight.
- **Admin reactions must go too.** When a kept speaker responds to an interruption
  ("shall we mute you?", "can you hear me?") that reaction is part of the disturbance
  and gets cut with it.
- **Muting is the last resort.** Only sub-second bleeds that cannot be cut cleanly
  (< 0.8 s of non-target audio with a total zone < 1.5 s) are muted instead of cut.
- **Audit before render.** The workflow is always: analyze → audit → (optionally verify
  frame) → process. Never render without reviewing the edit plan.

---

## Disturbance detection

A disturbance zone is built around every cluster of non-target speech and expanded
to include surrounding reactions from kept speakers.

### What gets flagged

| Type | Condition |
|---|---|
| Non-target speech | Any speaker not in `keep_speakers` |
| Admin language | Kept speaker says anything matching: `mute`, `unmute`, `shall we`, `can you hear`, `screen share`, `someone`, `somebody`, `who is`, `you're muted`, `am i muted` |
| Filler reactions | Kept speaker says: `amazing`, `all right`, `alright`, `ok so`, `okay so`, `anyway`, `moving on`, `where were we`, `so anyway` |
| Short utterances | Kept speaker entry is < 2.0 s **and** ≤ 4 words, adjacent to non-target speech |
| Standalone admin | `you're muted`, `you are muted`, `am i muted`, `can you hear me`, `is my mic` — even when not adjacent to a disturbance |
| Filler words | `uh`, `um`, `umm`, `uhh`, `ah`, `hmm`, `uh-huh`, `mhm` at segment boundaries |

### Bleed threshold

- Non-target zone **< 0.8 s** AND total zone **< 1.5 s** → **mute** (can't cut cleanly)
- Everything else → **cut entirely**

Sub-second bleeds are tracked separately in `mute_ranges` and applied as an FFmpeg
volume filter (`volume=0`) over the source timestamp range.

### Speech-boundary snapping

When cutting, the editor pads boundaries to avoid syllable clipping:
- End of kept content: **+0.15 s** (let trailing speech finish)
- Resume point: **−0.1 s** pre-roll (catch speech onset)

---

## Layout detection

`detect_layout(video_path)` samples a frame and uses pixel analysis to find:

| What | How |
|---|---|
| **Side panel position** (`panel_x`) | Scans columns for a brightness drop marking where the participant grid begins |
| **Tile boundaries** (`tile_regions`) | Scans rows within the panel for bright bands (camera feeds) vs dark bands (gaps); ignores bands < 20 px |
| **Speaker name bar** (`name_bar`) | Looks for a low-brightness band in the bottom-left of the frame (last ~40 px); auto-sizes width up to 30% of frame width |

Requires `Pillow` and `numpy`. If not installed, layout detection is skipped and you
must provide masks manually via `layout_overrides`.

### Tile masking heuristic

- Keep the first `N` substantial tiles (> 50 px tall) where `N = len(keep_speakers)`
- Mask all remaining tiles (other participants)
- Mask the name bar unless `preserve_presenter_names=True`

### Gallery / spotlight view

When the recording switches layout mid-video (e.g., gallery view for a closing
segment), the auto-detected layout will be wrong for those segments. Use
`layout_overrides` to provide explicit `Rect` masks per segment index:

```python
editor = MeetingEditor(
    ...,
    layout_overrides={
        1: [  # segment index 1 uses gallery layout
            Rect(1690, 0, 230, 1080, "attendee circles"),
            Rect(0, 1050, 220, 30, "Karima name bar"),
            Rect(790, 1048, 220, 30, "Bobby name bar"),
        ]
    }
)
```

> **Important:** `layout_overrides` indices refer to the segments *after* disturbance
> splitting. If `auto_split` creates extra segments, the editor automatically remaps
> override indices to the correct new segment positions. You don't need to recount
> manually — but re-run `audit()` to confirm the remapping looks right.

---

## Audio enhancement

Applied by default (`audio_enhance=True`). Disable with `audio_enhance=False`.

| Filter | Purpose |
|---|---|
| `highpass=f=80` | Remove low-frequency rumble (HVAC, desk vibration) |
| `afftdn=nf=-20` | FFT-based noise reduction at −20 dB noise floor |
| `loudnorm=I=-14:TP=-1:LRA=11` | Broadcast-standard loudness normalization |

---

## CRF quality

The `crf` parameter in `process()` controls encode quality (lower = better quality,
larger file):

| CRF | Quality | Use case |
|---|---|---|
| 18 | Visually lossless | Archive / master copy |
| **22** | High quality | **Default — good for publishing** |
| 28 | Medium | Quick preview / draft |

---

## Python API

The YAML interface and Streamlit app are the recommended entry points, but the
engine is also fully accessible directly:

```python
from sanitizer.meeting_editor import MeetingEditor, Rect

editor = MeetingEditor(
    video_path="recording.mp4",
    vtt_path="transcript.vtt",
    keep_speakers=["Alice Smith", "Bob Jones"],
    segments=[
        (369, 4017),   # 6:09–66:57 main content
        (4271, 4291),  # 71:11–71:31 closing remarks
    ],
    layout_overrides={
        1: [
            Rect(1690, 0, 230, 1080, "attendee circles (gallery)"),
            Rect(0, 1050, 220, 30, "Alice name bar"),
        ]
    },
)

editor.analyze()             # parse transcript + detect layout + find disturbances
editor.audit()               # print full edit plan — always review before rendering
editor.verify_frame(300)     # extract a masked frame at 5:00 for visual QA
editor.process("out.mp4", crf=22, audio_enhance=True)
```

### `get_speaker_segments(speaker)`

Returns all `(start_sec, end_sec)` ranges for a speaker from the transcript.
Useful for building `segments` when you only want one presenter's portions:

```python
ranges = editor.get_speaker_segments("Alice Smith")
```

---

## Troubleshooting

### Wrong speaker names
Run audit with any placeholder name — the output lists every speaker found with
their exact transcript spelling:

```bash
python sanitizer/sanitize.py project.yaml --audit
```

Or via the Python API:

```python
editor = MeetingEditor(video_path="rec.mp4", vtt_path="t.vtt", keep_speakers=["x"])
editor.analyze()
editor.audit()   # prints all detected speaker names
```

### Masks in wrong position
```python
editor.analyze()
editor.verify_frame(300)    # check at 5:00
editor.verify_frame(4275)   # check at a layout-switch point
```

### FFmpeg not found (Windows)
Refresh PATH after install without restarting your terminal:

```powershell
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path","User")
```

### Pillow/numpy not installed
Layout detection is silently skipped. Install to enable auto-detection:

```bash
pip install Pillow numpy
```

Without these, provide all masks manually via `layout_overrides`.
