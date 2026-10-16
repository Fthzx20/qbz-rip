import asyncio
import os
import re
import time
import aiohttp
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TPE2, TDRC, TRCK, TPOS, TSRC, TCOP, TCON, COMM, APIC

def sanitize_filename(name):
    """Sanitizes strings for cross-platform safe file paths, especially on Windows."""
    if not name:
        return "Unknown"
    # Replace illegal characters
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", str(name)).strip()
    # Strip trailing dots and spaces (Windows restriction)
    cleaned = cleaned.rstrip(". ")
    # Reserved device names in Windows
    reserved = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", 
                "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", 
                "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}
    if cleaned.upper() in reserved:
        cleaned = f"{cleaned}_"
    return cleaned or "Unknown"

def clamp_target_path(folder: str, filename: str, max_total_len: int = 245) -> str:
    """
    Clamps filename length so that os.path.join(folder, filename) + '.tmp'
    never exceeds Windows MAX_PATH limit (260 characters).
    """
    folder_abs = os.path.abspath(folder)
    max_fn_len = max(20, max_total_len - len(folder_abs) - 6)
    if len(filename) > max_fn_len:
        base, ext = os.path.splitext(filename)
        allowed_base_len = max(5, max_fn_len - len(ext))
        filename = f"{base[:allowed_base_len].rstrip('. ')}{ext}"
    return os.path.join(folder_abs, filename)

def format_safe_template(template, mapping):
    """Formats a template string safely without crashing if extra keys are present or missing."""
    class SafeDict(dict):
        def __missing__(self, key):
            return "Unknown"
    return template.format_map(SafeDict(mapping))

