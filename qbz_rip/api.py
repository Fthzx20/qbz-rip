import asyncio
import hashlib
import json
import re
import time
import unicodedata
import aiohttp
from .config import KNOWN_APP_PAIRS

class QobuzAPI:
    """Asynchronous client for interacting with the Qobuz REST API v0.2."""
    
    BASE_URL = "https://www.qobuz.com/api.json/0.2"
    
    def __init__(self, config):
        self.config = config
        self.session = None

    async def get_session(self):
        """Lazy-loaded aiohttp client session with TCP connection pooling and keepalive."""
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(limit=50, keepalive_timeout=60, enable_cleanup_closed=True)
            timeout = aiohttp.ClientTimeout(total=60, sock_connect=15)
            self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        return self.session

    async def close(self):
        """Closes the client session."""
        if self.session and not self.session.closed:
            await self.session.close()

    def _generate_track_signature(self, track_id, format_id, timestamp):
        """
        Generates standard Qobuz MD5 signature for track/getFileUrl.
        Formula: MD5("trackgetFileUrlformat_id" + format_id + "intentstreamtrack_id" + track_id + timestamp + app_secret)
        """
        raw = f"trackgetFileUrlformat_id{format_id}intentstreamtrack_id{track_id}{timestamp}{self.config.app_secret}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _generate_signature(self, endpoint, params):
        """Generates MD5 request signature for general protected Qobuz endpoints (like user/login)."""
        endpoint_slug = endpoint.replace("/", "")
        # Filter and convert to string
        filtered = {k: str(v) for k, v in params.items() if v is not None and k not in ["request_sig"]}
        # Sort keys alphabetically
        sorted_keys = sorted(filtered.keys())
        raw = endpoint_slug + "".join(f"{k}{filtered[k]}" for k in sorted_keys) + self.config.app_secret
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    async def auto_refresh_app_credentials(self):
        """
        Attempts to scrape live credentials from play.qobuz.com web bundle,
        or probes candidate App IDs to find one that accepts requests.
        """
        try:
            from .bundle_scraper import scrape_qobuz_web_credentials
            scraped = await scrape_qobuz_web_credentials()
            if scraped and scraped.get("app_id"):
                new_aid = scraped["app_id"]
                new_sec = scraped.get("app_secret")
                updated = False
                if new_aid != self.config.app_id:
                    self.config.app_id = new_aid
                    updated = True
                if new_sec and new_sec != self.config.app_secret:
                    self.config.app_secret = new_sec
                    updated = True
                if updated:
                    self.config.save()
                    print(f"[Qobuz API] Auto-updated App credentials from web bundle: ID {self.config.app_id}, Secret {self.config.app_secret[:6]}...")
                    return True
        except Exception as e:
            print(f"[Qobuz API] Scraper auto-refresh attempt error: {e}")

        # If scraping did not yield a new ID, probe known candidate App IDs
        session = await self.get_session()
        for aid, asec, lbl in KNOWN_APP_PAIRS:
            if aid == self.config.app_id or aid == "100000000":
                continue
            try:
                url = f"{self.BASE_URL}/catalog/search"
                p = {"app_id": aid, "query": "test", "type": "tracks", "limit": 1}
                h = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "X-App-Id": aid
                }
                if self.config.user_auth_token:
                    p["user_auth_token"] = self.config.user_auth_token
                    h["X-User-Auth-Token"] = self.config.user_auth_token
                async with session.get(url, params=p, headers=h) as r:
                    if r.status == 200:
                        self.config.app_id = aid
                        self.config.app_secret = asec
                        self.config.save()
                        print(f"[Qobuz API] Switched to working candidate App ID: {aid} ({lbl})")
                        return True
            except Exception:
                continue
        return False

    async def _api_request(self, endpoint, params=None, method="GET", sign=False):
        """Helper to make signed or unsigned API requests with exponential backoff on HTTP 429 and auto-healing on HTTP 400 app_id error."""
        session = await self.get_session()
        url = f"{self.BASE_URL}/{endpoint}"
        
        if params is None:
            params = {}
            
        params["app_id"] = self.config.app_id
        if self.config.user_auth_token and "user_auth_token" not in params:
            params["user_auth_token"] = self.config.user_auth_token

        if sign:
            if "request_ts" not in params:
                params["request_ts"] = str(int(time.time()))
            if "request_sig" not in params:
                params["request_sig"] = self._generate_signature(endpoint, params)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "X-App-Id": self.config.app_id
        }
        if self.config.user_auth_token:
            headers["X-User-Auth-Token"] = self.config.user_auth_token

        for attempt in range(3):
            try:
                # Ensure latest config app_id is passed in params and headers
                params["app_id"] = self.config.app_id
                headers["X-App-Id"] = self.config.app_id
                if sign:
                    params["request_sig"] = self._generate_signature(endpoint, params)

                if method.upper() == "GET":
                    resp = await session.get(url, params=params, headers=headers)
                else:
                    resp = await session.post(url, data=params, headers=headers)

                async with resp:
                    if resp.status == 429:
                        # Rate limited, back off
                        await asyncio.sleep(2.0 * (attempt + 1))
                        continue

                    if resp.status == 200:
                        return await resp.json(content_type=None)
                    else:
                        text = await resp.text()
                        try:
                            err_json = json.loads(text)
                            err_msg = err_json.get("message") or err_json.get("error") or text
                        except Exception:
                            err_msg = text

                        # Auto-recovery: If invalid/missing app_id, refresh and retry once
                        if resp.status == 400 and ("app_id" in err_msg.lower() or "missing app_id" in err_msg.lower()) and "request_sig" not in err_msg.lower() and "signature" not in err_msg.lower() and attempt < 2:
                            print(f"[Qobuz API] Detected App ID error ({err_msg[:60]}), triggering auto-refresh...")
                            refreshed = await self.auto_refresh_app_credentials()
                            if refreshed:
                                params["app_id"] = self.config.app_id
                                headers["X-App-Id"] = self.config.app_id
                                continue

                        raise Exception(f"Qobuz API error ({resp.status}): {err_msg[:250]}")
            except aiohttp.ClientError as e:
                if attempt == 2:
                    raise Exception(f"Network error communicating with Qobuz: {e}")
                await asyncio.sleep(1.0)

        raise Exception("Qobuz API request failed after retries.")

    # --- Authentication Methods ---

    async def login(self, username, password):
        """Authenticates user with Qobuz email and password using MD5 hashing and request signature."""
        email_clean = username.strip()
        pwd_clean = password.strip()
        pwd_md5 = hashlib.md5(pwd_clean.encode("utf-8")).hexdigest()

        # Qobuz API v0.2 expects MD5 hashed password and signed request
        attempts = [
            {"email": email_clean, "password": pwd_md5},
            {"username": email_clean, "password": pwd_md5},
            {"email": email_clean, "password": pwd_clean},
            {"username": email_clean, "password": pwd_clean}
        ]

        last_err = None
        for params in attempts:
            try:
                data = await self._api_request("user/login", params=params, method="POST", sign=True)
                token = data.get("user_auth_token")
                user = data.get("user", {})
                
                if token:
                    self.config.user_auth_token = token
                    self.config.user_id = str(user.get("id", ""))
                    self.config.user_email = user.get("email", email_clean)
                    self.config.user_display_name = user.get("display_name") or user.get("email", email_clean)
                    cred = user.get("credential", {})
                    sub_desc = cred.get("description", "Studio Master")
                    self.config.subscription_plan = sub_desc
                    self.config.save()
                    return data
            except Exception as e:
                last_err = e
                continue

        raise Exception(
            f"Login failed ({last_err}). Qobuz restricts direct password logins on many modern accounts. "
            "Please log in using your 'Web Session Token (user_auth_token)' from play.qobuz.com."
        )

    async def verify_auth_token(self, token=None):
        """
        Validates user_auth_token against Qobuz API.
        Automatically probes candidate App ID pairs (Web Player, Desktop, Mobile)
        to match whichever platform issued this session token, saving the working pair to config.
        """
        if token:
            clean_tok = token.strip(" \t\r\n\"'")
            if "token" in clean_tok:
                try:
                    tok_obj = json.loads(clean_tok)
                    clean_tok = tok_obj.get("token") or tok_obj.get("userAuthToken") or clean_tok
                except Exception:
                    m = re.search(r'["\']?(?:token|userAuthToken)["\']?\s*:\s*["\']([^"\']+)["\']', clean_tok)
                    if m:
                        clean_tok = m.group(1)
            self.config.user_auth_token = clean_tok
        elif self.config.user_auth_token:
            clean_tok = self.config.user_auth_token.strip(" \t\r\n\"'")
            if "token" in clean_tok:
                try:
                    tok_obj = json.loads(clean_tok)
                    clean_tok = tok_obj.get("token") or tok_obj.get("userAuthToken") or clean_tok
                except Exception:
                    m = re.search(r'["\']?(?:token|userAuthToken)["\']?\s*:\s*["\']([^"\']+)["\']', clean_tok)
                    if m:
                        clean_tok = m.group(1)
            self.config.user_auth_token = clean_tok
            
        if not self.config.user_auth_token:
            return None

        # Build list of (app_id, app_secret, label) to probe
        candidates = []

        # Try live scraping web bundle first (it directly validates stream signing secret)
        try:
            from .bundle_scraper import scrape_qobuz_web_credentials
            scraped = await scrape_qobuz_web_credentials(timeout_sec=15)
            if scraped and scraped.get("app_id") and scraped.get("app_secret"):
                s_aid = scraped["app_id"]
                s_sec = scraped["app_secret"]
                candidates.append((s_aid, s_sec, "Live Web Scraper"))
                self.config.app_id = s_aid
                self.config.app_secret = s_sec
                self.config.save()
                print(f"[Qobuz Auth] Applied verified stream credentials: App ID {s_aid}, Secret {s_sec[:6]}...")
        except Exception as e:
            print(f"[Qobuz Auth] Scraper probe error: {e}")

        if self.config.app_id and self.config.app_secret and self.config.app_id != "100000000":
            if not any(c[0] == self.config.app_id and c[1] == self.config.app_secret for c in candidates):
                candidates.append((self.config.app_id, self.config.app_secret, "Active Config"))

        for aid, asec, lbl in KNOWN_APP_PAIRS:
            if aid != "100000000" and not any(c[0] == aid for c in candidates):
                candidates.append((aid, asec, lbl))

        session = await self.get_session()
        last_error = None

        # 1. Primary probe: user/get across candidate App IDs
        for aid, asec, lbl in candidates:
            try:
                url = f"{self.BASE_URL}/user/get"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "X-App-Id": aid,
                    "X-User-Auth-Token": self.config.user_auth_token
                }
                params = {
                    "app_id": aid,
                    "user_auth_token": self.config.user_auth_token
                }
                async with session.get(url, params=params, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        user_data = data.get("user") if isinstance(data, dict) and "user" in data else data
                        if isinstance(user_data, dict):
                            self.config.app_id = aid
                            self.config.app_secret = asec
                            self.config.user_id = str(user_data.get("id", self.config.user_id))
                            self.config.user_email = user_data.get("email", self.config.user_email)
                            self.config.user_display_name = user_data.get("display_name") or user_data.get("email", "Qobuz Member")
                            cred = user_data.get("credential", {})
                            self.config.subscription_plan = cred.get("description", "Studio Master")
                            self.config.save()
                            print(f"[Qobuz Auth] Verified successfully using App ID: {aid} ({lbl})")
                            return user_data
                    else:
                        text = await resp.text()
                        last_error = f"HTTP {resp.status} on {aid} ({lbl}): {text[:70]}"
            except Exception as e:
                last_error = str(e)
                continue

        # 2. Secondary fallback probe: catalog/search with token
        for aid, asec, lbl in candidates:
            try:
                url = f"{self.BASE_URL}/catalog/search"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    "X-App-Id": aid,
                    "X-User-Auth-Token": self.config.user_auth_token
                }
                params = {
                    "app_id": aid,
                    "user_auth_token": self.config.user_auth_token,
                    "query": "test",
                    "type": "tracks",
                    "limit": 1
                }
                async with session.get(url, params=params, headers=headers) as resp:
                    if resp.status == 200:
                        self.config.app_id = aid
                        self.config.app_secret = asec
                        self.config.user_display_name = self.config.user_display_name or "Qobuz Member"
                        self.config.subscription_plan = self.config.subscription_plan or "Studio Active"
                        self.config.save()
                        print(f"[Qobuz Auth] Validated via search probe with App ID: {aid} ({lbl})")
                        return {"display_name": self.config.user_display_name}
            except Exception:
                continue

        print(f"[Qobuz Auth] Token verification failed across all candidate App IDs. Last error: {last_error}")
        return None

    # --- Catalog & Metadata Methods ---

    def rank_search_items(self, items, query, search_type="tracks"):
        """
        Ranks catalog search items with intelligent audiophile relevance scoring:
        1. Exact phrase/token matching against title, performer, and album.
        2. Demotion of tribute bands, karaoke, and unrelated covers unless explicitly searched.
        3. Audiophile bonus: Prioritizes 24-bit 192kHz Studio Master and 96kHz Hi-Res over standard CD/lossy.
        """
        clean_q = query.strip().lower()
        q_tokens = [t for t in re.split(r"\W+", clean_q) if len(t) > 1]

        def score_item(item):
            if not isinstance(item, dict):
                return 0.0
            score = 0.0

            title = str(item.get("title") or item.get("name") or "").lower()
            artist = ""
            perf = item.get("performer")
            if isinstance(perf, dict):
                artist = str(perf.get("name", "")).lower()
            elif isinstance(item.get("artist"), dict):
                artist = str(item["artist"].get("name", "")).lower()

            combined = f"{artist} {title}".strip()

            # 1. Exact & Substring Matches
            if clean_q == title or clean_q == combined:
                score += 160.0
            elif clean_q in combined:
                score += 85.0
            elif title in clean_q or (artist and artist in clean_q):
                score += 60.0

            # 2. Token overlap
            if q_tokens:
                matched = sum(1 for tok in q_tokens if tok in combined)
                score += (matched / len(q_tokens)) * 45.0

            # 3. Demote unwanted noise (karaoke, tribute, etc.) unless requested
            unwanted = ["karaoke", "tribute", "originally performed", "in the style of", "backing track", "cover version"]
            for u in unwanted:
                if u in combined and u not in clean_q:
                    score -= 70.0

            # 4. Audiophile Hi-Res Quality Boost
            bit_depth = item.get("maximum_bit_depth") or item.get("bit_depth") or 16
            try:
                sample_rate = float(item.get("maximum_sampling_rate") or item.get("sampling_rate") or 44.1)
            except Exception:
                sample_rate = 44.1

            if bit_depth >= 24:
                if sample_rate >= 176.4:
                    score += 25.0  # 192kHz Master
                elif sample_rate >= 88.2:
                    score += 18.0  # 96kHz Hi-Res
                else:
                    score += 10.0  # 24-bit 44.1/48kHz
            elif item.get("hires") or item.get("hires_streamable"):
                score += 14.0

            if item.get("parental_warning"):
                score += 2.0

            if item.get("_isrc_match"):
                score += 500.0

            return score

        return sorted(items, key=score_item, reverse=True)

    async def search(self, query, search_type="tracks", limit=30, offset=0):
        """
        Searches Qobuz catalog for tracks, albums, artists, playlists, or all categories simultaneously.
        Supports direct ISRC and UPC/EAN barcode lookups.
        """
        clean_q = str(query).strip()
        st = str(search_type).lower()
        limit_clean = max(1, min(int(limit), 100))
        offset_clean = max(0, int(offset))

        # Direct ISRC code matching (12 characters, e.g. USUM71703861)
        if re.match(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$", clean_q, re.I):
            try:
                raw_res = await self._api_request("catalog/search", params={"query": clean_q, "type": "tracks", "limit": 10, "offset": 0})
                if isinstance(raw_res, dict) and "tracks" in raw_res and len(raw_res["tracks"].get("items", [])) > 0:
                    matched_items = []
                    for itm in raw_res["tracks"]["items"]:
                        if str(itm.get("isrc", "")).upper() == clean_q.upper():
                            itm["_isrc_match"] = True
                            matched_items.insert(0, itm)
                        else:
                            matched_items.append(itm)
                    raw_res["tracks"]["items"] = matched_items
                    return raw_res
            except Exception:
                pass

        # Direct Barcode / UPC / EAN matching (12-14 digits)
        if re.match(r"^\d{12,14}$", clean_q):
            try:
                alb = await self.get_album(clean_q)
                if alb and isinstance(alb, dict) and alb.get("id"):
                    return {"albums": {"items": [alb], "total": 1}}
            except Exception:
                pass

        # Unified "all" search mode
        if st in ("all", "everything"):
            # Attempt multi-category search via Qobuz API
            try:
                res = await self._api_request("catalog/search", params={
                    "query": clean_q,
                    "limit": limit_clean,
                    "offset": offset_clean
                })
                if isinstance(res, dict) and any(k in res for k in ["tracks", "albums", "artists", "playlists"]):
                    combined = []
                    for cat in ["tracks", "albums", "artists", "playlists"]:
                        if cat in res and isinstance(res[cat], dict):
                            for it in res[cat].get("items", []):
                                it["_category"] = cat
                                combined.append(it)
                    res["all"] = {"items": self.rank_search_items(combined, clean_q), "total": len(combined)}
                    return res
            except Exception:
                pass

            # Fallback concurrent queries across all 4 categories
            tasks = [
                self.search(clean_q, search_type="tracks", limit=limit_clean, offset=offset_clean),
                self.search(clean_q, search_type="albums", limit=limit_clean, offset=offset_clean),
                self.search(clean_q, search_type="artists", limit=limit_clean, offset=offset_clean),
                self.search(clean_q, search_type="playlists", limit=limit_clean, offset=offset_clean),
            ]
            gathered = await asyncio.gather(*tasks, return_exceptions=True)
            res = {}
            combined = []
            for cat_name, cat_res in zip(["tracks", "albums", "artists", "playlists"], gathered):
                if isinstance(cat_res, dict) and cat_name in cat_res and isinstance(cat_res[cat_name], dict):
                    items = cat_res[cat_name].get("items", [])
                    for it in items:
                        it["_category"] = cat_name
                    combined.extend(items)
                    res[cat_name] = cat_res[cat_name]
            res["all"] = {"items": self.rank_search_items(combined, clean_q), "total": len(combined)}
            return res

        type_map = {
            "tracks": "tracks",
            "albums": "albums",
            "artists": "artists",
            "playlists": "playlists"
        }
        st_clean = type_map.get(st, "tracks")
        params = {
            "query": clean_q,
            "type": st_clean,
            "limit": limit_clean,
            "offset": offset_clean
        }
        res = await self._api_request("catalog/search", params=params)
        if isinstance(res, dict) and st_clean in res and isinstance(res[st_clean], dict):
            items = res[st_clean].get("items", [])
            for it in items:
                it["_category"] = st_clean
            res[st_clean]["items"] = self.rank_search_items(items, clean_q, search_type=st_clean)
        return res

    async def smart_search(self, query, search_type="tracks", limit=30, offset=0):
        """
        Intelligent multi-stage search engine:
        1. Primary direct query with audiophile re-ranking.
        2. Parallel candidate generation (unaccented diacritics, noise stripping, token transposition).
        3. Cross-category fallback (auto-extract albums from tracks or vice-versa).
        """
        clean_st = str(search_type).lower()
        clean_q = str(query).strip()
        last_error = None

        # 1. Primary search with direct user query
        try:
            res = await self.search(clean_q, search_type=clean_st, limit=limit, offset=offset)
            key = "all" if clean_st in ("all", "everything") else clean_st
            if isinstance(res, dict) and key in res and len(res[key].get("items", [])) > 0:
                return res
        except Exception as e:
            last_error = e
            res = {}

        # Helpers for normalization
        def strip_accents(text):
            return "".join(
                c for c in unicodedata.normalize("NFD", text)
                if unicodedata.category(c) != "Mn"
            )

        def clean_text(q):
            t = re.sub(r'[\(\[][^\)\]]*(?:feat|ft|remaster|radio|edit|version|mix|official|video|audio|deluxe|bonus|live|expanded|anniversary)[^\)\]]*[\)\]]', '', q, flags=re.I)
            t = re.sub(r'\b(?:feat\.?|ft\.?)\s+[^\-]+', '', t, flags=re.I)
            t = re.sub(r'[^\w\s\-\'\,\.]', ' ', t)
            t = re.sub(r'\s+', ' ', t).strip()
            return t

        candidates = []

        # A. Diacritics/Accents normalized version (Björk <-> Bjork, Rosalía <-> Rosalia)
        unaccented = strip_accents(clean_q)
        if unaccented.lower() != clean_q.lower():
            candidates.append(unaccented)

        # B. Cleaned text without noisy bracket tags
        cleaned = clean_text(clean_q)
        if cleaned and cleaned.lower() not in [clean_q.lower(), unaccented.lower()]:
            candidates.append(cleaned)
            cleaned_unaccented = strip_accents(cleaned)
            if cleaned_unaccented.lower() not in [c.lower() for c in candidates]:
                candidates.append(cleaned_unaccented)

        # C. Sub-phrase permutations: handle "Artist - Title" vs "Title Artist"
        for base in [clean_q, cleaned] if cleaned != clean_q else [clean_q]:
            if " - " in base:
                left, right = [p.strip() for p in base.split(" - ", 1)]
                candidates.append(f"{left} {right}")
                candidates.append(f"{right} {left}")
                candidates.append(right)
                candidates.append(left)
            elif " by " in base.lower():
                m = re.split(r"\s+by\s+", base, flags=re.I, maxsplit=1)
                if len(m) == 2:
                    t_part, a_part = m[0].strip(), m[1].strip()
                    candidates.append(f"{a_part} {t_part}")
                    candidates.append(f"{t_part} {a_part}")
                    candidates.append(t_part)

        # 2. Parallel candidate evaluation
        unique_cands = []
        seen = {clean_q.lower()}
        for c in candidates:
            c_low = c.strip().lower()
            if c_low and c_low not in seen:
                seen.add(c_low)
                unique_cands.append(c.strip())

        if unique_cands:
            async def try_cand(cand_str):
                try:
                    return await self.search(cand_str, search_type=clean_st, limit=limit, offset=offset)
                except Exception:
                    return None

            cand_results = await asyncio.gather(*[try_cand(c) for c in unique_cands[:4]], return_exceptions=True)
            for cr in cand_results:
                if isinstance(cr, dict):
                    key = "all" if clean_st in ("all", "everything") else clean_st
                    if key in cr and len(cr[key].get("items", [])) > 0:
                        return cr

        # 3. Cross-category recovery: If user searched Albums but 0 found, extract albums from tracks
        if clean_st == "albums":
            try:
                trk_res = await self.search(cleaned or unaccented or clean_q, search_type="tracks", limit=limit)
                tracks = trk_res.get("tracks", {}).get("items", []) if isinstance(trk_res, dict) else []
                seen_album_ids = set()
                recovered_albums = []
                for trk in tracks:
                    alb = trk.get("album")
                    if alb and alb.get("id") and alb["id"] not in seen_album_ids:
                        seen_album_ids.add(alb["id"])
                        alb["_category"] = "albums"
                        recovered_albums.append(alb)
                if recovered_albums:
                    return {"albums": {"items": self.rank_search_items(recovered_albums, clean_q, "albums"), "total": len(recovered_albums)}}
            except Exception:
                pass

        # 4. Cross-category recovery: If user searched Tracks but 0 found, check albums
        if clean_st == "tracks":
            try:
                alb_res = await self.search(cleaned or unaccented or clean_q, search_type="albums", limit=limit)
                albums = alb_res.get("albums", {}).get("items", []) if isinstance(alb_res, dict) else []
                if albums:
                    for a in albums:
                        a["_category"] = "albums"
                    return {"albums": {"items": self.rank_search_items(albums, clean_q, "albums"), "total": len(albums)}}
            except Exception:
                pass

        # If all candidates returned empty and an API error occurred on primary query, raise it
        if last_error and (not res or not any(len(res.get(k, {}).get("items", [])) > 0 for k in ["tracks", "albums", "artists", "playlists", "all"])):
            raise last_error

        return res

    async def get_track(self, track_id):
        """Retrieves metadata for a track."""
        return await self._api_request("track/get", params={"track_id": str(track_id).strip()})

    async def get_album(self, album_id):
        """Retrieves metadata and tracklist for an album."""
        return await self._api_request("album/get", params={"album_id": str(album_id).strip()})

    async def get_artist(self, artist_id):
        """Retrieves artist details and their discography."""
        try:
            return await self._api_request("artist/get", params={"artist_id": str(artist_id).strip(), "extra": "albums", "limit": 100})
        except Exception:
            return await self._api_request("artist/get", params={"artist_id": str(artist_id).strip(), "limit": 100})

    async def get_playlist(self, playlist_id):
        """Retrieves playlist details and its tracks."""
        return await self._api_request("playlist/get", params={"playlist_id": str(playlist_id).strip(), "limit": 500, "offset": 0})

    # --- Hi-Res Stream URL Extraction ---

    async def get_file_url(self, track_id, preferred_format_id=None):
        """
        Retrieves the direct bit-perfect FLAC audio stream URL for a track.
        Handles format hierarchy: 27 (192kHz) -> 7 (96kHz) -> 6 (44.1kHz FLAC) -> 5 (MP3).
        Automatically attempts candidate signing secrets if signature error occurs.
        """
        if preferred_format_id is None:
            preferred_format_id = self.config.format_id

        # Hierarchical quality fallback list
        if preferred_format_id == 27:
            formats_to_try = [27, 7, 6, 5]
        elif preferred_format_id == 7:
            formats_to_try = [7, 6, 5]
        elif preferred_format_id == 6:
            formats_to_try = [6, 5]
        else:
            formats_to_try = [5]

        # Candidate signing secrets to try
        secrets_to_try = []
        if self.config.app_secret:
            secrets_to_try.append(self.config.app_secret)

        fallback_secrets = [
            "abb21364945c0583309667d13ca3d93a",
            "b27926955a50d249f3e46c76dbb4fc7d",
            "e91240c345167dbdbef56e07a68e98ec",
            "a4f3b764b82d029519398f6d2f7881be",
            "2143ea23b98e2133b3ff5f9218227b68",
            "59a35e40e87247fb4268e64c204c3cf7",
            "04c7a01662fb1d2003ea169994c65cd4",
            "ecb428d0999ae38d6df7244ab9db138e",
        ]
        for s in fallback_secrets:
            if s not in secrets_to_try:
                secrets_to_try.append(s)

        last_error = None
        for sec in secrets_to_try:
            signature_failed = False
            for fmt in formats_to_try:
                ts = str(int(time.time()))
                raw_sig = f"trackgetFileUrlformat_id{fmt}intentstreamtrack_id{track_id}{ts}{sec}"
                sig = hashlib.md5(raw_sig.encode("utf-8")).hexdigest()
                params = {
                    "track_id": str(track_id),
                    "format_id": str(fmt),
                    "intent": "stream",
                    "request_ts": ts,
                    "request_sig": sig
                }
                try:
                    data = await self._api_request("track/getFileUrl", params=params, sign=False)
                    url = data.get("url")
                    if url:
                        if sec != self.config.app_secret:
                            self.config.app_secret = sec
                            self.config.save()
                            print(f"[Qobuz API] Switched to working stream signing secret: {sec[:6]}...")
                        return {
                            "url": url,
                            "format_id": fmt,
                            "mime_type": data.get("mime_type", "audio/flac"),
                            "sampling_rate": data.get("sampling_rate"),
                            "bit_depth": data.get("bit_depth"),
                            "track_id": track_id
                        }
                    else:
                        last_error = data.get("message", "No stream URL returned.")
                except Exception as e:
                    err_str = str(e)
                    last_error = err_str
                    if "signature" in err_str.lower() or "request_sig" in err_str.lower():
                        signature_failed = True
                        break  # Wrong secret, skip remaining formats and try next candidate secret!
                    continue

            if not signature_failed and last_error and "signature" not in last_error.lower() and "request_sig" not in last_error.lower():
                # If error is not a signature error (e.g. track geo-restricted or streamable:false), don't loop secrets
                break

        if signature_failed or (last_error and ("signature" in last_error.lower() or "request_sig" in last_error.lower())):
            print("[Qobuz API] Stream signature failed with cached keys, auto-refreshing live web bundle secret...")
            refreshed = await self.auto_refresh_app_credentials()
            if refreshed and self.config.app_secret not in secrets_to_try:
                sec = self.config.app_secret
                for fmt in formats_to_try:
                    ts = str(int(time.time()))
                    raw_sig = f"trackgetFileUrlformat_id{fmt}intentstreamtrack_id{track_id}{ts}{sec}"
                    sig = hashlib.md5(raw_sig.encode("utf-8")).hexdigest()
                    params = {
                        "track_id": str(track_id),
                        "format_id": str(fmt),
                        "intent": "stream",
                        "request_ts": ts,
                        "request_sig": sig
                    }
                    try:
                        data = await self._api_request("track/getFileUrl", params=params, sign=False)
                        url = data.get("url")
                        if url:
                            return {
                                "url": url,
                                "format_id": fmt,
                                "mime_type": data.get("mime_type", "audio/flac"),
                                "sampling_rate": data.get("sampling_rate"),
                                "bit_depth": data.get("bit_depth"),
                                "track_id": track_id
                            }
                    except Exception as e:
                        last_error = str(e)

        raise Exception(f"Unable to retrieve audio stream URL for track {track_id}: {last_error}")
    
    async def get_preview_url(self, track_id):
        """
        Retrieves a 30-second sample/preview stream URL for a track.
        Works across all user subscription tiers including non-subscribers.
        """
        # 1. Try track metadata preview/sample URL if present
        try:
            track_meta = await self.get_track(track_id)
            if isinstance(track_meta, dict):
                sample_url = track_meta.get("preview_url") or track_meta.get("sample_url")
                if sample_url:
                    return sample_url
        except Exception:
            pass

        # 2. Request 128/320kbps MP3 stream using intent='sample' or fallback to stream
        ts = str(int(time.time()))
        secrets_to_try = [s for s in [self.config.app_secret, "abb21364945c0583309667d13ca3d93a", "b27926955a50d249f3e46c76dbb4fc7d"] if s]
        for sec in secrets_to_try:
            for intent in ["sample", "stream"]:
                raw_sig = f"trackgetFileUrlformat_id5intent{intent}track_id{track_id}{ts}{sec}"
                sig = hashlib.md5(raw_sig.encode("utf-8")).hexdigest()
                params = {
                    "track_id": str(track_id),
                    "format_id": "5",
                    "intent": intent,
                    "request_ts": ts,
                    "request_sig": sig
                }
                try:
                    data = await self._api_request("track/getFileUrl", params=params, sign=False)
                    if data and data.get("url"):
                        return data["url"]
                except Exception:
                    continue

        # 3. Fallback to standard get_file_url format 5
        try:
            info = await self.get_file_url(track_id, preferred_format_id=5)
            return info.get("url")
        except Exception:
            return None
