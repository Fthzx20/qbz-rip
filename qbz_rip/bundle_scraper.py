import asyncio
import base64
import datetime
import hashlib
import json
import re
import ssl
from typing import Optional, Dict, List
import aiohttp

DEFAULT_BUNDLE_URLS = [
    "/resources/8.2.0-b034/bundle.js",
    "/resources/8.1.0-b019/bundle.js",
    "/resources/7.2.0-b082e/bundle.js",
]

KNOWN_CANDIDATE_SECRETS = [
    "abb21364945c0583309667d13ca3d93a",  # Web player live secret
    "b27926955a50d249f3e46c76dbb4fc7d",  # Web player public secret
    "e91240c345167dbdbef56e07a68e98ec",  # Desktop client secret
    "a4f3b764b82d029519398f6d2f7881be",  # Android client secret
    "2143ea23b98e2133b3ff5f9218227b68",  # Web v8 stream key
    "59a35e40e87247fb4268e64c204c3cf7",  # Web v7 stream key
    "04c7a01662fb1d2003ea169994c65cd4",  # Alternate key
    "ecb428d0999ae38d6df7244ab9db138e",  # Alternate key
]

def get_ssl_context():
    """Returns an SSL context with fallback for unbundled Windows root certificates."""
    try:
        return ssl.create_default_context()
    except Exception:
        return ssl._create_unverified_context()

async def validate_stream_signature(session: aiohttp.ClientSession, app_id: str, secret: str) -> bool:
    """
    Sends a test request to track/getFileUrl with track_id=1.
    If the secret is wrong, Qobuz returns HTTP 400: 'Invalid Request Signature parameter (request_sig)'.
    If the secret is mathematically correct, Qobuz accepts the signature (returns != 400 or error without 'request_sig').
    """
    ts = str(int(datetime.datetime.now().timestamp()))
    raw_sig = f"trackgetFileUrlformat_id27intentstreamtrack_id1{ts}{secret}"
    r_sig = hashlib.md5(raw_sig.encode("utf-8")).hexdigest()
    
    url = "https://www.qobuz.com/api.json/0.2/track/getFileUrl"
    params = {
        "format_id": "27",
        "intent": "stream",
        "track_id": "1",
        "request_ts": ts,
        "request_sig": r_sig,
        "app_id": app_id
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "X-App-Id": app_id
    }
    try:
        async with session.get(url, params=params, headers=headers) as resp:
            resp_text = await resp.text()
            if resp.status != 400:
                return True
            # Even if 400, verify if it's NOT a signature error
            if "request_sig" not in resp_text.lower() and "signature" not in resp_text.lower():
                return True
            return False
    except Exception:
        return False

