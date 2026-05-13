"""
Professional Meeting Video Editor
==================================
Transcript-driven editing of Teams/Zoom recordings for publishing.

Given a video + VTT transcript + list of speakers to keep, this tool:
1. ANALYZES the transcript to find all non-target audio
2. DETECTS the video layout (side panel position, tile positions) via pixel analysis
3. IDENTIFIES "disturbance zones" — non-target speech PLUS surrounding admin
   reactions from kept speakers (e.g. "shall we mute you?", "Am I muted?")
4. AUTO-SPLITS segments to CUT disturbance zones entirely (not just mute)
5. AUDITS the final clean plan before processing
6. PROCESSES the video with visual masks + audio enhancement

Design principles:
- CUT, don't mute. Dead air from muted participants is obvious and unprofessional.
- Admin reactions to disturbances must also be cut (kept speakers saying
  "mute you", "can you hear me", etc. in response to non-target interruptions).
- Only use muting as a last resort for sub-second bleeds that can't be cut cleanly.
- The editor should produce broadcast-ready output with zero manual intervention.

Usage:
    from meeting_editor import MeetingEditor

    editor = MeetingEditor(
        video_path="recording.mp4",
        vtt_path="transcript.vtt",
        keep_speakers=["Karima Kanji-Tajdin", "Bobby Chang"],
    )
    editor.analyze()          # Parse transcript + detect layout + auto-split
    editor.audit()            # Print full edit plan
    editor.process("out.mp4") # Render final video
"""

import re
import subprocess
import json
import os
import shutil
import uuid
from pathlib import Path
from dataclasses import dataclass, field

try:
    import numpy as np
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# ── Data classes ──────────────────────────────────────────────────────────

@dataclass
class VTTEntry:
    start: float      # seconds
    end: float        # seconds
    speaker: str
    text: str

@dataclass
class Rect:
    x: int
    y: int
    w: int
    h: int
    label: str = ""

    def as_drawbox(self) -> str:
        return f"drawbox=x={self.x}:y={self.y}:w={self.w}:h={self.h}:color=black:t=fill"

@dataclass
class MuteRange:
    start: float     # source video seconds
    end: float       # source video seconds
    speaker: str
    text: str

@dataclass
class Disturbance:
    """A zone to CUT entirely — non-target speech plus surrounding admin reactions."""
    start: float       # source video seconds (includes admin lead-in)
    end: float         # source video seconds (includes admin tail)
    entries: list      # list of VTTEntry objects in this zone
    reason: str        # human-readable description

@dataclass
class Issue:
    """An issue found during audit."""
    severity: str    # "CRITICAL", "WARNING", "INFO"
    category: str    # "audio", "visual", "content", "admin"
    time_src: float  # source timestamp
    description: str
    action: str = "" # what the editor will do about it: "CUT", "MUTE", "FLAG"

@dataclass
class LayoutProfile:
    """Detected layout of a Teams recording."""
    width: int = 0
    height: int = 0
    panel_x: int = 0         # where side panel starts
    panel_width: int = 0
    tile_regions: list = field(default_factory=list)  # list of (y_start, y_end, label)
    name_bar: Rect = None    # speaker name overlay position


# ── VTT Parser ────────────────────────────────────────────────────────────

def parse_vtt(vtt_path: str) -> list[VTTEntry]:
    """Parse Teams VTT transcript."""
    content = Path(vtt_path).read_text(encoding="utf-8-sig")
    pattern = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[.,]\d{3})\s*\n"
        r"<v\s+([^>]+)>([^<]*)</v>"
    )
    entries = []
    for m in pattern.finditer(content):
        s, e, speaker, text = m.groups()
        entries.append(VTTEntry(
            start=_ts_to_sec(s), end=_ts_to_sec(e),
            speaker=speaker.strip(), text=text.strip()
        ))
    return entries


def _ts_to_sec(ts: str) -> float:
    parts = ts.replace(",", ".").split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return int(parts[0]) * 60 + float(parts[1])


