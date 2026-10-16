import asyncio
import html
import json
import re
import ssl
import urllib.parse
import urllib.request

def get_ssl_context():
    """Returns an SSL context with fallback for unbundled Windows root certificates."""
    try:
        return ssl.create_default_context()
    except Exception:
        return ssl._create_unverified_context()

def http_get_sync(url, headers=None, timeout=12):
    """
    Robust synchronous HTTP GET with realistic browser headers,
    redirect handling, and automatic SSL verification fallback on Windows.
    Returns: (content_string, final_url)
    """
    default_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    if headers:
        default_headers.update(headers)

    req = urllib.request.Request(url, headers=default_headers)
    ctx = get_ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            charset = resp.headers.get_content_charset() or 'utf-8'
            return resp.read().decode(charset, errors='ignore'), resp.geturl()
    except Exception:
        # Fallback to unverified SSL context if certificate verification fails on Windows
        unverified_ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=timeout, context=unverified_ctx) as resp:
            charset = resp.headers.get_content_charset() or 'utf-8'
            return resp.read().decode(charset, errors='ignore'), resp.geturl()

def parse_qobuz_url(text):
    """
    Parses a direct Qobuz URL or ID string.
    Supports open.qobuz.com, play.qobuz.com, and www.qobuz.com with any locale prefix.
    Returns: (type, id) e.g. ('track', '12345'), ('album', 'xxxx'), or (None, None).
    """
    if not isinstance(text, str):
        return None, None
    t = text.strip()

    # Direct raw numeric ID or UPC barcode (e.g. 12345678, 0060253786968)
    if re.fullmatch(r"\d{6,14}", t):
        return "raw_id", t

    # Alphanumeric Album ID (e.g. es45w03nwb5eb - 11 to 14 alphanumeric chars)
    if re.fullmatch(r"[a-z0-9]{11,14}", t, re.I) and not t.isdigit():
        return "album", t

    # Strip query parameters (?...) and URL fragments (#...)
    clean_t = re.sub(r"[?#].*$", "", t).rstrip("/")

    # Track URLs: .../track/.../12345 or .../track/12345
    m = re.search(r"q-?obuz\.com/(?:[a-zA-Z]{2}(?:-[a-zA-Z]{2})?/)?track/(?:.*/)?([a-zA-Z0-9_\-]+)", clean_t, re.I)
    if m:
        return "track", m.group(1)

    # Album URLs: .../album/.../xxxx or .../album/xxxx
    m = re.search(r"q-?obuz\.com/(?:[a-zA-Z]{2}(?:-[a-zA-Z]{2})?/)?album/(?:.*/)?([a-zA-Z0-9_\-]+)", clean_t, re.I)
    if m:
        return "album", m.group(1)

    # Playlist URLs: .../playlist/xxxx
    m = re.search(r"q-?obuz\.com/(?:[a-zA-Z]{2}(?:-[a-zA-Z]{2})?/)?playlist/(?:.*/)?([a-zA-Z0-9_\-]+)", clean_t, re.I)
    if m:
        return "playlist", m.group(1)

    # Artist / Interpreter URLs: .../interpreter/xxxx, .../interpret/xxxx, .../artist/xxxx
    m = re.search(r"q-?obuz\.com/(?:[a-zA-Z]{2}(?:-[a-zA-Z]{2})?/)?(?:interpreter|interpret|artist)/(?:.*/)?([a-zA-Z0-9_\-]+)", clean_t, re.I)
    if m:
        return "artist", m.group(1)

    return None, None

def is_external_music_link(text):
    """Detects if input text is an external music streaming URL."""
    if not isinstance(text, str):
        return False
    t = text.strip().lower()
    return any(domain in t for domain in [
        "spotify.com", "open.spotify.com", "spotify:", "spotify.link", "spoti.fi",
        "music.apple.com", "itunes.apple.com", "apple.co",
        "tidal.com",
        "youtube.com", "youtu.be", "music.youtube.com",
        "deezer.com", "deezer.page.link",
        "soundcloud.com", "on.soundcloud.com",
        "music.amazon.com", "amazon.com/music", "a.co", "amzn.to",
        "bandcamp.com"
    ])

def clean_music_title(title):
    """Cleans common video tags, remaster brackets, and noise from titles."""
    if not title:
        return ""
    t = html.unescape(title)
    t = re.sub(
        r"\s*[\(\[](?:Official Music Video|Official Video|Official Audio|Music Video|Official Visualizer|Visualizer|Lyrics|Lyric Video|Audio|4K Remaster|Remastered \d+|Remastered|HD|Video|Clip Officiel)[\)\]]",
        "",
        t,
        flags=re.I
    )
    return t.strip(" -\"'")