class DownloadManager:
    """Handles high-speed direct bit-perfect stream downloading and audiophile metadata tagging."""

    def __init__(self, api, config):
        self.api = api
        self.config = config
        self.semaphore = asyncio.Semaphore(self.config.concurrent_downloads)
        self.is_paused = False
        self.is_cancelled = False
        self._folder_locks = {}

    def _get_folder_lock(self, folder):
        """Returns or creates an asyncio.Lock specific to an album folder for thread-safe operations."""
        if not folder:
            return asyncio.Lock()
        norm_key = os.path.normcase(os.path.abspath(folder))
        if norm_key not in self._folder_locks:
            self._folder_locks[norm_key] = asyncio.Lock()
        return self._folder_locks[norm_key]

    def update_concurrency(self, new_val):
        """Dynamically adjusts download concurrency."""
        val = max(1, min(int(new_val), 5))
        self.semaphore = asyncio.Semaphore(val)

    async def download_track(self, track_id, progress_callback=None, task_state=None, parent_folder=None, track_meta=None):
        """Downloads a track at maximum available bit-depth/sample rate, writes tags, and embeds artwork."""
        async with self.semaphore:
            if self.is_cancelled or (task_state and task_state.get("is_cancelled")):
                return False, "Cancelled", None

            clean_tid = str(track_id).strip()
            if not clean_tid.isdigit():
                return False, f"Invalid track ID '{clean_tid}' (album ID detected, cannot stream album directly)", None

            # 1. Fetch metadata if not already supplied
            if not track_meta or not isinstance(track_meta, dict):
                try:
                    track_meta = await self.api.get_track(track_id)
                except Exception as e:
                    err_msg = str(e)
                    if "404" in err_msg or "No result matching" in err_msg:
                        return False, f"Track delisted / unavailable on Q-Buz (404)", None
                    return False, f"Metadata lookup failed: {err_msg[:60]}", None

            if not track_meta or not isinstance(track_meta, dict):
                return False, f"Could not retrieve track metadata for ID {track_id}", None

            album_meta = track_meta.get("album") or {}
            if not isinstance(album_meta, dict):
                album_meta = {}

            title = track_meta.get("title") or f"Track {track_id}"
            performer = track_meta.get("performer") or {}
            if not isinstance(performer, dict):
                performer = {}
            artist = performer.get("name")
            if not artist:
                album_artist_obj = album_meta.get("artist") or {}
                if isinstance(album_artist_obj, dict):
                    artist = album_artist_obj.get("name")
            if not artist:
                artist = "Unknown Artist"

            album_title = album_meta.get("title") or "Unknown Album"
            track_num = track_meta.get("track_number", 1)
            disc_num = track_meta.get("media_number", 1)
            total_tracks = album_meta.get("tracks_count") or 1
            total_discs = album_meta.get("media_count") or 1
            isrc = track_meta.get("isrc") or ""
            copyright_str = album_meta.get("copyright") or ""

            # Genre detection
            genre_obj = album_meta.get("genre") or track_meta.get("genre") or {}
            genre_name = genre_obj.get("name") if isinstance(genre_obj, dict) else str(genre_obj or "")

            # Release Year
            release_date = album_meta.get("release_date_original") or album_meta.get("release_date_download") or ""
            year = release_date[:4] if len(release_date) >= 4 else ""

            try:
                track_num = int(track_num)
            except (ValueError, TypeError):
                track_num = 1
            try:
                disc_num = int(disc_num)
            except (ValueError, TypeError):
                disc_num = 1
            try:
                total_tracks = int(total_tracks)
            except (ValueError, TypeError):
                total_tracks = 1
            try:
                total_discs = int(total_discs)
            except (ValueError, TypeError):
                total_discs = 1

            # 2. Get stream URL (prioritizing 24-bit/192kHz Studio Master)
            if progress_callback:
                progress_callback(0.0, "Requesting Studio Master URL...")

            try:
                stream_info = await self.api.get_file_url(track_id, self.config.format_id)
                stream_url = stream_info.get("url") if isinstance(stream_info, dict) else None
                if not stream_url:
                    return False, "Server returned empty stream URL", None
            except Exception as e:
                err_s = str(e)
                print(f"[Stream Error] Track {track_id}: {err_s}")
                if "404" in err_s:
                    return False, "Stream not found on server (404 / Geo-restricted)", None
                elif "401" in err_s or "403" in err_s or "user_auth_token" in err_s.lower():
                    return False, "Unauthorized stream (Token expired / Login needed)", None
                clean_err = re.sub(r"^Unable to retrieve audio stream URL for track [^:]+:\s*", "", err_s).strip()
                return False, f"Stream failed: {clean_err[:45]}", None

            fmt_id = stream_info.get("format_id", self.config.format_id)
            ext = "flac" if fmt_id in [27, 7, 6] else "mp3"
            bit_depth = stream_info.get("bit_depth") or track_meta.get("maximum_bit_depth") or track_meta.get("bit_depth") or (24 if fmt_id in [27, 7] else 16)
            sample_rate = stream_info.get("sampling_rate") or track_meta.get("maximum_sampling_rate") or track_meta.get("sampling_rate") or (192.0 if fmt_id == 27 else 96.0 if fmt_id == 7 else 44.1)

            # Metadata info for extended tags
            label_name = album_meta.get("label", {}).get("name") if isinstance(album_meta.get("label"), dict) else ""
            composer_name = track_meta.get("composer", {}).get("name") if isinstance(track_meta.get("composer"), dict) else ""
            duration_sec = track_meta.get("duration", 0)

            # Format spec labels
            try:
                s_float = float(sample_rate)
                sr_str = f"{int(s_float)}kHz" if s_float.is_integer() else f"{s_float}kHz"
            except Exception:
                sr_str = f"{sample_rate}kHz"
            bd_str = f"{bit_depth}bit"
            qual_str = f"{bd_str}-{sr_str}"

            # 3. Determine actual destination file path based on returned format (with Windows MAX_PATH safety)
            mapping = {
                "artist": sanitize_filename(artist),
                "album": sanitize_filename(album_title),
                "title": sanitize_filename(title),
                "track_num": f"{track_num:02d}",
                "disc_num": f"{disc_num:02d}",
                "total_tracks": f"{total_tracks:02d}",
                "total_discs": f"{total_discs:02d}",
                "genre": sanitize_filename(genre_name) if genre_name else "Unknown",
                "year": year or "Unknown",
                "bit_depth": bd_str,
                "sample_rate": sr_str,
                "bit_depth_raw": str(bit_depth),
                "sample_rate_raw": str(sample_rate),
                "quality": qual_str,
                "label": sanitize_filename(label_name) if label_name else "Unknown",
                "composer": sanitize_filename(composer_name) if composer_name else "Unknown",
                "isrc": sanitize_filename(isrc) if isrc else "Unknown",
                "ext": ext
            }

            if parent_folder:
                prefix = f"{disc_num}-{track_num:02d}" if disc_num > 1 else f"{track_num:02d}"
                safe_t = sanitize_filename(title)
                safe_a = sanitize_filename(artist)
                folder_base = os.path.basename(os.path.normpath(parent_folder)).lower()
                if safe_a.lower() in folder_base or not safe_a:
                    raw_filename = f"{prefix} - {safe_t}.{ext}"
                else:
                    raw_filename = f"{prefix} - {safe_a} - {safe_t}.{ext}"
                target_path = clamp_target_path(parent_folder, raw_filename)
            else:
                rel_path = format_safe_template(self.config.naming_template, mapping)
                rel_dir = os.path.dirname(rel_path)
                rel_file = os.path.basename(rel_path)
                target_dir = os.path.join(self.config.download_directory, rel_dir)
                target_path = clamp_target_path(target_dir, rel_file)

            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            tmp_path = f"{target_path}.tmp"

            # 4. Fast Sync Skip check (avoids redundant re-download)
            if os.path.exists(target_path) and os.path.getsize(target_path) > 100000:
                spec_label = f"{bit_depth}-bit/{sample_rate}kHz {ext.upper()}"
                if progress_callback:
                    progress_callback(1.0, f"Already exists ({spec_label})")
                return True, f"Skipped (Exists) • {spec_label}", target_path

            # 5. Direct Stream Download with CDN bypass headers, Range resume support, and retry loop
            session = await self.api.get_session()
            start_time = time.time()
            downloaded_bytes = 0
            total_bytes = 0
            last_ui_update = 0
            max_retries = 3

            for attempt in range(max_retries):
                if self.is_cancelled or (task_state and task_state.get("is_cancelled")):
                    if os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass
                    return False, "Cancelled", None

                dl_headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "*/*",
                    "Accept-Encoding": "identity",
                    "Referer": "https://play.qobuz.com/",
                }

                if downloaded_bytes > 0:
                    dl_headers["Range"] = f"bytes={downloaded_bytes}-"
                    file_mode = "ab"
                else:
                    file_mode = "wb"

                stream_timeout = aiohttp.ClientTimeout(total=None, sock_read=45, sock_connect=15)
                try:
                    async with session.get(stream_url, headers=dl_headers, timeout=stream_timeout) as resp:
                        if resp.status not in (200, 206):
                            raise Exception(f"Stream server returned status {resp.status}")

                        if resp.status == 200 and downloaded_bytes > 0:
                            # Server ignored Range header, restarting from byte 0
                            downloaded_bytes = 0
                            file_mode = "wb"
                            total_bytes = int(resp.headers.get("Content-Length", 0))

                        if not total_bytes:
                            if "Content-Range" in resp.headers:
                                cr = resp.headers.get("Content-Range", "")
                                m_cr = re.search(r"/(\d+)", cr)
                                if m_cr:
                                    total_bytes = int(m_cr.group(1))
                            if not total_bytes:
                                cl = int(resp.headers.get("Content-Length", 0))
                                total_bytes = (downloaded_bytes + cl) if cl > 0 else 0

                        with open(tmp_path, file_mode) as f:
                            async for chunk in resp.content.iter_chunked(128 * 1024):
                                # Check pause / cancel
                                while self.is_paused or (task_state and task_state.get("is_paused")):
                                    if self.is_cancelled or (task_state and task_state.get("is_cancelled")):
                                        break
                                    await asyncio.sleep(0.5)

                                if self.is_cancelled or (task_state and task_state.get("is_cancelled")):
                                    raise asyncio.CancelledError("Download cancelled by user.")

                                f.write(chunk)
                                downloaded_bytes += len(chunk)

                                # Throttled progress callback
                                now = time.time()
                                if progress_callback and (now - last_ui_update >= 0.25 or (total_bytes > 0 and downloaded_bytes == total_bytes)):
                                    last_ui_update = now
                                    percent = (downloaded_bytes / total_bytes) if total_bytes > 0 else 0.5
                                    elapsed = now - start_time
                                    speed_kb = (downloaded_bytes / 1024) / elapsed if elapsed > 0 else 0
                                    if speed_kb > 1024:
                                        speed_str = f"{speed_kb / 1024:.1f} MB/s"
                                    else:
                                        speed_str = f"{speed_kb:.0f} KB/s"

                                    if total_bytes > 0:
                                        progress_callback(percent, f"{speed_str} • {percent * 100:.0f}%")
                                    else:
                                        mb_str = f"{downloaded_bytes / (1024*1024):.1f} MB"
                                        progress_callback(0.5, f"{speed_str} • {mb_str}")

                    # Verify if stream completed fully
                    if (total_bytes > 0 and downloaded_bytes >= total_bytes) or (total_bytes == 0 and downloaded_bytes > 100000):
                        break

                except asyncio.CancelledError:
                    if os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass
                    return False, "Cancelled", None

                except Exception as ex:
                    if self.is_cancelled or (task_state and task_state.get("is_cancelled")):
                        if os.path.exists(tmp_path):
                            try:
                                os.remove(tmp_path)
                            except Exception:
                                pass
                        return False, "Cancelled", None

                    if attempt < max_retries - 1:
                        await asyncio.sleep(1.0 * (attempt + 1))
                        if progress_callback:
                            progress_callback(
                                (downloaded_bytes / total_bytes) if total_bytes > 0 else 0.5,
                                f"Reconnecting (retry {attempt + 1}/{max_retries})..."
                            )
                        continue
                    else:
                        if os.path.exists(tmp_path):
                            try:
                                os.remove(tmp_path)
                            except Exception:
                                pass
                        raise ex

            # Verify downloaded audio payload integrity
            if total_bytes > 0 and downloaded_bytes < total_bytes:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise Exception(f"Incomplete download: received {downloaded_bytes}/{total_bytes} bytes. Stream was truncated.")

            actual_size = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
            if actual_size < 1024:
                err_sample = ""
                try:
                    with open(tmp_path, "r", errors="ignore") as ef:
                        err_sample = ef.read(200)
                except Exception:
                    pass
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise Exception(f"Downloaded audio stream is empty or corrupt ({actual_size} bytes): {err_sample}")

            # 6. Embed Audiophile Metadata & Artwork
            if progress_callback:
                progress_callback(0.99, "Writing audiophile tags & artwork...")

            # Fetch high-resolution cover art
            cover_data = None
            cover_obj = album_meta.get("image") or {}
            cover_url = None
            if isinstance(cover_obj, dict):
                cover_url = cover_obj.get("large") or cover_obj.get("small") or cover_obj.get("thumbnail")
            elif isinstance(cover_obj, str):
                cover_url = cover_obj

            if cover_url:
                try:
                    async with session.get(cover_url, timeout=aiohttp.ClientTimeout(total=10)) as c_resp:
                        if c_resp.status == 200:
                            cover_data = await c_resp.read()
                except Exception as e:
                    print(f"Failed to fetch cover image: {e}")

            # Concurrency-safe folder operations: cover.jpg and Digital Booklet.pdf (A 1)
            if parent_folder:
                os.makedirs(parent_folder, exist_ok=True)
                folder_lock = self._get_folder_lock(parent_folder)
                async with folder_lock:
                    # Save folder artwork cover.jpg for audiophile library browsers
                    if cover_data:
                        try:
                            cover_path = os.path.join(parent_folder, "cover.jpg")
                            if not os.path.exists(cover_path):
                                with open(cover_path, "wb") as cf:
                                    cf.write(cover_data)
                        except Exception as e:
                            print(f"Failed to write album cover.jpg: {e}")

                    # Download Official Digital Booklet PDF if available in album goodies (A 1)
                    goodies = album_meta.get("goodies")
                    if not goodies and album_meta.get("id"):
                        try:
                            full_alb = await self.api.get_album(album_meta["id"])
                            if isinstance(full_alb, dict) and full_alb.get("goodies"):
                                goodies = full_alb["goodies"]
                        except Exception:
                            pass

                    if goodies:
                        try:
                            for goody in goodies:
                                g_url = goody.get("url")
                                g_name = goody.get("name") or goody.get("original_filename") or "Digital Booklet.pdf"
                                g_mime = str(goody.get("mime_type") or "").lower()
                                g_desc = str(goody.get("description") or "").lower()
                                
                                is_pdf_goody = (
                                    ".pdf" in str(g_url).lower()
                                    or ".pdf" in str(g_name).lower()
                                    or "booklet" in str(g_name).lower()
                                    or "livret" in str(g_name).lower()
                                    or "booklet" in g_desc
                                    or "pdf" in g_mime
                                    or str(goody.get("file_format_id")) in ["21", "22"]
                                )

                                if g_url and is_pdf_goody:
                                    pdf_filename = sanitize_filename(g_name)
                                    if not pdf_filename.lower().endswith(".pdf"):
                                        pdf_filename += ".pdf"
                                    pdf_path = clamp_target_path(parent_folder, pdf_filename)
                                    if not os.path.exists(pdf_path):
                                        async with session.get(g_url, timeout=aiohttp.ClientTimeout(total=60)) as b_resp:
                                            if b_resp.status == 200:
                                                with open(pdf_path, "wb") as bf:
                                                    async for chunk in b_resp.content.iter_chunked(128 * 1024):
                                                        bf.write(chunk)
                                                print(f"[Q-Buz Downloader] Downloaded Digital Booklet: {pdf_filename}")
                        except Exception as e:
                            print(f"Failed to write digital booklet PDF: {e}")

            # Fetch Synced Lyrics from LRCLIB
            lyrics_info = None
            lrc_to_save = None
            try:
                from .lyrics import fetch_lyrics
                lyrics_info = await fetch_lyrics(title, artist, album_title, int(duration_sec or 0))
                if lyrics_info:
                    lrc_to_save = lyrics_info.get("synced") or lyrics_info.get("plain")
            except Exception as e:
                print(f"Lyrics lookup error: {e}")

            # Apply tags with exception isolation
            try:
                if ext == "flac":
                    audio = FLAC(tmp_path)
                    # Extract true bitstream specs directly from decoded FLAC STREAMINFO header
                    true_bit_depth = getattr(audio.info, "bits_per_sample", bit_depth)
                    true_sample_rate = getattr(audio.info, "sample_rate", int(sample_rate * 1000)) / 1000.0
                    bit_depth = true_bit_depth
                    sample_rate = true_sample_rate

                    audio["TITLE"] = str(title)
                    audio["ARTIST"] = str(artist)
                    audio["ALBUM"] = str(album_title)
                    alb_art_name = album_meta.get("artist", {}).get("name") if isinstance(album_meta.get("artist"), dict) else artist
                    audio["ALBUMARTIST"] = str(alb_art_name or artist)
                    audio["TRACKNUMBER"] = str(track_num)
                    audio["TRACKTOTAL"] = str(album_meta.get("tracks_count") or track_num)
                    audio["DISCNUMBER"] = str(disc_num)
                    audio["DISCTOTAL"] = str(album_meta.get("media_count") or disc_num)
                    if year:
                        audio["DATE"] = str(year)
                        audio["YEAR"] = str(year)
                    if isrc:
                        audio["ISRC"] = str(isrc)
                    if copyright_str:
                        audio["COPYRIGHT"] = str(copyright_str)

                    composer = track_meta.get("composer", {}).get("name") if isinstance(track_meta.get("composer"), dict) else None
                    if composer:
                        audio["COMPOSER"] = str(composer)

                    genre = album_meta.get("genre", {}).get("name") if isinstance(album_meta.get("genre"), dict) else None
                    if genre:
                        audio["GENRE"] = str(genre)

                    try:
                        s_fl = float(sample_rate)
                        sr_tag = f"{int(s_fl)}kHz" if s_fl.is_integer() else f"{s_fl}kHz"
                    except Exception:
                        sr_tag = f"{sample_rate}kHz"
                    spec_tag = f"Q-Buz Studio Master • {bit_depth}-bit/{sr_tag}"
                    audio["COMMENT"] = spec_tag

                    # Embed Vorbis lyrics
                    if lyrics_info:
                        if lyrics_info.get("synced"):
                            audio["LYRICS"] = str(lyrics_info["synced"])
                        if lyrics_info.get("plain"):
                            audio["UNSYNCEDLYRICS"] = str(lyrics_info["plain"])

                    if cover_data:
                        pic = Picture()
                        pic.data = cover_data
                        pic.type = 3  # Cover Front
                        pic.mime = "image/png" if cover_data.startswith(b"\x89PNG") else "image/jpeg"
                        pic.desc = "Front Cover"
                        audio.clear_pictures()
                        audio.add_picture(pic)

                    audio.save()

                elif ext == "mp3":
                    try:
                        audio = ID3(tmp_path)
                    except Exception:
                        audio = ID3()

                    audio.add(TIT2(encoding=3, text=str(title)))
                    audio.add(TPE1(encoding=3, text=str(artist)))
                    alb_art_name = album_meta.get("artist", {}).get("name") if isinstance(album_meta.get("artist"), dict) else artist
                    if alb_art_name:
                        audio.add(TPE2(encoding=3, text=str(alb_art_name)))
                    audio.add(TALB(encoding=3, text=str(album_title)))
                    total_tracks_val = album_meta.get("tracks_count")
                    trck_str = f"{track_num}/{total_tracks_val}" if total_tracks_val else str(track_num)
                    audio.add(TRCK(encoding=3, text=trck_str))
                    total_discs_val = album_meta.get("media_count")
                    tpos_str = f"{disc_num}/{total_discs_val}" if total_discs_val else str(disc_num)
                    audio.add(TPOS(encoding=3, text=tpos_str))
                    if year:
                        audio.add(TDRC(encoding=3, text=str(year)))
                    if isrc:
                        audio.add(TSRC(encoding=3, text=str(isrc)))
                    if copyright_str:
                        audio.add(TCOP(encoding=3, text=str(copyright_str)))
                    genre = album_meta.get("genre", {}).get("name") if isinstance(album_meta.get("genre"), dict) else None
                    if genre:
                        audio.add(TCON(encoding=3, text=str(genre)))
                    audio.add(COMM(encoding=3, lang="eng", desc="", text="Q-Buz Studio Master"))
                    if cover_data:
                        audio.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_data))
                    if lyrics_info and (lyrics_info.get("plain") or lyrics_info.get("synced")):
                        from mutagen.id3 import USLT
                        audio.add(USLT(encoding=3, lang='eng', desc='Lyrics', text=str(lyrics_info.get("plain") or lyrics_info.get("synced"))))
                    audio.save(tmp_path)

            except Exception as e:
                print(f"Warning: Metadata tagging issue for {tmp_path}: {e}")
            finally:
                audio = None
                cover_data = None
                lyrics_info = None

            # 7. Safe Windows Atomic Rename
            renamed = False
            for _ in range(5):
                try:
                    if os.path.exists(target_path):
                        try:
                            os.remove(target_path)
                        except Exception:
                            pass
                    os.replace(tmp_path, target_path)
                    renamed = True
                    break
                except Exception:
                    await asyncio.sleep(0.2)

            if not renamed and os.path.exists(tmp_path):
                try:
                    os.replace(tmp_path, target_path)
                    renamed = True
                except Exception:
                    try:
                        import shutil
                        shutil.copy2(tmp_path, target_path)
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass
                        renamed = True
                    except Exception as e:
                        raise e

            # Save companion .lrc file if lyrics were retrieved
            if os.path.exists(target_path) and lrc_to_save:
                try:
                    from .lyrics import save_lrc_file
                    save_lrc_file(target_path, lrc_to_save)
                except Exception as e:
                    print(f"Failed to write .lrc file: {e}")

            # 8. Checksum verification & album checksums.md5 generation (A 4) with folder lock
            if parent_folder and os.path.exists(target_path):
                folder_lock = self._get_folder_lock(parent_folder)
                async with folder_lock:
                    try:
                        import hashlib
                        hasher = hashlib.md5()
                        with open(target_path, "rb") as af:
                            while chunk := af.read(128 * 1024):
                                hasher.update(chunk)
                        md5_val = hasher.hexdigest()
                        base_name = os.path.basename(target_path)
                        chk_file = os.path.join(parent_folder, "checksums.md5")
                        existing = ""
                        if os.path.exists(chk_file):
                            with open(chk_file, "r", encoding="utf-8", errors="ignore") as rf:
                                existing = rf.read()
                        if base_name not in existing:
                            with open(chk_file, "a", encoding="utf-8") as wf:
                                wf.write(f"{md5_val} *{base_name}\n")
                    except Exception as e:
                        print(f"Warning: Failed to write MD5 checksum: {e}")

            try:
                s_fl = float(sample_rate)
                sr_disp = f"{int(s_fl)}kHz" if s_fl.is_integer() else f"{s_fl}kHz"
            except Exception:
                sr_disp = f"{sample_rate}kHz"
            spec_desc = f"{bit_depth}-bit/{sr_disp} FLAC" if ext == "flac" else "320kbps MP3"
            if progress_callback:
                progress_callback(1.0, f"Completed ({spec_desc})")

            return True, f"Completed ({spec_desc})", target_path