def _fmt(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ── Layout Detection ──────────────────────────────────────────────────────

def detect_layout(video_path: str, sample_time: float = None) -> LayoutProfile:
    """Detect the Teams recording layout by analyzing a frame.
    
    Returns a LayoutProfile with panel position, tile boundaries, etc.
    """
    if not HAS_PIL:
        raise ImportError("PIL/numpy required for layout detection. pip install Pillow numpy")
    
    # Get video dimensions
    info = _ffprobe(video_path)
    width = height = 0
    duration = float(info.get("format", {}).get("duration", 0))
    for s in info.get("streams", []):
        if s.get("codec_type") == "video":
            width = int(s["width"])
            height = int(s["height"])
            break

    if sample_time is None:
        sample_time = min(300, duration * 0.1)  # 5 min in, or 10% of video
    
    # Extract frame
    frame_path = _extract_frame(video_path, sample_time)
    img = np.array(Image.open(frame_path))
    os.unlink(frame_path)

    layout = LayoutProfile(width=width, height=height)
    
    # Find panel boundary: scan columns from right looking for brightness drop
    # Teams slides area is bright (white/light background), panel is dark
    margin = int(width * 0.6)  # panel is always in the right 40%
    for x in range(width - 1, margin, -1):
        # Check column brightness (skip top/bottom 10%)
        col = img[int(height*0.1):int(height*0.9), x, :].mean()
        if col > 200:  # found bright slide area
            layout.panel_x = x + 1
            break
    else:
        # Fallback: try finding sharp brightness transition
        for x in range(margin, width - 50):
            left = img[int(height*0.1):int(height*0.9), x-5:x, :].mean()
            right = img[int(height*0.1):int(height*0.9), x:x+5, :].mean()
            if left > 150 and right < 50:
                layout.panel_x = x
                break
    
    layout.panel_width = width - layout.panel_x
    
    # Find tile positions within the panel
    if layout.panel_x > 0:
        panel_strip = img[:, layout.panel_x:, :]
        row_brightness = panel_strip.mean(axis=(1, 2))
        
        # Find bright bands (camera tiles) vs dark bands (gaps)
        threshold = 40
        in_tile = False
        tile_start = 0
        tiles = []
        for y in range(height):
            bright = row_brightness[y] > threshold
            if bright and not in_tile:
                tile_start = y
                in_tile = True
            elif not bright and in_tile:
                if y - tile_start > 20:  # ignore tiny bright spots
                    tiles.append((tile_start, y))
                in_tile = False
        if in_tile and height - tile_start > 20:
            tiles.append((tile_start, height))
        
        layout.tile_regions = tiles
    
    # Detect speaker name bar (bottom-left, usually last 40px of frame)
    bottom_strip = img[height-40:, :int(width*0.3), :]
    for y_offset in range(40):
        row_bright = bottom_strip[y_offset, :, :].mean()
        if row_bright > 30:
            bar_y = height - 40 + y_offset
            # Find width of name bar
            bar_w = 0
            for x in range(int(width * 0.3)):
                if img[bar_y, x, :].mean() > 20:
                    bar_w = x
            layout.name_bar = Rect(0, bar_y, min(bar_w + 20, int(width * 0.3)), height - bar_y, "speaker_name")
            break
    
    return layout


def _ffprobe(path: str) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True
    )
    return json.loads(r.stdout) if r.stdout else {}


def _extract_frame(video_path: str, time_sec: float) -> str:
    """Extract a single frame as a temp PNG."""
    tmp = Path(video_path).parent / f"_tmp_frame_{int(time_sec)}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(time_sec), "-i", video_path,
         "-frames:v", "1", "-update", "1", str(tmp)],
        capture_output=True, text=True
    )
    return str(tmp)


# ── Main Editor ───────────────────────────────────────────────────────────