async def scrape_qobuz_web_credentials(timeout_sec: int = 25) -> Optional[Dict[str, str]]:
    """
    Scrapes the live Qobuz web player (play.qobuz.com) to extract the active 9-digit App ID
    and validates the stream signing secret from decoded timezone seeds & known keys.
    """
    ssl_ctx = get_ssl_context()
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/javascript,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout, headers=headers) as session:
            # 1. Fetch Login Page to discover latest bundle.js URL
            bundle_url = None
            try:
                async with session.get("https://play.qobuz.com/login") as resp:
                    if resp.status == 200:
                        login_html = await resp.text()
                        m = re.search(r'<script[^>]+src="(/resources/[^"]+/bundle\.js)"', login_html, re.I)
                        if not m:
                            m = re.search(r'<script[^>]+src="([^"]*bundle[^"]*\.js)"', login_html, re.I)
                        if m:
                            bundle_url = m.group(1)
            except Exception as e:
                print(f"[BundleScraper] Warning: Failed to fetch login page: {e}")

            candidate_bundle_urls = []
            if bundle_url:
                candidate_bundle_urls.append(bundle_url)
            for default_b in DEFAULT_BUNDLE_URLS:
                if default_b not in candidate_bundle_urls:
                    candidate_bundle_urls.append(default_b)

            # 2. Fetch and parse bundle content
            bundle_content = ""
            for b_path in candidate_bundle_urls:
                full_url = f"https://play.qobuz.com{b_path}" if b_path.startswith("/") else b_path
                try:
                    async with session.get(full_url) as b_resp:
                        if b_resp.status == 200:
                            bundle_content = await b_resp.text()
                            if len(bundle_content) > 5000:
                                print(f"[BundleScraper] Successfully loaded bundle from {full_url}")
                                break
                except Exception as e:
                    print(f"[BundleScraper] Warning: Failed to fetch bundle at {full_url}: {e}")
                    continue

            if not bundle_content:
                print("[BundleScraper] Could not retrieve any web bundle content.")
                return None

            # 3. Extract 9-digit App ID
            app_id = None
            m_id = re.search(r'production:\s*\{\s*api:\s*\{\s*appId:\s*["\'](?P<app_id>\d{9})["\']', bundle_content)
            if not m_id:
                m_id = re.search(r'appId:\s*["\'](?P<app_id>\d{9})["\']', bundle_content)
            if not m_id:
                m_id = re.search(r'["\']?app_id["\']?\s*:\s*["\'](?P<app_id>\d{9})["\']', bundle_content)
            if not m_id:
                m_id = re.search(r'X-App-Id["\']?\s*:\s*["\'](?P<app_id>\d{9})["\']', bundle_content)

            if m_id:
                app_id = m_id.group("app_id")
                print(f"[BundleScraper] Extracted live App ID: {app_id}")
            else:
                print("[BundleScraper] App ID pattern not found in bundle.")
                return None

            # 4. Extract Candidate Secrets
            candidate_secrets: List[str] = []

            # A. Reconstruct from Timezone Seeds (Qobuz dynamic signing secret mechanism)
            try:
                seed_tz_regex = re.compile(r'initialSeed\("(?P<seed>[\w=]+)",(?:\w+\.)?utimezone\.(?P<timezone>[a-z]+)\)', re.I)
                secrets_map: Dict[str, List[str]] = {}
                for seed_match in seed_tz_regex.finditer(bundle_content):
                    seed = seed_match.group("seed")
                    timezone = seed_match.group("timezone").lower()
                    secrets_map[timezone] = [seed]

                if secrets_map:
                    timezones_pat = "|".join([tz.capitalize() for tz in secrets_map.keys()])
                    info_extras_regex = re.compile(rf'name:"\w+/(?P<timezone>{timezones_pat})",info:"(?P<info>[\w=]+)",extras:"(?P<extras>[\w=]+)"', re.I)
                    for match in info_extras_regex.finditer(bundle_content):
                        tz = match.group("timezone").lower()
                        info = match.group("info")
                        extras = match.group("extras")
                        if tz in secrets_map:
                            secrets_map[tz].extend([info, extras])

                    for secret_array in secrets_map.values():
                        combined = "".join(secret_array)
                        # Try both common decode trimmings: [:-44] and full[:32]
                        for c_slice in [combined[:-44], combined]:
                            try:
                                decoded = base64.b64decode(c_slice).decode("utf-8", errors="ignore")
                                if len(decoded) >= 32:
                                    s_key = decoded[:32]
                                    if s_key not in candidate_secrets:
                                        candidate_secrets.append(s_key)
                            except Exception:
                                pass
            except Exception as e:
                print(f"[BundleScraper] Warning: Seed reconstruction failed: {e}")

            # B. Known Working Secrets
            for ks in KNOWN_CANDIDATE_SECRETS:
                if ks not in candidate_secrets:
                    candidate_secrets.append(ks)

            # C. Direct Bundle Config Secret (as fallback candidate)
            m_sec = re.search(r'appSecret:\s*["\'](?P<secret>[a-fA-F0-9]{32})["\']', bundle_content)
            if not m_sec:
                m_sec = re.search(r'["\']?app_secret["\']?\s*:\s*["\'](?P<secret>[a-fA-F0-9]{32})["\']', bundle_content)
            if m_sec:
                d_sec = m_sec.group("secret")
                if d_sec not in candidate_secrets:
                    candidate_secrets.append(d_sec)

            # 5. Validate Candidate Secrets against track/getFileUrl with active App ID
            print(f"[BundleScraper] Validating {len(candidate_secrets)} candidate secrets for App ID {app_id}...")
            valid_secret = None
            for cand in candidate_secrets:
                is_valid = await validate_stream_signature(session, app_id, cand)
                if is_valid:
                    valid_secret = cand
                    print(f"[BundleScraper] Verified valid stream signing secret for App ID {app_id}: {cand[:6]}...")
                    break

            if not valid_secret:
                # If network test couldn't reach or confirm, use top seed or default known secret
                valid_secret = candidate_secrets[0] if candidate_secrets else "b27926955a50d249f3e46c76dbb4fc7d"
                print(f"[BundleScraper] Using unverified top candidate secret: {valid_secret[:6]}...")

            return {
                "app_id": app_id,
                "app_secret": valid_secret
            }

    except Exception as e:
        print(f"[BundleScraper] Error scraping Qobuz credentials: {e}")
        return None