def follow_redirects_sync(url):
    """Follows HTTP redirects (e.g. mobile shortlinks like spotify.link, apple.co) to destination URL."""
    try:
        _, final_url = http_get_sync(url, timeout=8)
        return final_url
    except Exception as e:
        print(f"[LinkResolver] Redirect resolution error for {url}: {e}")
        return url

async def resolve_external_link(url):
    """
    Resolves external music streaming links to a clean search query for Qobuz.
    Returns: (search_query, search_type, display_info, service_name)
    """
    url = url.strip()

    # 0. Follow mobile shortlink redirects
    shortlink_domains = ["spotify.link", "spoti.fi", "apple.co", "deezer.page.link", "on.soundcloud.com", "a.co", "amzn.to"]
    if any(d in url.lower() for d in shortlink_domains):
        url = await asyncio.to_thread(follow_redirects_sync, url)

    # 1. SPOTIFY
    if "spotify.com" in url or url.startswith("spotify:"):
        # Convert URI (e.g. spotify:track:4cOdK2wGLETKBW3PvgPWqT) to URL
        if url.startswith("spotify:"):
            parts = url.split(":")
            if len(parts) >= 3:
                url = f"https://open.spotify.com/{parts[1]}/{parts[2]}"

        clean_url = re.sub(r"[?#].*$", "", url)
        
        # Extract entity type and ID
        m = re.search(r"open\.spotify\.com/(track|album|playlist|artist)/([a-zA-Z0-9]+)", clean_url)
        if m:
            entity_type, entity_id = m.group(1), m.group(2)
            
            # Method A: Spotify Embed JSON (__NEXT_DATA__) - 100% reliable, zero bot blocks
            embed_url = f"https://open.spotify.com/embed/{entity_type}/{entity_id}"
            try:
                embed_html, _ = await asyncio.to_thread(http_get_sync, embed_url)
                next_m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', embed_html, re.DOTALL)
                if next_m:
                    data = json.loads(next_m.group(1))
                    entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
                    if entity:
                        name = entity.get("title") or entity.get("name") or ""
                        clean_name = clean_music_title(name)
                        artists = [a.get("name") for a in entity.get("artists", []) if a.get("name")]
                        artist_str = ", ".join(artists) if artists else ""
                        
                        if entity_type == "track":
                            search_q = f"{artist_str} {clean_name}".strip() if artist_str else clean_name
                            return search_q, "tracks", f"Spotify Track: {clean_name} by {artist_str}", "Spotify"
                        elif entity_type == "album":
                            search_q = f"{artist_str} {clean_name}".strip() if artist_str else clean_name
                            return search_q, "albums", f"Spotify Album: {clean_name} by {artist_str}", "Spotify"
                        elif entity_type == "playlist":
                            return clean_name, "playlists", f"Spotify Playlist: {clean_name}", "Spotify"
                        elif entity_type == "artist":
                            return clean_name, "artists", f"Spotify Artist: {clean_name}", "Spotify"
            except Exception as e:
                print(f"[LinkResolver] Spotify embed parsing exception: {e}")

            # Method B: Official Spotify oEmbed API Fallback
            try:
                oembed_url = f"https://open.spotify.com/oembed?url={urllib.parse.quote(clean_url)}"
                oembed_json_str, _ = await asyncio.to_thread(http_get_sync, oembed_url)
                oembed_data = json.loads(oembed_json_str)
                raw_title = clean_music_title(oembed_data.get("title", ""))
                
                cat = "tracks" if entity_type == "track" else "albums" if entity_type == "album" else "playlists" if entity_type == "playlist" else "artists"
                return raw_title, cat, f"Spotify {entity_type.capitalize()}: {raw_title}", "Spotify"
            except Exception as e:
                print(f"[LinkResolver] Spotify oembed fallback exception: {e}")

    # 2. APPLE MUSIC / ITUNES
    elif "music.apple.com" in url or "itunes.apple.com" in url:
        clean_url = url
        track_match = re.search(r"[?&]i=(\d+)", clean_url)
        song_match = re.search(r"/(?:song)/[^/]+/(\d+)", clean_url)
        album_match = re.search(r"/album/(?:[^/]+/)?(\d+)", clean_url)
        artist_match = re.search(r"/artist/(?:[^/]+/)?(\d+)", clean_url)
        slug_match = re.search(r"/(?:album|song|artist)/([^/]+)/(\d+)", clean_url)
        slug_title = html.unescape(slug_match.group(1).replace("-", " ")) if slug_match else ""

        try:
            # Case A: Track ID in album URL (?i=...) or direct song URL
            target_track_id = track_match.group(1) if track_match else (song_match.group(1) if song_match else None)
            if target_track_id:
                api_url = f"https://itunes.apple.com/lookup?id={target_track_id}&entity=song"
                data_str, _ = await asyncio.to_thread(http_get_sync, api_url)
                data = json.loads(data_str)
                results = data.get("results", [])
                if results:
                    trk = results[0]
                    track_name = clean_music_title(trk.get("trackName", slug_title))
                    artist_name = trk.get("artistName", "")
                    return f"{artist_name} {track_name}".strip(), "tracks", f"Apple Music Track: {track_name} by {artist_name}", "Apple Music"

            # Case B: Album URL
            if album_match:
                aid = album_match.group(1)
                api_url = f"https://itunes.apple.com/lookup?id={aid}"
                data_str, _ = await asyncio.to_thread(http_get_sync, api_url)
                data = json.loads(data_str)
                results = data.get("results", [])
                if results:
                    alb = results[0]
                    collection_name = clean_music_title(alb.get("collectionName", slug_title))
                    artist_name = alb.get("artistName", "")
                    return f"{artist_name} {collection_name}".strip(), "albums", f"Apple Music Album: {collection_name} by {artist_name}", "Apple Music"

            # Case C: Artist URL
            if artist_match:
                art_id = artist_match.group(1)
                api_url = f"https://itunes.apple.com/lookup?id={art_id}"
                data_str, _ = await asyncio.to_thread(http_get_sync, api_url)
                data = json.loads(data_str)
                results = data.get("results", [])
                if results:
                    artist_name = results[0].get("artistName", slug_title)
                    return artist_name, "artists", f"Apple Music Artist: {artist_name}", "Apple Music"

            if slug_title:
                cat = "tracks" if "/song/" in url else "albums" if "/album/" in url else "artists"
                return slug_title, cat, f"Apple Music: {slug_title}", "Apple Music"
        except Exception as e:
            print(f"[LinkResolver] Apple Music resolution error: {e}")

    # 3. TIDAL
    elif "tidal.com" in url:
        m = re.search(r"tidal\.com/(?:browse/)?(track|album|artist|playlist)/([a-zA-Z0-9\-]+)", url)
        if m:
            t_type, t_id = m.group(1), m.group(2)
            try:
                html_text, _ = await asyncio.to_thread(http_get_sync, url)
                title_m = re.search(r'<meta (?:property|name)="og:title" content="([^"]+)"', html_text)
                if title_m:
                    raw_title = html.unescape(title_m.group(1))
                    # Tidal format: "Title by Artist on TIDAL" or "Title on TIDAL"
                    clean_t = re.sub(r"\s+on TIDAL.*$", "", raw_title, flags=re.I).strip()
                    clean_t = re.sub(r"\s*\|\s*TIDAL.*$", "", clean_t, flags=re.I).strip()

                    cat = "tracks" if t_type == "track" else "albums" if t_type == "album" else "playlists" if t_type == "playlist" else "artists"
                    if " by " in clean_t:
                        t_parts = clean_t.split(" by ", 1)
                        query_term = f"{t_parts[1].strip()} {clean_music_title(t_parts[0].strip())}"
                        return query_term, cat, f"Tidal: {clean_t}", "Tidal"
                    else:
                        return clean_music_title(clean_t), cat, f"Tidal: {clean_t}", "Tidal"
            except Exception as e:
                print(f"[LinkResolver] Tidal resolution error: {e}")

    # 4. YOUTUBE / YOUTUBE MUSIC
    elif "youtube.com" in url or "youtu.be" in url:
        try:
            api_url = f"https://www.youtube.com/oembed?url={urllib.parse.quote(url)}&format=json"
            data_str, _ = await asyncio.to_thread(http_get_sync, api_url)
            data = json.loads(data_str)
            raw_title = html.unescape(data.get("title", ""))
            author = html.unescape(data.get("author_name", "")).replace(" - Topic", "").strip()
            clean_title = clean_music_title(raw_title)

            # Check if title has "Artist - Song" pattern
            if " - " in clean_title:
                return clean_title, "tracks", f"YouTube Track: {clean_title}", "YouTube"
            elif author and author.lower() not in clean_title.lower():
                return f"{author} {clean_title}".strip(), "tracks", f"YouTube Track: {clean_title} by {author}", "YouTube"
            else:
                return clean_title, "tracks", f"YouTube Track: {clean_title}", "YouTube"
        except Exception as e:
            print(f"[LinkResolver] YouTube resolution error: {e}")

    # 5. DEEZER
    elif "deezer.com" in url:
        try:
            t_m = re.search(r"/track/(\d+)", url)
            a_m = re.search(r"/album/(\d+)", url)
            art_m = re.search(r"/artist/(\d+)", url)
            pl_m = re.search(r"/playlist/(\d+)", url)

            if t_m:
                api_url = f"https://api.deezer.com/track/{t_m.group(1)}"
                data_str, _ = await asyncio.to_thread(http_get_sync, api_url)
                data = json.loads(data_str)
                title = clean_music_title(html.unescape(data.get("title", "")))
                artist = html.unescape(data.get("artist", {}).get("name", ""))
                isrc = data.get("isrc")
                query_term = isrc if isrc else f"{artist} {title}".strip()
                desc = f"Deezer Track: {title} by {artist}" + (f" [ISRC: {isrc}]" if isrc else "")
                return query_term, "tracks", desc, "Deezer"
            elif a_m:
                api_url = f"https://api.deezer.com/album/{a_m.group(1)}"
                data_str, _ = await asyncio.to_thread(http_get_sync, api_url)
                data = json.loads(data_str)
                title = clean_music_title(html.unescape(data.get("title", "")))
                artist = html.unescape(data.get("artist", {}).get("name", ""))
                upc = data.get("upc")
                query_term = upc if upc else f"{artist} {title}".strip()
                desc = f"Deezer Album: {title} by {artist}" + (f" [UPC: {upc}]" if upc else "")
                return query_term, "albums", desc, "Deezer"
            elif art_m:
                api_url = f"https://api.deezer.com/artist/{art_m.group(1)}"
                data_str, _ = await asyncio.to_thread(http_get_sync, api_url)
                data = json.loads(data_str)
                artist = html.unescape(data.get("name", ""))
                return artist, "artists", f"Deezer Artist: {artist}", "Deezer"
            elif pl_m:
                api_url = f"https://api.deezer.com/playlist/{pl_m.group(1)}"
                data_str, _ = await asyncio.to_thread(http_get_sync, api_url)
                data = json.loads(data_str)
                title = html.unescape(data.get("title", ""))
                return title, "playlists", f"Deezer Playlist: {title}", "Deezer"
        except Exception as e:
            print(f"[LinkResolver] Deezer resolution error: {e}")

    # 6. SOUNDCLOUD
    elif "soundcloud.com" in url:
        try:
            api_url = f"https://soundcloud.com/oembed?url={urllib.parse.quote(url)}&format=json"
            data_str, _ = await asyncio.to_thread(http_get_sync, api_url)
            data = json.loads(data_str)
            title = clean_music_title(html.unescape(data.get("title", "")))
            author = html.unescape(data.get("author_name", ""))
            return f"{author} {title}".strip(), "tracks", f"SoundCloud: {title} by {author}", "SoundCloud"
        except Exception as e:
            print(f"[LinkResolver] SoundCloud resolution error: {e}")

    # 7. BANDCAMP
    elif "bandcamp.com" in url:
        try:
            html_text, final_url = await asyncio.to_thread(http_get_sync, url)
            og_title_m = re.search(r'<meta (?:property|name)="og:title" content="([^"]+)"', html_text, re.I)
            if og_title_m:
                raw_title = html.unescape(og_title_m.group(1))
                is_album = "/album/" in final_url or "/album/" in url
                cat = "albums" if is_album else "tracks"
                if ", by " in raw_title:
                    title_part, artist_part = raw_title.split(", by ", 1)
                    title_clean = clean_music_title(title_part.strip())
                    artist_clean = artist_part.strip()
                    query = f"{artist_clean} {title_clean}"
                    return query, cat, f"Bandcamp: {title_clean} by {artist_clean}", "Bandcamp"
                else:
                    title_clean = clean_music_title(raw_title)
                    return title_clean, cat, f"Bandcamp: {title_clean}", "Bandcamp"
        except Exception as e:
            print(f"[LinkResolver] Bandcamp resolution error: {e}")

    # 8. AMAZON MUSIC
    elif "amazon.com" in url or "music.amazon." in url:
        try:
            html_text, final_url = await asyncio.to_thread(http_get_sync, url)
            og_title_m = re.search(r'<meta (?:property|name)="og:title" content="([^"]+)"', html_text, re.I)
            if og_title_m:
                raw_title = html.unescape(og_title_m.group(1))
                clean_t = re.sub(r"\s+on Amazon Music.*$", "", raw_title, flags=re.I).strip()
                is_album = "/albums/" in final_url or "/albums/" in url
                cat = "albums" if is_album else "tracks"
                if " by " in clean_t:
                    t_part, a_part = clean_t.split(" by ", 1)
                    query = f"{a_part.strip()} {clean_music_title(t_part.strip())}"
                    return query, cat, f"Amazon Music: {clean_t}", "Amazon Music"
                else:
                    return clean_music_title(clean_t), cat, f"Amazon Music: {clean_t}", "Amazon Music"
        except Exception as e:
            print(f"[LinkResolver] Amazon Music resolution error: {e}")

    return None, None, None, None
