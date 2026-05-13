"""
Auto Music — Fetch royalty-free background music from Pixabay.
===============================================================
Downloads ambient/corporate/tech tracks for video backgrounds.
No attribution required (Pixabay license).

Usage:
    from music import fetch_music

    # Auto-select based on mood
    track_path = fetch_music(mood="corporate", duration_range=(60, 120))

    # Or specify a search term
    track_path = fetch_music(query="ambient technology", output_dir="./music")
"""

import os
import requests
from pathlib import Path

# Pixabay API (free tier, 100 requests/min)
PIXABAY_API_URL = "https://pixabay.com/api/audio/"

# Mood → search term mapping for automatic selection
MOOD_MAP = {
    "corporate": "corporate technology upbeat",
    "tech": "technology digital modern",
    "ambient": "ambient calm atmospheric",
    "upbeat": "upbeat positive energy",
    "inspirational": "inspirational motivational",
    "minimal": "minimal electronic soft",
    "cinematic": "cinematic epic dramatic",
    "chill": "lofi chill relaxing",
}

# Default music cache directory
MUSIC_CACHE = Path(__file__).parent / "_music_cache"


def fetch_music(
    query: str = None,
    mood: str = "tech",
    duration_range: tuple = (60, 180),
    api_key: str = None,
    output_dir: str = None,
    verbose: bool = True,
) -> str:
    """Fetch a royalty-free music track from Pixabay.

    Args:
        query: Direct search query (overrides mood)
        mood: Mood preset (corporate, tech, ambient, upbeat, inspirational, minimal, cinematic, chill)
        duration_range: (min_seconds, max_seconds) for track length
        api_key: Pixabay API key (or set PIXABAY_API_KEY env var)
        output_dir: Where to save the track (default: _music_cache/)
        verbose: Print progress

    Returns:
        Path to downloaded MP3 file, or None if no API key / no results.
    """
    # Resolve API key
    key = api_key or os.environ.get("PIXABAY_API_KEY", "")
    if not key:
        if verbose:
            print("  ⚠ No Pixabay API key. Set PIXABAY_API_KEY env var or pass api_key=")
            print("    Get a free key at: https://pixabay.com/api/docs/")
            print("    Skipping background music.")
        return None

    # Resolve query
    if not query:
        query = MOOD_MAP.get(mood, MOOD_MAP["tech"])

    # Output directory
    cache_dir = Path(output_dir) if output_dir else MUSIC_CACHE
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Check cache first
    cache_key = query.replace(" ", "_")[:30]
    cached = list(cache_dir.glob(f"{cache_key}*.mp3"))
    if cached:
        if verbose:
            print(f"  ♪ Using cached: {cached[0].name}")
        return str(cached[0])

    # Search Pixabay
    params = {
        "key": key,
        "q": query,
        "per_page": 10,
    }

    if verbose:
        print(f"  ♪ Searching Pixabay for: \"{query}\"...")

    try:
        resp = requests.get(PIXABAY_API_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        if verbose:
            print(f"  ⚠ Music fetch failed: {e}")
        return None

    hits = data.get("hits", [])
    if not hits:
        if verbose:
            print(f"  ⚠ No tracks found for \"{query}\"")
        return None

    # Filter by duration
    min_dur, max_dur = duration_range
    candidates = [h for h in hits if min_dur <= h.get("duration", 0) <= max_dur]
    if not candidates:
        # Fall back to any track
        candidates = hits

    # Pick the best match (first result, usually most relevant)
    track = candidates[0]
    audio_url = track.get("audio_url") or track.get("url")

    if not audio_url:
        if verbose:
            print(f"  ⚠ No download URL for track")
        return None

    # Download
    filename = f"{cache_key}_{track.get('id', 'track')}.mp3"
    output_path = str(cache_dir / filename)

    if verbose:
        dur = track.get("duration", 0)
        print(f"  ♪ Downloading: {track.get('tags', 'untitled')} ({dur}s)")

    try:
        audio_resp = requests.get(audio_url, timeout=30)
        audio_resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(audio_resp.content)
    except (requests.RequestException, IOError) as e:
        if verbose:
            print(f"  ⚠ Download failed: {e}")
        return None

    if verbose:
        size = os.path.getsize(output_path) / 1024 / 1024
        print(f"  ♪ Saved: {filename} ({size:.1f} MB)")

    return output_path


def list_moods() -> list[str]:
    """List available mood presets."""
    return list(MOOD_MAP.keys())
