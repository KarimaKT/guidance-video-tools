#!/usr/bin/env python3
"""
Teams Meeting Sanitizer — CLI Entry Point

Usage:
    python sanitize.py <instructions.yaml>              # full render
    python sanitize.py <instructions.yaml> --audit      # audit only (no render)
    python sanitize.py <instructions.yaml> --verify 300 # extract masked frame at 5:00
    python sanitize.py --templates                       # list available templates
    python sanitize.py --init <template_name>            # generate a starter config

Examples:
    python sanitize.py my_webinar.yaml --audit
    python sanitize.py my_webinar.yaml
    python sanitize.py --init ai_webinar
"""

import sys
import argparse
from pathlib import Path

from meeting_editor import MeetingEditor, Rect
from instructions import load_instructions, list_templates, load_template


def main():
    parser = argparse.ArgumentParser(
        description="Professional meeting recording sanitizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s project.yaml              Analyze, audit, and render
  %(prog)s project.yaml --audit      Audit only (review edit plan)
  %(prog)s project.yaml --verify 300 Extract masked frame at 5:00
  %(prog)s --templates               List available templates
  %(prog)s --init ai_webinar         Create starter config from template
        """,
    )
    parser.add_argument("instructions", nargs="?", help="Path to edit instructions YAML")
    parser.add_argument("--audit", action="store_true", help="Audit only — don't render")
    parser.add_argument("--verify", type=float, metavar="TIME",
                        help="Extract a masked verification frame at TIME seconds (source)")
    parser.add_argument("--templates", action="store_true", help="List available templates")
    parser.add_argument("--init", metavar="TEMPLATE", help="Generate starter config from template")
    parser.add_argument("--crf", type=int, help="Override CRF quality (18=lossless, 22=high, 28=draft)")
    parser.add_argument("--no-audio-enhance", action="store_true", help="Disable audio enhancement")

    args = parser.parse_args()

    # List templates
    if args.templates:
        templates = list_templates()
        if not templates:
            print("No templates found.")
            return
        print("\nAvailable templates:\n")
        for t in templates:
            print(f"  {t['name']:<25} {t['description'][:60]}")
        print(f"\nUse --init <name> to generate a starter config.")
        return

    # Generate starter config
    if args.init:
        output_file = f"{args.init}_project.yaml"
        template = load_template(args.init)
        
        starter = {
            "template": args.init,
            "video": "path/to/recording.mp4",
            "vtt": "path/to/transcript.vtt",
            "output": "output.mp4",
            "keep_speakers": ["Speaker 1", "Speaker 2"],
        }
        
        import yaml
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(f"# Generated from template: {args.init}\n")
            f.write(f"# Edit the values below, then run: python sanitize.py {output_file}\n\n")
            yaml.dump(starter, f, default_flow_style=False, sort_keys=False)
        
        print(f"\n  ✅ Created {output_file}")
        print(f"  Edit it with your video path, VTT path, and speaker names.")
        print(f"  Then run: python sanitize.py {output_file} --audit")
        return

    # Need instructions file for everything else
    if not args.instructions:
        parser.print_help()
        return

    # Load instructions
    instr = load_instructions(args.instructions)

    if not instr.video_path:
        print("ERROR: 'video' path not set in instructions file.")
        sys.exit(1)
    if not instr.vtt_path:
        print("ERROR: 'vtt' path not set in instructions file.")
        sys.exit(1)
    if not instr.keep_speakers:
        print("ERROR: 'keep_speakers' not set in instructions file.")
        sys.exit(1)

    # Resolve paths relative to the instructions file
    instr_dir = Path(args.instructions).parent
    video_path = str((instr_dir / instr.video_path).resolve()) if not Path(instr.video_path).is_absolute() else instr.video_path
    vtt_path = str((instr_dir / instr.vtt_path).resolve()) if not Path(instr.vtt_path).is_absolute() else instr.vtt_path
    output_path = str((instr_dir / instr.output_path).resolve()) if not Path(instr.output_path).is_absolute() else instr.output_path

    # Build editor
    editor = MeetingEditor(
        video_path=video_path,
        vtt_path=vtt_path,
        keep_speakers=instr.keep_speakers,
        segments=instr.segments or None,
        layout_overrides=instr.layout_overrides or None,
    )

    # Analyze
    editor.analyze()

    # Verify frame
    if args.verify is not None:
        editor.verify_frame(args.verify)
        return

    # Audit
    editor.audit()

    if args.audit:
        print("\n  [Audit mode — no rendering. Remove --audit to render.]")
        return

    # Render
    crf = args.crf if args.crf is not None else instr.crf
    audio_enhance = not args.no_audio_enhance and instr.audio_enhance
    editor.process(output_path, crf=crf, audio_enhance=audio_enhance)


if __name__ == "__main__":
    main()
