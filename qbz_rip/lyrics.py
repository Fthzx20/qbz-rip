import asyncio
import os
import urllib.parse
from typing import Optional, Dict
import aiohttp

LRCLIB_BASE_URL = "https://lrclib.net/api"

async def fetch_lyrics(title: str, artist: str, album: str = "", duration_sec: int = 0) -> Optional[Dict[str, str]]:
    """
    Fetches synchronized (.lrc) and plain lyrics from LRCLIB open database.
    Does not require any API key.
    Returns dict with keys: 'synced' (LRC formatted), 'plain', 'instrumental' (bool) or None.
    """
    clean_title = (title or "").strip()
    clean_artist = (artist or "").strip()
    clean_album = (album or "").strip()

    if not clean_title or not clean_artist:
        return None

    headers = {
        "User-Agent": "QBZ-Rip/1.0.0 (https://github.com/qbz-rip)"
    }

    params = {
        "track_name": clean_title,
        "artist_name": clean_artist,
    }
    if clean_album:
        params["album_name"] = clean_album
    if duration_sec and duration_sec > 0:
        params["duration"] = str(int(duration_sec))

    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            # 1. Exact match attempt via /api/get
            try:
                async with session.get(f"{LRCLIB_BASE_URL}/get", params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        if data and isinstance(data, dict):
                            synced = data.get("syncedLyrics")
                            plain = data.get("plainLyrics")
                            instrumental = data.get("instrumental", False)
                            if synced or plain or instrumental:
                                return {
                                    "synced": synced or "",
                                    "plain": plain or "",
                                    "instrumental": bool(instrumental)
                                }
            except Exception:
                pass

            # 2. Fuzzy search fallback via /api/search
            q = f"{clean_artist} {clean_title}"
            search_params = {"q": q}
            try:
                async with session.get(f"{LRCLIB_BASE_URL}/search", params=search_params) as resp:
                    if resp.status == 200:
                        items = await resp.json(content_type=None)
                        if isinstance(items, list) and len(items) > 0:
                            best = items[0]
                            synced = best.get("syncedLyrics")
                            plain = best.get("plainLyrics")
                            instrumental = best.get("instrumental", False)
                            if synced or plain or instrumental:
                                return {
                                    "synced": synced or "",
                                    "plain": plain or "",
                                    "instrumental": bool(instrumental)
                                }
            except Exception:
                pass

    except Exception as e:
        print(f"[LRCLIB] Warning: Could not fetch lyrics for {clean_artist} - {clean_title}: {e}")

    return None

def save_lrc_file(audio_filepath: str, lyrics_text: str) -> Optional[str]:
    """
    Saves synchronized lyrics to a .lrc file next to the audio file.
    """
    if not audio_filepath or not lyrics_text:
        return None
    try:
        base, _ = os.path.splitext(audio_filepath)
        lrc_path = f"{base}.lrc"
        with open(lrc_path, "w", encoding="utf-8") as f:
            f.write(lyrics_text.strip() + "\n")
        return lrc_path
    except Exception as e:
        print(f"[LRCLIB] Warning: Failed to save .lrc file: {e}")
        return None
