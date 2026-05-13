"""
CAT Video Tools — Web UI
=========================
Streamlit-based interface for both tools:
  1. Meeting Sanitizer: upload recording + transcript → get clean video
  2. Video Creator: describe your video → get narrated explainer

Run:
    streamlit run app.py
"""

import streamlit as st
import sys
import os
import tempfile
import shutil
from pathlib import Path

# Add tool directories to path
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "sanitizer"))
sys.path.insert(0, str(ROOT / "creator"))

st.set_page_config(
    page_title="CAT Video Tools",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        background: linear-gradient(90deg, #4fc3f7, #ba68c8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    .tool-card {
        background: #1e1e2e;
        border-radius: 12px;
        padding: 1.5rem;
        border: 1px solid #333;
        margin-bottom: 1rem;
    }
    .stProgress > div > div > div > div {
        background: linear-gradient(90deg, #4fc3f7, #81c784);
    }
</style>
""", unsafe_allow_html=True)


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p class="main-header">🎬 CAT Video Tools</p>', unsafe_allow_html=True)
    st.caption("Power CAT Video Production Suite")
    st.divider()
    
    tool = st.radio(
        "Select Tool",
        ["🏠 Home", "✂️ Meeting Sanitizer", "🎥 Video Creator"],
        index=0,
    )
    
    st.divider()
    st.caption("v1.0 • Built with Streamlit")
    st.caption("[GitHub Repo](https://github.com/KarimaKT/cat-video-tools)")


# ── Home Page ────────────────────────────────────────────────────────────────
if tool == "🏠 Home":
    st.markdown('<p class="main-header">CAT Video Tools</p>', unsafe_allow_html=True)
    st.markdown("**Two professional video tools in one package.**")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### ✂️ Meeting Sanitizer")
        st.markdown("""
        **You provide:**
        - A Teams/Zoom recording (.mp4)
        - A transcript file (.vtt)
        - Which speakers to keep
        - Any additional notes
        
        **I do the rest:**
        - Detect & remove non-target speakers
        - Cut admin chatter ("Am I muted?")
        - Mask participant tiles
        - Enhance audio to broadcast quality
        """)
    
    with col2:
        st.markdown("### 🎥 Video Creator")
        st.markdown("""
        **You provide:**
        - A topic or document to explain
        - Desired duration and voice
        - Any key points to cover
        
        **I do the rest:**
        - Generate professional slides
        - Create neural narration
        - Add transitions & background music
        - Produce a complete video
        """)


# ── Meeting Sanitizer ────────────────────────────────────────────────────────
elif tool == "✂️ Meeting Sanitizer":
    st.markdown("## ✂️ Meeting Sanitizer")
    st.markdown("Upload your recording and transcript. I'll clean it up professionally.")
    
    with st.expander("ℹ️ What this tool does", expanded=False):
        st.markdown("""
        - **Analyzes** your transcript to find non-target speakers and admin chatter
        - **Detects** the video layout (side panel, participant tiles) automatically
        - **Cuts** disturbance zones entirely (interruptions + reactions like "shall we mute you?")
        - **Masks** non-target participant tiles with black overlays
        - **Enhances** audio: noise reduction + loudness normalization
        """)
    
    st.divider()
    
    # File uploads
    col1, col2 = st.columns(2)
    with col1:
        video_file = st.file_uploader("📹 Upload Recording", type=["mp4", "mkv", "webm"],
                                       help="Teams or Zoom recording file")
    with col2:
        vtt_file = st.file_uploader("📝 Upload Transcript", type=["vtt", "srt"],
                                     help="VTT transcript (Teams auto-generates these)")
    
    # Speaker selection
    st.markdown("### Speakers to Keep")
    
    speakers_text = st.text_area(
        "Enter speaker names (one per line)",
        placeholder="Karima Kanji-Tajdin\nBobby Chang",
        help="Exact names as they appear in the transcript. Run 'Audit' first to see all detected names.",
        height=100,
    )
    
    # Advanced options
    with st.expander("⚙️ Advanced Options"):
        col1, col2, col3 = st.columns(3)
        with col1:
            crf = st.slider("Quality (CRF)", 18, 32, 22,
                           help="Lower = better quality, bigger file. 22 = high quality default.")
        with col2:
            audio_enhance = st.checkbox("Audio Enhancement", value=True,
                                       help="Noise reduction + loudness normalization")
        with col3:
            template = st.selectbox("Template", ["ai_webinar", "custom"],
                                   help="Preset disturbance detection patterns")
        
        segments_text = st.text_area(
            "Time Segments (optional)",
            placeholder="6:09 - 66:57  # Main content\n71:11 - 71:31  # Closing",
            help="Leave blank to process entire video. Format: start - end (MM:SS or H:MM:SS)",
            height=80,
        )
        
        additional_notes = st.text_area(
            "Additional Instructions (optional)",
            placeholder="E.g., 'End after Bobby says: and that's why we like the native integrations'",
            height=60,
        )
    
    st.divider()
    
    # Actions
    col1, col2, col3 = st.columns(3)
    
    with col1:
        audit_btn = st.button("🔍 Audit Only", use_container_width=True,
                             help="Analyze and show edit plan without rendering")
    with col2:
        render_btn = st.button("▶️ Render Video", type="primary", use_container_width=True,
                              help="Full analysis + render")
    with col3:
        verify_btn = st.button("🖼️ Verify Frame", use_container_width=True,
                              help="Extract a masked frame for visual QA")
    
    # Processing logic
    if (audit_btn or render_btn) and video_file and vtt_file and speakers_text.strip():
        # Save uploaded files to temp dir
        work_dir = Path(tempfile.mkdtemp(prefix="sanitizer_"))
        video_path = str(work_dir / "input.mp4")
        vtt_path = str(work_dir / "transcript.vtt")
        output_path = str(work_dir / "output.mp4")
        
        with open(video_path, "wb") as f:
            f.write(video_file.read())
        with open(vtt_path, "wb") as f:
            f.write(vtt_file.read())
        
        keep_speakers = [s.strip() for s in speakers_text.strip().split("\n") if s.strip()]
        
        # Parse segments if provided
        segments = None
        if segments_text.strip():
            segments = _parse_segments(segments_text)
        
        with st.spinner("Analyzing recording..."):
            try:
                from meeting_editor import MeetingEditor
                
                editor = MeetingEditor(
                    video_path=video_path,
                    vtt_path=vtt_path,
                    keep_speakers=keep_speakers,
                    segments=segments,
                )
                editor.analyze()
                
                # Show audit results
                st.markdown("### 📋 Audit Report")
                
                # Speakers found
                st.markdown("**Speakers detected:**")
                for name, dur in sorted(editor.all_speakers.items(), key=lambda x: -x[1]):
                    tag = "✅ KEEP" if name in editor.keep_speakers else "❌ REMOVE"
                    st.text(f"  {tag}  {name} ({dur/60:.1f} min)")
                
                # Disturbances
                if editor.disturbances:
                    st.markdown(f"**Disturbance zones found: {len(editor.disturbances)}**")
                    for d in sorted(editor.disturbances, key=lambda x: x.start):
                        dur = d.end - d.start
                        st.text(f"  ✂️ CUT {_fmt_time(d.start)} → {_fmt_time(d.end)} ({dur:.1f}s) — {d.reason}")
                
                # Clean segments
                st.markdown(f"**Output: {len(editor.clean_segments)} segments, "
                           f"{sum(e-s for s,e in editor.clean_segments)/60:.1f} min**")
                
                # Render if requested
                if render_btn:
                    st.divider()
                    progress = st.progress(0, text="Rendering...")
                    
                    editor.process(output_path, crf=crf, audio_enhance=audio_enhance)
                    progress.progress(100, text="Complete!")
                    
                    if os.path.exists(output_path):
                        st.success("✅ Video rendered successfully!")
                        with open(output_path, "rb") as f:
                            st.download_button(
                                "⬇️ Download Sanitized Video",
                                f.read(),
                                file_name="sanitized_output.mp4",
                                mime="video/mp4",
                                type="primary",
                            )
                
            except Exception as e:
                st.error(f"Error: {e}")
            finally:
                # Cleanup happens on next run or session end
                pass
    
    elif (audit_btn or render_btn):
        st.warning("Please upload both a video and transcript, and enter at least one speaker name.")


# ── Video Creator ────────────────────────────────────────────────────────────
elif tool == "🎥 Video Creator":
    st.markdown("## 🎥 Video Creator")
    st.markdown("Describe your video and I'll generate it with narration and professional slides.")
    
    with st.expander("ℹ️ What this tool does", expanded=False):
        st.markdown("""
        - **Generates** professional animated slides from your content
        - **Narrates** with neural text-to-speech (natural-sounding voices)
        - **Adds** transitions, background music, and branding
        - **Produces** a complete MP4 ready to upload
        """)
    
    st.divider()
    
    # Input method
    input_method = st.radio(
        "How would you like to provide content?",
        ["✍️ Write scenes manually", "📄 Upload YAML script", "📋 Describe and I'll structure it"],
        horizontal=True,
    )
    
    if input_method == "📄 Upload YAML script":
        script_file = st.file_uploader("Upload YAML script", type=["yaml", "yml"])
        
        if script_file:
            # Save and process
            work_dir = Path(tempfile.mkdtemp(prefix="creator_"))
            script_path = str(work_dir / "script.yaml")
            output_path = str(work_dir / "output.mp4")
            
            with open(script_path, "wb") as f:
                f.write(script_file.read())
            
            if st.button("▶️ Generate Video", type="primary"):
                with st.spinner("Generating video..."):
                    try:
                        from video_creator import VideoCreator
                        creator = VideoCreator(script_path)
                        creator.generate(output_path)
                        
                        if os.path.exists(output_path):
                            st.success("✅ Video generated!")
                            with open(output_path, "rb") as f:
                                st.download_button(
                                    "⬇️ Download Video",
                                    f.read(),
                                    file_name="generated_video.mp4",
                                    mime="video/mp4",
                                    type="primary",
                                )
                    except Exception as e:
                        st.error(f"Error: {e}")
    
    elif input_method == "✍️ Write scenes manually":
        st.markdown("### Video Settings")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            title = st.text_input("Video Title", "My Explainer Video")
        with col2:
            voice = st.selectbox("Voice", [
                "en-US-AriaNeural (Female)",
                "en-US-JennyNeural (Female)",
                "en-US-GuyNeural (Male)",
                "en-US-AndrewNeural (Male)",
                "en-US-BrianNeural (Male)",
                "en-GB-SoniaNeural (Female, UK)",
            ])
        with col3:
            voice_rate = st.select_slider("Speed", 
                options=["-20%", "-10%", "+0%", "+5%", "+10%", "+15%", "+20%"],
                value="+5%")
        
        st.markdown("### Scenes")
        st.caption("Add scenes to your video. Each scene gets a slide + narration.")
        
        # Dynamic scene editor
        if "scenes" not in st.session_state:
            st.session_state.scenes = [{"title": "", "narration": "", "bullets": ""}]
        
        for i, scene in enumerate(st.session_state.scenes):
            with st.container(border=True):
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.session_state.scenes[i]["title"] = st.text_input(
                        f"Scene {i+1} Title", scene.get("title", ""), key=f"title_{i}")
                    st.session_state.scenes[i]["bullets"] = st.text_area(
                        "Bullet points (one per line)", scene.get("bullets", ""),
                        key=f"bullets_{i}", height=80)
                with col2:
                    st.session_state.scenes[i]["narration"] = st.text_area(
                        "Narration", scene.get("narration", ""),
                        key=f"narr_{i}", height=130,
                        placeholder="What the narrator says during this scene...")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("➕ Add Scene"):
                st.session_state.scenes.append({"title": "", "narration": "", "bullets": ""})
                st.rerun()
        with col2:
            if len(st.session_state.scenes) > 1 and st.button("➖ Remove Last"):
                st.session_state.scenes.pop()
                st.rerun()
        
        st.divider()
        
        if st.button("▶️ Generate Video", type="primary"):
            # Build script from form data
            scenes_with_content = [s for s in st.session_state.scenes if s.get("narration")]
            if not scenes_with_content:
                st.warning("Add narration to at least one scene.")
            else:
                work_dir = Path(tempfile.mkdtemp(prefix="creator_"))
                output_path = str(work_dir / "output.mp4")
                
                with st.spinner("Generating video..."):
                    try:
                        from video_creator import VideoCreator, VideoScript, Scene as VScene
                        
                        script = VideoScript()
                        script.title = title
                        script.voice = voice.split(" (")[0]
                        script.voice_rate = voice_rate
                        
                        for s in scenes_with_content:
                            scene = VScene()
                            scene.title = s.get("title", "")
                            scene.narration = s.get("narration", "")
                            scene.bullets = [b.strip() for b in s.get("bullets", "").split("\n") if b.strip()]
                            scene.visual = "slide"
                            script.scenes.append(scene)
                        
                        creator = VideoCreator(script=script)
                        creator.generate(output_path)
                        
                        if os.path.exists(output_path):
                            st.success("✅ Video generated!")
                            st.video(output_path)
                            with open(output_path, "rb") as f:
                                st.download_button(
                                    "⬇️ Download Video",
                                    f.read(),
                                    file_name="generated_video.mp4",
                                    mime="video/mp4",
                                    type="primary",
                                )
                    except Exception as e:
                        st.error(f"Error: {e}")
    
    elif input_method == "📋 Describe and I'll structure it":
        st.markdown("### Describe Your Video")
        
        col1, col2 = st.columns(2)
        with col1:
            topic = st.text_area(
                "What should the video explain?",
                placeholder="E.g., 'Explain how Copilot Studio connects to Dataverse tables for structured AI knowledge retrieval'",
                height=120,
            )
            duration = st.select_slider(
                "Target Duration",
                options=["30 seconds", "60 seconds", "90 seconds", "2 minutes", "3 minutes", "5 minutes"],
                value="90 seconds",
            )
        with col2:
            audience = st.text_input("Target Audience",
                                    placeholder="E.g., 'Technical decision makers familiar with Power Platform'")
            key_points = st.text_area(
                "Key points to cover (optional)",
                placeholder="- How agents connect to Dataverse\n- Query patterns\n- Benefits over unstructured knowledge",
                height=100,
            )
            voice = st.selectbox("Preferred Voice", [
                "en-US-AriaNeural (Female)",
                "en-US-GuyNeural (Male)",
                "en-US-AndrewNeural (Male)",
                "en-US-JennyNeural (Female)",
            ], key="desc_voice")
        
        st.info("💡 **Tip:** Provide as much context as possible. I'll structure the scenes, write narration, and generate the video automatically.")
        
        if st.button("🪄 Generate Script & Video", type="primary"):
            if not topic:
                st.warning("Please describe what the video should explain.")
            else:
                st.info("⚠️ Auto-structuring from description requires AI assistance. "
                       "For now, use the 'Write scenes manually' or 'Upload YAML' mode, "
                       "or ask your Copilot CLI assistant to generate a script YAML for you.")


# ── Helper Functions ─────────────────────────────────────────────────────────

def _parse_segments(text: str) -> list:
    """Parse segment text like '6:09 - 66:57' into [(start_sec, end_sec), ...]"""
    import re
    segments = []
    for line in text.strip().split("\n"):
        line = line.split("#")[0].strip()  # remove comments
        if not line:
            continue
        match = re.match(r'(\d+:?\d+:?\d*)\s*[-–]\s*(\d+:?\d+:?\d*)', line)
        if match:
            start = _parse_time(match.group(1))
            end = _parse_time(match.group(2))
            if start is not None and end is not None:
                segments.append((start, end))
    return segments if segments else None


def _parse_time(t: str) -> float:
    """Parse MM:SS or H:MM:SS to seconds."""
    parts = t.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return None


def _fmt_time(sec: float) -> str:
    """Format seconds as M:SS or H:MM:SS."""
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