class MeetingEditor:
    """Professional meeting video editor.
    
    Args:
        video_path:    Path to the source recording
        vtt_path:      Path to the VTT transcript
        keep_speakers: List of speaker names to keep (all others are removed)
        segments:      Optional list of (start_sec, end_sec) to keep from source.
                       If None, keeps the full video.
        layout_overrides: Optional dict of layout masks per segment index.
                          e.g. {2: [Rect(...)]} for a different layout in segment 3.
    """

    def __init__(self, video_path: str, vtt_path: str, keep_speakers: list[str],
                 segments: list[tuple[float, float]] = None,
                 layout_overrides: dict = None):
        self.video_path = video_path
        self.vtt_path = vtt_path
        self.keep_speakers = set(keep_speakers)
        self.segments = segments
        self.layout_overrides = layout_overrides or {}
        
        # Populated by analyze()
        self.vtt_entries: list[VTTEntry] = []
        self.all_speakers: dict[str, float] = {}
        self.layout: LayoutProfile = None
        self.issues: list[Issue] = []
        self.mute_ranges: list[MuteRange] = []       # only for sub-second bleeds
        self.disturbances: list[Disturbance] = []     # zones to CUT entirely
        self.visual_masks: list[Rect] = []
        self.clean_segments: list[tuple[float, float]] = []  # final segments after auto-split
        self._analyzed = False
    
    # ── Step 1: Analyze ───────────────────────────────────────────────

    def analyze(self, detect_visual_layout: bool = True):
        """Full analysis: transcript + layout + issue detection."""
        print("=" * 60)
        print("ANALYZING MEETING RECORDING")
        print("=" * 60)
        
        # Parse transcript
        self.vtt_entries = parse_vtt(self.vtt_path)
        print(f"  Transcript: {len(self.vtt_entries)} entries parsed")
        
        # Speaker summary
        self.all_speakers = {}
        for e in self.vtt_entries:
            self.all_speakers[e.speaker] = self.all_speakers.get(e.speaker, 0) + (e.end - e.start)
        
        print(f"  Speakers found: {len(self.all_speakers)}")
        for name, dur in sorted(self.all_speakers.items(), key=lambda x: -x[1]):
            tag = " [KEEP]" if name in self.keep_speakers else " [REMOVE]"
            print(f"    {name:<35} {dur/60:.1f} min{tag}")
        
        # Detect layout
        if detect_visual_layout and HAS_PIL:
            print(f"\n  Detecting video layout...")
            self.layout = detect_layout(self.video_path)
            print(f"    Resolution:  {self.layout.width}x{self.layout.height}")
            print(f"    Panel start: x={self.layout.panel_x}")
            print(f"    Panel width: {self.layout.panel_width}px")
            print(f"    Tiles found: {len(self.layout.tile_regions)}")
            for i, (y1, y2) in enumerate(self.layout.tile_regions):
                print(f"      Tile {i+1}: y={y1}-{y2} ({y2-y1}px)")
            if self.layout.name_bar:
                nb = self.layout.name_bar
                print(f"    Name bar:    x={nb.x} y={nb.y} w={nb.w} h={nb.h}")
        
        # Use segments or full video
        if self.segments is None:
            info = _ffprobe(self.video_path)
            dur = float(info.get("format", {}).get("duration", 0))
            self.segments = [(0, dur)]
        
        # Find all issues, build disturbance zones, auto-split segments
        self._find_disturbances()
        self._find_content_issues()
        self._auto_split_segments()
        self._build_visual_masks()
        
        self._analyzed = True
        print(f"\n  Analysis complete:")
        print(f"    {len(self.disturbances)} disturbance zones to CUT")
        print(f"    {len(self.mute_ranges)} sub-second bleeds to MUTE")
        print(f"    {len(self.clean_segments)} clean segments (after auto-split)")
        print(f"    {len(self.issues)} issues total")
        return self

    def _find_disturbances(self):
        """Find disturbance zones: non-target speech + surrounding admin reactions.
        
        A disturbance zone includes:
        1. All contiguous non-target speaker entries
        2. Any kept-speaker entries that are REACTIONS to the disturbance:
           - Admin language: "mute", "unmute", "can you hear", "shall we", etc.
           - Filler reactions: "All right", "OK", "Amazing" right after disturbance
        3. A buffer to catch the transition back to clean content
        
        Short bleeds (<1s of non-target audio with no admin reaction) become
        mute ranges instead of cuts.
        """
        admin_patterns = [
            'mute', 'unmute', 'shall we', 'can you hear', 'screen share',
            'someone', 'somebody', 'who is', 'you\'re muted', 'am i muted',
        ]
        reaction_patterns = [
            'amazing', 'all right', 'alright', 'ok so', 'okay so',
            'anyway', 'moving on', 'where were we', 'so anyway',
        ]
        
        for seg_i, (seg_start, seg_end) in enumerate(self.segments):
            # Get all entries in this segment
            seg_entries = [e for e in self.vtt_entries
                          if e.start >= seg_start and e.start < seg_end]
            
            # Find clusters of non-target speech
            i = 0
            while i < len(seg_entries):
                e = seg_entries[i]
                if e.speaker in self.keep_speakers:
                    i += 1
                    continue
                
                # Found non-target speech — build the disturbance zone
                zone_entries = [e]
                zone_start = e.start
                zone_end = e.end
                
                # Expand forward: include adjacent non-target + admin reactions
                j = i + 1
                while j < len(seg_entries):
                    next_e = seg_entries[j]
                    gap = next_e.start - zone_end
                    
                    if gap > 5.0:
                        break  # too far apart, separate disturbance
                    
                    if next_e.speaker not in self.keep_speakers:
                        # More non-target speech
                        zone_entries.append(next_e)
                        zone_end = max(zone_end, next_e.end)
                        j += 1
                    elif self._is_admin_reaction(next_e, admin_patterns, reaction_patterns):
                        # Kept speaker reacting to the disturbance
                        zone_entries.append(next_e)
                        zone_end = max(zone_end, next_e.end)
                        j += 1
                    else:
                        break  # clean content resumes
                    
                # Expand backward: check if kept speaker's lead-in is admin
                k = i - 1
                while k >= 0:
                    prev_e = seg_entries[k]
                    gap = zone_start - prev_e.end
                    if gap > 2.0:
                        break
                    if prev_e.speaker in self.keep_speakers and \
                       self._is_admin_reaction(prev_e, admin_patterns, reaction_patterns):
                        zone_entries.insert(0, prev_e)
                        zone_start = min(zone_start, prev_e.start)
                        k -= 1
                    else:
                        break
                
                # Determine: CUT or MUTE?
                non_target_duration = sum(
                    ze.end - ze.start for ze in zone_entries
                    if ze.speaker not in self.keep_speakers
                )
                total_zone_duration = zone_end - zone_start
                
                if non_target_duration < 0.8 and total_zone_duration < 1.5:
                    # Very brief bleed — mute instead of cut
                    for ze in zone_entries:
                        if ze.speaker not in self.keep_speakers:
                            self.mute_ranges.append(MuteRange(
                                start=ze.start, end=ze.end,
                                speaker=ze.speaker, text=ze.text
                            ))
                            self.issues.append(Issue(
                                severity="WARNING", category="audio",
                                time_src=ze.start,
                                description=f"Brief bleed [{ze.speaker}]: \"{ze.text[:50]}\"",
                                action="MUTE"
                            ))
                else:
                    # Substantial disturbance — CUT the entire zone
                    speakers_involved = set(ze.speaker for ze in zone_entries
                                           if ze.speaker not in self.keep_speakers)
                    reason = (f"{len(zone_entries)} entries, "
                             f"{total_zone_duration:.1f}s, "
                             f"speakers: {', '.join(speakers_involved)}")
                    self.disturbances.append(Disturbance(
                        start=zone_start,
                        end=zone_end,
                        entries=zone_entries,
                        reason=reason
                    ))
                    for ze in zone_entries:
                        action_desc = "CUT (part of disturbance zone)"
                        if ze.speaker in self.keep_speakers:
                            action_desc = "CUT (admin reaction to disturbance)"
                        self.issues.append(Issue(
                            severity="CRITICAL", category="audio",
                            time_src=ze.start,
                            description=f"[{ze.speaker}]: \"{ze.text[:60]}\"",
                            action=action_desc
                        ))
                
                i = j  # skip past the zone

    def _is_admin_reaction(self, entry: VTTEntry, admin_pats: list, reaction_pats: list) -> bool:
        """Check if a kept-speaker entry is an admin reaction to a disturbance."""
        lower = entry.text.lower()
        for pat in admin_pats + reaction_pats:
            if pat in lower:
                return True
        # Very short entries right next to disturbances are likely reactions
        if (entry.end - entry.start) < 2.0 and len(entry.text.split()) <= 4:
            # Short utterance like "All right.", "OK.", "Amazing."
            return True
        return False

    def _auto_split_segments(self):
        """Split user-provided segments around disturbance zones.
        
        Input: self.segments (rough time ranges to keep)
        Output: self.clean_segments (refined ranges with disturbances excised)
        
        Also adjusts layout_overrides indices to match new segment numbering.
        """
        if not self.disturbances:
            self.clean_segments = list(self.segments)
            return
        
        new_segments = []
        old_to_new = {}  # map old segment index to new indices
        
        for seg_i, (seg_start, seg_end) in enumerate(self.segments):
            # Find disturbances within this segment
            seg_disturbances = [
                d for d in self.disturbances
                if d.start >= seg_start and d.end <= seg_end
            ]
            
            if not seg_disturbances:
                old_to_new[seg_i] = [len(new_segments)]
                new_segments.append((seg_start, seg_end))
                continue
            
            # Sort by start time
            seg_disturbances.sort(key=lambda d: d.start)
            
            # Split around each disturbance
            cursor = seg_start
            new_indices = []
            for d in seg_disturbances:
                # Add clean portion before disturbance (if substantial)
                if d.start - cursor > 1.0:
                    new_indices.append(len(new_segments))
                    new_segments.append((cursor, d.start))
                
                # Find clean resume point after disturbance
                # Look for the next kept-speaker entry that's real content
                resume = d.end
                for e in self.vtt_entries:
                    if e.start >= d.end and e.speaker in self.keep_speakers:
                        # Check this isn't another reaction/filler
                        lower = e.text.lower().strip()
                        if lower.startswith(('amazing', 'all right', 'alright', 'ok ', 'okay')):
                            resume = e.end  # skip this filler too
                        else:
                            resume = e.start
                            break
                
                cursor = resume
            
            # Add remaining clean portion
            if seg_end - cursor > 1.0:
                new_indices.append(len(new_segments))
                new_segments.append((cursor, seg_end))
            
            old_to_new[seg_i] = new_indices
        
        # Remap layout_overrides to new segment indices
        new_overrides = {}
        for old_i, rects in self.layout_overrides.items():
            if old_i in old_to_new:
                for new_i in old_to_new[old_i]:
                    new_overrides[new_i] = rects
        self.layout_overrides = new_overrides
        
        self.clean_segments = new_segments
        
        if len(new_segments) != len(self.segments):
            removed_time = sum(d.end - d.start for d in self.disturbances)
            print(f"\n  Auto-split: {len(self.segments)} segments → "
                  f"{len(new_segments)} (cut {removed_time:.1f}s of disturbances)")

    def _find_content_issues(self):
        """Find standalone admin mentions, hesitations, and gaps.
        
        Note: admin reactions that are PART of a disturbance zone are already
        handled by _find_disturbances(). This catches standalone admin talk
        from kept speakers (e.g. "Hey Karima, I think you're muted" from Bobby
        when there's no adjacent non-target speech).
        """
        standalone_admin_patterns = [
            'you\'re muted', 'you are muted', 'am i muted', 'are we muted',
            'i think you\'re muted', 'can you hear me', 'is my mic',
            'we\'re sharing the recording', 'we were sharing the recording',
            'drop this image into the chat', 'questions in the chat',
        ]
        filler_words = {'uh', 'um', 'umm', 'uhh', 'ah', 'hmm', 'uh-huh', 'mhm'}
        
        # Which source times are already covered by disturbances?
        disturbed_times = set()
        for d in self.disturbances:
            for e in d.entries:
                disturbed_times.add(e.start)
        
        for seg_i, (seg_start, seg_end) in enumerate(self.segments):
            prev_end = seg_start
            for e in self.vtt_entries:
                if e.start < seg_start or e.start >= seg_end:
                    continue
                if e.start in disturbed_times:
                    continue  # already handled
                
                # Standalone admin mentions from kept speakers
                if e.speaker in self.keep_speakers:
                    lower = e.text.lower()
                    for pat in standalone_admin_patterns:
                        if pat in lower:
                            # This is standalone admin — create a disturbance to cut it
                            self.disturbances.append(Disturbance(
                                start=e.start,
                                end=e.end,
                                entries=[e],
                                reason=f"standalone admin: \"{e.text[:50]}\""
                            ))
                            self.issues.append(Issue(
                                severity="CRITICAL", category="admin",
                                time_src=e.start,
                                description=f"Standalone admin [{e.speaker}]: \"{e.text[:60]}\"",
                                action="CUT"
                            ))
                            break
                
                # Hesitations at segment boundaries (first/last 3 seconds)
                if e.speaker in self.keep_speakers:
                    in_first_3 = (e.start - seg_start) < 3
                    in_last_3 = (seg_end - e.start) < 3
                    if in_first_3 or in_last_3:
                        words = e.text.lower().split()
                        has_filler = any(w.strip('.,!?') in filler_words for w in words)
                        if has_filler:
                            loc = "start" if in_first_3 else "end"
                            self.issues.append(Issue(
                                severity="WARNING", category="content",
                                time_src=e.start,
                                description=f"Filler at segment {loc}: \"{e.text[:60]}\"",
                                action="FLAG"
                            ))
                
                # Long gaps
                gap = e.start - prev_end
                if gap > 3.0:
                    self.issues.append(Issue(
                        severity="INFO", category="content",
                        time_src=e.start,
                        description=f"{gap:.1f}s silence gap",
                        action="FLAG"
                    ))
                prev_end = e.end

    def _build_visual_masks(self):
        """Build visual mask rectangles from layout analysis."""
        if not self.layout or not self.layout.tile_regions:
            return
        
        # Determine which tiles belong to kept speakers vs others
        # Heuristic: first N tiles (from top) correspond to kept speakers,
        # remaining tiles are other participants to mask
        n_keep = len(self.keep_speakers)
        tiles = self.layout.tile_regions
        
        if len(tiles) > n_keep:
            # Tiles might have name labels between them, so we look for groups
            # Keep the first n_keep substantial tiles (>50px tall), mask the rest
            kept = 0
            mask_start_y = 0
            for i, (y1, y2) in enumerate(tiles):
                tile_height = y2 - y1
                if tile_height > 50:  # substantial tile (camera feed)
                    kept += 1
                if kept >= n_keep:
                    # Everything after this tile gets masked
                    mask_start_y = y2
                    break
            
            if mask_start_y > 0:
                self.visual_masks.append(Rect(
                    x=self.layout.panel_x,
                    y=mask_start_y,
                    w=self.layout.panel_width,
                    h=self.layout.height - mask_start_y,
                    label="non-target participants"
                ))
        
        # Always mask the speaker name bar if detected
        if self.layout.name_bar:
            self.visual_masks.append(self.layout.name_bar)

    # ── Step 2: Audit ─────────────────────────────────────────────────

    def audit(self) -> bool:
        """Print a complete audit report. Returns True if disturbances were found."""
        if not self._analyzed:
            self.analyze()
        
        print("\n" + "=" * 60)
        print("EDIT PLAN AUDIT REPORT")
        print("=" * 60)
        
        # Disturbances found and cut
        if self.disturbances:
            print(f"\n── DISTURBANCE ZONES CUT ({len(self.disturbances)}) ──")
            total_cut = 0
            for d in sorted(self.disturbances, key=lambda x: x.start):
                dur = d.end - d.start
                total_cut += dur
                print(f"  ✂ CUT {_fmt(d.start)} → {_fmt(d.end)} ({dur:.1f}s) — {d.reason}")
                for e in d.entries:
                    tag = "  [ADMIN REACTION]" if e.speaker in self.keep_speakers else ""
                    print(f"       [{e.speaker}]: \"{e.text[:65]}\"{tag}")
            print(f"  Total cut: {total_cut:.1f}s")
        
        # Clean segments (after auto-split)
        print(f"\n── CLEAN SEGMENTS ({len(self.clean_segments)}) ──")
        total_dur = 0
        for i, (s, e) in enumerate(self.clean_segments):
            dur = e - s
            total_dur += dur
            mask_note = ""
            if i in self.layout_overrides:
                mask_note = " [CUSTOM LAYOUT]"
            print(f"  {i+1}. {_fmt(s)} → {_fmt(e)} ({dur:.0f}s){mask_note}")
        print(f"  Total output: {_fmt(total_dur)} ({total_dur/60:.1f} min)")
        
        # Visual masks
        print(f"\n── VISUAL MASKS ({len(self.visual_masks)}) ──")
        for r in self.visual_masks:
            print(f"  {r.as_drawbox()}  ({r.label})")
        for seg_i, rects in self.layout_overrides.items():
            print(f"  Segment {seg_i+1} overrides:")
            for r in rects:
                print(f"    {r.as_drawbox()}  ({r.label})")

        # Sub-second mutes (if any)
        if self.mute_ranges:
            print(f"\n── SUB-SECOND AUDIO MUTES ({len(self.mute_ranges)}) ──")
            for mr in self.mute_ranges:
                print(f"  MUTE {_fmt(mr.start)} → {_fmt(mr.end)} "
                      f"({mr.end-mr.start:.1f}s) [{mr.speaker}]: \"{mr.text[:50]}\"")
        
        # Remaining flags
        flags = [i for i in self.issues if i.action == "FLAG"]
        if flags:
            print(f"\n── FLAGGED FOR REVIEW ({len(flags)}) ──")
            for issue in flags:
                print(f"  [{issue.severity}] {_fmt(issue.time_src)}: {issue.description}")
        
        # Summary
        n_cut = sum(1 for i in self.issues if 'CUT' in i.action)
        n_mute = sum(1 for i in self.issues if i.action == 'MUTE')
        n_flag = len(flags)
        print(f"\n{'=' * 60}")
        print(f"  Actions: {n_cut} CUT, {n_mute} MUTE, {n_flag} flagged")
        print(f"  Output: {len(self.clean_segments)} segments, {total_dur/60:.1f} min")
        print("=" * 60)
        
        return len(self.disturbances) > 0

    def _merge_mute_ranges(self) -> list[dict]:
        """Merge overlapping/adjacent mute ranges."""
        if not self.mute_ranges:
            return []
        sorted_mr = sorted(self.mute_ranges, key=lambda x: x.start)
        merged = []
        current = {
            'start': sorted_mr[0].start - 0.3,
            'end': sorted_mr[0].end + 0.3,
            'speaker': sorted_mr[0].speaker,
            'texts': [sorted_mr[0].text]
        }
        for mr in sorted_mr[1:]:
            if mr.start - 0.3 <= current['end'] + 0.5:
                current['end'] = max(current['end'], mr.end + 0.3)
                if mr.speaker != current['speaker']:
                    current['speaker'] += f" + {mr.speaker}"
                current['texts'].append(mr.text)
            else:
                merged.append(current)
                current = {
                    'start': mr.start - 0.3,
                    'end': mr.end + 0.3,
                    'speaker': mr.speaker,
                    'texts': [mr.text]
                }
        merged.append(current)
        return merged

    # ── Step 3: Process ───────────────────────────────────────────────

    def process(self, output_path: str, crf: int = 22, audio_enhance: bool = True):
        """Render the final edited video.
        
        Uses clean_segments (auto-split around disturbances).
        Only applies muting for sub-second bleeds that couldn't be cut.
        """
        if not self._analyzed:
            self.analyze()
        
        segments = self.clean_segments
        out_dir = Path(output_path).parent
        # Use unique temp dir to avoid collisions with parallel runs
        temp_dir = out_dir / f"_edit_temp_{uuid.uuid4().hex[:8]}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        print("\n" + "=" * 60)
        print("PROCESSING VIDEO")
        print("=" * 60)
        
        # Build merged mute ranges (only sub-second bleeds remain)
        merged_mutes = self._merge_mute_ranges() if self.mute_ranges else []
        
        temp_files = []
        for i, (seg_start, seg_end) in enumerate(segments):
            tmp = str(temp_dir / f"seg_{i:02d}.mp4")
            dur = seg_end - seg_start
            print(f"\n  Segment {i+1}/{len(segments)}: "
                  f"{_fmt(seg_start)} → {_fmt(seg_end)} ({dur:.0f}s)")
            
            # Video filters: masks
            vf_parts = []
            if i in self.layout_overrides:
                for r in self.layout_overrides[i]:
                    vf_parts.append(r.as_drawbox())
            else:
                for r in self.visual_masks:
                    vf_parts.append(r.as_drawbox())
            
            # Audio filters: mute non-target speakers + enhancement
            af_parts = []
            
            # Mute ranges that fall within this segment (using segment-local time)
            for mr in merged_mutes:
                # Check overlap with this segment
                mute_start = max(mr['start'], seg_start)
                mute_end = min(mr['end'], seg_end)
                if mute_start < mute_end:
                    # Convert to segment-local time
                    local_start = mute_start - seg_start
                    local_end = mute_end - seg_start
                    af_parts.append(
                        f"volume=enable='between(t,{local_start:.2f},{local_end:.2f})':volume=0"
                    )
                    print(f"    Muting: {_fmt(mute_start)} → {_fmt(mute_end)} "
                          f"(local {local_start:.1f}-{local_end:.1f}s)")
            
            # Audio enhancement
            if audio_enhance:
                af_parts.append("highpass=f=80")
                af_parts.append("afftdn=nf=-20")
                af_parts.append("loudnorm=I=-14:TP=-1:LRA=11")
            
            # Build FFmpeg command
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(seg_start), "-to", str(seg_end),
                "-i", self.video_path,
            ]
            if vf_parts:
                cmd += ["-vf", ",".join(vf_parts)]
            if af_parts:
                cmd += ["-af", ",".join(af_parts)]
            cmd += [
                "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
                "-c:a", "aac", "-b:a", "192k",
                tmp
            ]
            
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"    ERROR: {r.stderr[-300:]}")
                continue
            
            size = os.path.getsize(tmp) / 1024 / 1024
            print(f"    ✓ Encoded ({size:.1f} MB)")
            temp_files.append(tmp)
        
        if not temp_files:
            print("  No segments processed!")
            shutil.rmtree(str(temp_dir), ignore_errors=True)
            return None
        
        # Concatenate
        if len(temp_files) == 1:
            shutil.move(temp_files[0], output_path)
        else:
            list_file = str(temp_dir / "concat.txt")
            with open(list_file, "w") as f:
                for tf in temp_files:
                    # Use forward slashes for FFmpeg compatibility on Windows
                    fpath = str(Path(tf).resolve()).replace("\\", "/")
                    f.write(f"file '{fpath}'\n")
            
            print(f"\n  Concatenating {len(temp_files)} segments...")
            cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", list_file, "-c", "copy", output_path
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"  Concat error: {r.stderr[-300:]}")
                shutil.rmtree(str(temp_dir), ignore_errors=True)
                return None
        
        # Cleanup
        shutil.rmtree(str(temp_dir), ignore_errors=True)
        
        size = os.path.getsize(output_path) / 1024 / 1024
        print(f"\n  ✅ DONE: {output_path} ({size:.0f} MB)")
        return output_path

    # ── Helpers ────────────────────────────────────────────────────────

    def verify_frame(self, source_time: float, output_path: str = None):
        """Extract a frame with masks applied for visual verification."""
        if output_path is None:
            output_path = str(Path(self.video_path).parent / f"_verify_{int(source_time)}s.png")
        
        # Determine which segment this time falls in
        seg_i = None
        for i, (s, e) in enumerate(self.segments):
            if s <= source_time <= e:
                seg_i = i
                break
        
        # Get masks for this segment
        if seg_i is not None and seg_i in self.layout_overrides:
            masks = self.layout_overrides[seg_i]
        else:
            masks = self.visual_masks
        
        vf = ",".join(r.as_drawbox() for r in masks) if masks else "null"
        
        cmd = [
            "ffmpeg", "-y", "-ss", str(source_time), "-i", self.video_path,
            "-frames:v", "1", "-update", "1", "-vf", vf, output_path
        ]
        subprocess.run(cmd, capture_output=True, text=True)
        print(f"  Verification frame: {output_path}")
        return output_path

    def get_speaker_segments(self, speaker: str) -> list[tuple[float, float]]:
        """Get all time ranges where a specific speaker is talking."""
        ranges = []
        for e in self.vtt_entries:
            if e.speaker == speaker:
                ranges.append((e.start, e.end))
        return ranges


# ── CLI ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage: python meeting_editor.py <video> <vtt> <speaker1> [speaker2] ...")
        print("\nExample:")
        print('  python meeting_editor.py recording.mp4 transcript.vtt "Karima" "Bobby"')
        sys.exit(1)
    
    video = sys.argv[1]
    vtt = sys.argv[2]
    speakers = sys.argv[3:]
    
    editor = MeetingEditor(video, vtt, speakers)
    editor.analyze()
    editor.audit()
    
    print("\nTo process, call editor.process('output.mp4')")
