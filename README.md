<div align="center">

# ⚡ QBZ RIP
### The Ultimate 24-bit / 192kHz Studio Master Q-Buz Downloader

[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-blue.svg?style=for-the-badge&logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-success.svg?style=for-the-badge)](LICENSE)
[![UI: CustomTkinter](https://img.shields.io/badge/UI-CustomTkinter-00b4d8.svg?style=for-the-badge)](https://github.com/TomSchimansky/CustomTkinter)
[![Audio: 24-bit/192kHz FLAC](https://img.shields.io/badge/Audio-24--bit%2F192kHz%20FLAC-ffb703.svg?style=for-the-badge)](https://en.wikipedia.org/wiki/FLAC)
[![Platform: Windows / macOS / Linux](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg?style=for-the-badge)]()

A high-performance, asynchronous, bit-perfect desktop application built exclusively for **Q-Buz**.  
Designed for audiophiles who demand true, uncompressed **24-bit / 192kHz Studio Master** quality straight from the source.

[Features](#-features--superpowers) • [Audio Formats](#-q-buz-audio-tiers) • [Spectrogram Analysis & Label Upsampling](#-spectrogram-analysis--the-label-upsampling-phenomenon) • [Installation](#-installation) • [Authentication](#-q-buz-authentication-guide) • [Multi-User Login](#-multi-user--account-switching) • [Usage Guide](#-how-to-use) • [Configuration](#-configuration) • [Troubleshooting](#-troubleshooting--faq)

</div>

---

## 🌟 Features & Superpowers

* 👑 **True 24-bit / 192kHz Studio Master FLAC**: Downloads direct, untouched FLAC audio streams straight from Q-Buz CDN servers. No transcoding, zero DSP manipulation, zero loss, and zero forced upscaling.
* 🎵 **Instant 30s Audio Preview Player**: Listen to 30-second high-fidelity sample clips directly inside search results using the interactive `▶ Preview` / `⏹ Stop` player before downloading.
* 📑 **Official Q-Buz Digital Booklet Download (PDF)**: Automatically detects and downloads high-resolution official digital liner notes and booklets (`Digital Booklet.pdf`) included in album goodies directly into the album folder.
* 🎤 **Auto Synced Lyrics (`.lrc` + Embedded Tags)**: Integrated with the open-source **LRCLIB** database. Automatically generates synchronized `.lrc` files next to audio tracks and embeds Vorbis comments (`LYRICS`, `UNSYNCEDLYRICS`) or ID3 tags (`USLT`).
* 📋 **Batch URL / Multi-Link Importer**: Paste multiple tracks, albums, or playlists at once from Q-Buz, Spotify, Apple Music, Tidal, Deezer, YouTube, SoundCloud, Bandcamp, and Amazon Music, or load links directly from a `.txt` file!
* 🔗 **Universal Multi-Platform Link Resolver**: Paste URLs from **Spotify**, **Apple Music**, **Tidal**, **Deezer**, **YouTube**, **SoundCloud**, **Bandcamp**, and **Amazon Music** (with automatic HTTP 301/302 redirect resolution for mobile shortlinks like `spotify.link`, `spoti.fi`, `apple.co`, `deezer.page.link`, `on.soundcloud.com`, `a.co`, `amzn.to`) to download matching Studio Master tracks on Q-Buz.
* ⚡ **True Parallel Async Concurrency & HTTP Range Auto-Resume**: Powered by Python's `asyncio` and `aiohttp`. Configure 1 to 5 simultaneous download slots with real-time UI speed and independent progress bars. If a socket timeout or network fluctuation occurs, downloads automatically resume from the last byte via `Range: bytes={downloaded}-` instead of restarting from scratch!
* 🏷️ **Extended Audiophile Vorbis & ID3 Tagging**: Automatically embeds rich metadata into FLAC tags (`TITLE`, `ARTIST`, `ALBUM`, `ALBUMARTIST`, `TRACKNUMBER`, `TRACKTOTAL`, `DISCNUMBER`, `DISCTOTAL`, `DATE`, `YEAR`, `ISRC`, `COPYRIGHT`, `COMPOSER`, `GENRE`, `COMMENT`) plus maximum resolution embedded front cover art.
* 🛡️ **Bit-Stream Integrity & `checksums.md5` Generation**: Verifies the downloaded FLAC byte count against CDN headers, validates `STREAMINFO` decoded bit-depth/sample rate with Mutagen, and automatically appends cryptographic MD5 hashes into `checksums.md5` for archival verification.
* 🗂️ **Thread-Safe Album Operations & Windows MAX_PATH Safety**: Multi-worker downloads of the same album safely lock folder operations (preventing duplicate PDF/cover art downloads or race conditions in checksum files) and clamp file paths to avoid Windows 260-character path errors.
* 🎨 **Album Folder Artwork (`cover.jpg`)**: Automatically saves high-res `cover.jpg` directly into the album folder for external media players (Foobar2000, Plex, Roon, Kodi, MusicBee).
* 💿 **Multi-Disc Safe**: Automatically prefixes disc numbers (e.g. `1-01`, `2-01`) for multi-disc box sets, preventing track overwriting.
* 🔍 **Advanced Audiophile Search Engine**:
  * **Unified Multi-Category Catalog Search**: Search simultaneously across Tracks, Albums, Artists, and Playlists (`All`), or target specific categories with live pagination (`Load More Results`).
  * **Intelligent Audiophile Re-Ranking**: Automatically prioritizes authentic **24-bit/192kHz Studio Master** and **96kHz Hi-Res** releases over CD/lossy cuts, while filtering out unwanted karaoke and tribute cuts.
  * **Live Quality Filtering**: One-click filter chips to isolate `All Qualities`, `✨ Hi-Res (24-bit+)`, `🏆 192kHz Master Only`, or `💿 CD Lossless (16-bit)`.
  * **Instant Sorting**: Re-sort on the fly by `Best Match`, `Highest Quality`, `Newest Release`, or `Title (A-Z)`.
  * **ISRC & Barcode (UPC/EAN) Direct Matching**: Paste 12-character ISRC codes or 12–14 digit album barcodes for direct 1:1 bit-perfect master lookup.
  * **Multi-Stage Query Normalization**: Automatically normalizes diacritics (`Björk` ↔ `Bjork`), strips noisy bracket tags (`[Remastered 2021]`), and evaluates artist/title token transpositions in parallel.
  * **Recent Searches & Quick Recall**: Instant-click recent search pills and global keyboard shortcuts (`Ctrl+F` to search, `Esc` to clear).
  * **Direct Track-to-Album Jump**: Click `💽 Album` on any track card to immediately inspect and download the full release or digital booklet.
* ☑️ **Interactive Track Selection Checklist**: When downloading Albums or Playlists, an interactive checklist modal lets you choose specific tracks with **Select All**, **Deselect All**, **Invert Selection**, and clickable track rows.
* 📁 **Windows Explorer Integration**: One-click "Open Folder" button in Queue header plus individual folder reveal buttons (`📁`) that highlight the exact downloaded audio file in Windows Explorer.
* 🔔 **Queue Completion Chime**: Gentle notification chime when batch downloads finish.
* 🚀 **1-Click Windows Automation (`install.bat` & `run.bat`)**: Out-of-the-box Windows batch scripts that auto-detect Python, upgrade pip, install dependencies, and launch the application seamlessly.
* ⚡ **Fluid 60 FPS Chunked UI Rendering**: High-performance UI engine featuring chunked progressive rendering that keeps the window butter-smooth and responsive even with hundreds of search results.
* 🖼️ **Resilient Cover Thumbnail Engine**: High-speed async artwork loader with browser spoofing headers, SSL fallback, and clean placeholder fallbacks (`🎵`) preventing network hang-ups.
* 🧠 **Session Preservation & Auto-Restore**: Never lose your queue! Both pending and actively downloading tracks are automatically saved on exit (`session.json`) and seamlessly restored on the next launch.
* 🔁 **One-Click Failed & Cancelled Download Retry**: Instant `🔁` retry button on individual items plus a header `🔁 Retry Failed` button to revive failed or cancelled tracks without re-searching.
* 🛡️ **Graceful Delisted & Geo-Block Protection**: Gracefully detects 404 delisted or region-locked tracks on Q-Buz and flags them cleanly without crashing or interrupting other downloads.
* ⏭️ **Smart Sync Skip**: Automatically checks if a track was already downloaded and skips redundant network traffic.

---

## 🎼 Q-Buz Audio Tiers

Q-Buz provides uncompressed lossless audio streams categorized by format IDs:

| Format ID | Format Name | Resolution / Bitrate | Description |
| :---: | :--- | :--- :---: | :--- |
| **27** | **Studio Master (Default)** | **24-bit / up to 192 kHz** | Pure uncompressed studio master FLAC. |
| **7** | **Hi-Res** | **24-bit / up to 96 kHz** | High-resolution lossless FLAC. |
| **6** | **CD Lossless** | **16-bit / 44.1 kHz** | Red Book standard lossless CD FLAC. |
| **5** | **MP3** | **320 kbps CBR** | High-bitrate standard lossy MP3. |

*Note: An active Q-Buz Studio or Sublime subscription is required to stream and download 24-bit Hi-Res and Studio Master files.*

---

## 🔬 Spectrogram Analysis & the "Label Upsampling" Phenomenon

Many audiophiles inspect downloaded FLAC files using spectrogram software such as **Spek**, **Audacity**, or **iZotope RX**, and ask:

> *"Why do some 24-bit / 192kHz or 24-bit / 96kHz files in Spek appear sharply cut off at 20kHz, 22.05kHz, or 24kHz like standard CD or MP3 audio? Is QBZ-RIP's download truly 100% pure and bit-perfect?"*

Here is the transparent, in-depth audio engineering explanation:

### 1. Does QBZ-RIP Deliver 100% Pure, Bit-Perfect Audio?
**YES, 100% PURE AND BIT-PERFECT.**  
`qbz-rip` fetches the raw binary FLAC audio stream directly from Q-Buz's official Content Delivery Networks (CDNs: CloudFront/Akamai). 
- The application **NEVER** re-encodes, transcodes, downsamples, or applies DSP filtering of any kind.
- Mutagen directly reads the authentic binary `STREAMINFO` block from the FLAC header.
- The cryptographic MD5 hash recorded in `checksums.md5` matches the exact binary file hosted on Q-Buz CDN servers.

---

### 2. Why Do Some Spectrograms ("Spek") Look Cut-Off?
If the audio stream is 100% bit-perfect from Q-Buz, why does Spek show high frequencies stopping abruptly at 20kHz–24kHz? This is determined by the **source studio master provided by the record label**:

#### A. The "Label Upsampling" Phenomenon (Early-Digital Era Masters: 1980s – Early 2000s)
* During the early digital recording era (late 1980s through the 2000s), almost all recording studios tracked and mixed audio digitally at **16-bit / 44.1kHz** (Red Book CD standard) or **24-bit / 48kHz** (early DAT tape and early Pro Tools systems).
* According to the **Nyquist-Shannon Sampling Theorem**, the absolute maximum audio frequency that can be represented is half of the sampling rate (the Nyquist limit):
  * Sample rate 44.1 kHz $\rightarrow$ absolute frequency ceiling (Nyquist limit) is **22.05 kHz**.
  * Sample rate 48.0 kHz $\rightarrow$ absolute frequency ceiling (Nyquist limit) is **24.0 kHz**.
* When major record labels (Universal Music Group, Sony Music, Warner Music, etc.) re-release catalog albums in "Hi-Res Remastered" editions for streaming services (Q-Buz, HDtracks, Apple Music), **some labels do not track down and re-digitize original multi-track analog tapes**. Instead, they take the existing 44.1kHz or 48kHz digital master and export it into a 24-bit / 96kHz or 24-bit / 192kHz container file!
* **The result:**
  * **Container/File specs:** The FLAC file is genuine 24-bit / 192kHz (150MB–350MB, sample rate of 192,000 samples per second).
  * **Acoustic spectrum (Spek):** The audio frequencies hard-stop at 22.05kHz or 24kHz because the original digital master never contained any ultrasonic content above that frequency. Everything above 24kHz is silence / digital noise floor (-120dB).

#### B. Steep Brickwall Low-Pass Filters in Modern Pop & EDM Mastering
* In modern music production, mastering engineers frequently apply **steep brickwall low-pass filters at 20kHz – 22kHz**.
* The purpose is to eliminate non-audible ultrasonic frequencies that can cause intermodulation distortion (IMD) on consumer amplifiers, tweeters, and DACs. Even if the master was exported at 24/96 or 24/192, ultrasonic audio was intentionally filtered out during studio mastering.

#### C. When Does Spek Display Continuous Energy Up to 40kHz–90kHz+?
* Files showing rich, continuous harmonic decay reaching 40kHz, 60kHz, and beyond are **True Analog Master Tape Transfers**.
* Examples include classic recordings from the 1960s–1980s (e.g. *Pink Floyd - The Dark Side of the Moon*, *The Eagles - Hotel California*, *Steely Dan - Aja*, *Miles Davis - Kind of Blue*, or classical orchestra recordings from Deutsche Grammophon / Decca) digitized directly from original 1/2-inch or 1-inch analog master tapes using modern high-resolution ADCs at 192kHz.
* Analog magnetic tape possesses natural wide-band frequency response with smooth rolloff and no artificial digital cutoff, yielding a rich, continuous gradient across the entire spectrogram in Spek.

> **💡 Summary & Guarantee for Audiophiles:**  
> QBZ-RIP guarantees that your downloaded files are **1:1 bit-perfect copies of the master files delivered by the record label to Q-Buz**. Any frequency cut-off observed in Spek is inherent to the master provided by the record label (*Label Upsampling* or *Studio Mastering Choices*), not an artifact of QBZ-RIP.

---

## 🚀 Installation

### 1. Requirements
* **Python 3.8 or higher** (Python 3.10–3.13 recommended; fully compatible with Python 3.14).
* Windows 10/11, macOS, or Linux.

### ⚡ 1-Click Quick Start (Windows — Recommended)
If you are on Windows, no manual command-line typing is needed:
1. Double-click **`install.bat`** — Automatically detects your Python installation (`py` or `python`), upgrades pip, and installs all required dependencies.
2. Double-click **`run.bat`** — Launches QBZ-RIP with optimal settings (`-B` flag to bypass bytecode cache errors).

---

### 💻 Manual Setup (Cross-Platform / CLI)
```bash
# 1. Navigate to the project directory
cd "d:/Desktop/Documents/Code Things/qbz-rip"

# 2. (Optional) Create and activate a virtual environment
python -m venv venv

# Windows PowerShell / CMD:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
# (Tip for Windows: If 'pip' is not recognized, run: py -m pip install -r requirements.txt)
```

### 3. Dependencies
* `customtkinter` (Modern Dark/Navy GUI framework)
* `aiohttp` (High-performance async HTTP client)
* `mutagen` (Audiophile FLAC Vorbis & ID3 tagging)
* `Pillow` (High-resolution cover art processing)
* `imageio-ffmpeg` (Audio preview playback engine)
* `packaging` (Compatibility utility)

---

## 🔑 Q-Buz Authentication Guide

Because Q-Buz blocks direct email & password logins on many modern accounts (particularly accounts created via Google, Apple, or recent registrations), the primary and most reliable method is using your **Web Session Token (`user_auth_token`)**.

### How to Retrieve Your Web Session Token:
1. Open your browser (Chrome, Edge, Firefox, Brave) and visit the official web player (**play.q-buz.com**).
2. Log in to your Q-Buz account.
3. Press **F12** on your keyboard (or right-click anywhere and choose **Inspect**) to open **Developer Tools**.
4. Navigate to the **Application** tab (in Chrome/Edge) or **Storage** tab (in Firefox).
5. In the left sidebar, expand **Local Storage** $\rightarrow$ `https://play.q-buz...` (the web player origin).
6. Look for the key named **`localuser`**.
7. In the value column, copy either:
   - The string inside `"token"` or `"userAuthToken"` (e.g. `pssuHJXxS2jl2...`), **OR**
   - Simply copy the **entire JSON object** found in `localuser`.
8. Open QBZ-RIP, go to **⚙️ Settings**, paste into the token input box, and click **Sign In with Token**.
9. The app will automatically validate your session and display your active subscription plan.

---

## 👥 Multi-User & Account Switching

### Scenario A: Switching Accounts on the Same Machine
1. Go to the **⚙️ Settings** tab.
2. Click the red **Logout** button. The previous session is cleared immediately.
3. Copy the token from the new account (via `play.q-buz.com` in the browser).
4. Paste it into the token field and click **Sign In with Token**.
5. The identity and subscription tier of the new user will activate instantly.

### Scenario B: Using on Another Computer
1. Copy or clone the `qbz-rip` folder to the target computer.
2. Run the application with `python -B main.py`.
3. Open **⚙️ Settings** and log in with your token.
4. Settings for each machine are saved in isolation at `%USERPROFILE%\.qbz_rip\config.json`.

---

## 🎮 How to Use

### 1. Launching the App
```bash
# Recommended command (bypasses bytecode cache errors on Python 3.14):
python -B main.py
```

### 2. Searching & Downloading
1. In the **🔍 Search** tab, enter:
   - **Song or Artist Name**: e.g. `Daft Punk`, `Billie Eilish`, `Norah Jones`
   - **Direct Q-Buz URL**: e.g. `https://play.q-buz.com/album/0060253786968`
   - **Direct Track / Album ID**: e.g. `15302127` or `0060253786968`
   - **External Streaming Link**: Spotify, Apple Music, Tidal, Deezer, YouTube, SoundCloud, Bandcamp, Amazon Music.
2. Click **▶ Preview** on search results to hear a 30-second high-fidelity audio clip before downloading.
3. Click **Download**:
   - Individual tracks queue immediately.
   - For Albums or Playlists, an **Interactive Track Selection Checklist** opens, allowing you to select specific tracks!

### 3. Batch Import (Multi-Link Download)
1. Click the **📋 Batch Import** button next to the search bar or in the Queue header.
2. Paste multiple URLs or IDs (one per line).
3. You can also click **📁 Load .txt File** to import a list of links.
4. Click **🚀 Queue All Links** — all valid tracks and albums will be resolved and queued automatically!

### 4. Queue Monitoring
* Switch to the **📥 Queue Monitor** tab to watch live download speeds and progress bars.
* Control buttons on each item:
  - ⏸ **Pause / Resume**: Temporarily pause or resume a specific download.
  - ✖ **Cancel**: Stop and remove an item from the queue.
  - ⬆ **Move to Top**: Bump a track to the front of the queue.
  - 🔁 **Retry**: Instantly re-queue a failed download with a single click.
  - 📁 **Reveal**: Open and select the downloaded file in Windows Explorer.

---

## ⚙️ Configuration

Application settings can be managed via the GUI or edited in `~/.qbz_rip/config.json`:

```json
{
    "format_id": 27,
    "download_directory": "C:\\Users\\YourUsername\\Music\\Q-Buz",
    "naming_template": "{artist}/{album}/{track_num} - {title}.{ext}",
    "concurrent_downloads": 3,
    "play_sound_on_complete": true,
    "app_id": "798273057",
    "app_secret": "abb21364945c0583309667d13ca3d93a"
}
```

### Supported Naming Template Variables
* `{artist}`: Album or Track artist name
* `{album}`: Album title
* `{title}`: Track title
* `{track_num}`: Zero-padded track number (`01`, `02`)
* `{total_tracks}`: Zero-padded total tracks in album (`12`)
* `{disc_num}`: Zero-padded disc number (`01`, `02`)
* `{total_discs}`: Zero-padded total discs in album (`01`)
* `{genre}`: Music genre name (`Jazz`, `Rock`, `Classical`)
* `{year}`: 4-digit release year (`2024`)
* `{bit_depth}`: Formatted bit depth (`24bit` or `16bit`)
* `{sample_rate}`: Formatted sampling rate (`192kHz`, `96kHz`, `44.1kHz`)
* `{quality}`: Combined audiophile spec label (`24bit-192kHz`)
* `{label}`: Record label name
* `{composer}`: Track composer name
* `{isrc}`: International Standard Recording Code
* `{ext}`: File extension (`flac` or `mp3`)

---

## 🛠️ Troubleshooting & FAQ

#### Q: Why do I get `'pip' is not recognized as an internal or external command` on Windows?
**A:** This occurs when Python's `Scripts` directory has not been added to your Windows system `PATH` variable. You have 3 easy ways to fix it:
1. **Method 1 (Easiest — 1-Click):** Simply double-click **`install.bat`** in the project folder. It uses the Windows Python launcher (`py`) to locate Python and install all dependencies automatically.
2. **Method 2 (CLI):** Run the command using the Python launcher directly:
   ```bash
   py -m pip install -r requirements.txt
   ```
3. **Method 3 (Fix PATH permanently):** Re-run the official installer from [python.org](https://www.python.org/), click **Modify**, and check the box **"Add python.exe to PATH"**.

#### Q: Why do I get `Q-Buz API error (404): No result matching given argument` on certain tracks?
**A:** A 404 error from the Q-Buz API means the track or release has been **delisted**, removed by the record label, or is **geo-restricted** in your account's registered country/region. QBZ-RIP catches this cleanly, marks the track with a warning, and continues downloading the rest of your queue smoothly without crashing.

#### Q: Why do I get `Q-Buz API error (400): Invalid or missing app_id parameter`?
**A:** The Q-Buz service requires an active, matching client `app_id`. The application includes automated recovery:
1. QBZ-RIP automatically scrapes active client App IDs from the official Web Player bundle.
2. If issues persist, open **⚙️ Settings** and click **🔍 Auto-Detect**.
3. Or open the web player (`play.q-buz.com`) -> press F12 -> Network tab (filter: `api.json/0.2`), inspect a request header, copy the **`X-App-Id`** value (9 digits), and paste it into Settings.

#### Q: Why do I see `ValueError: bad marshal data` when running with Python 3.14?
**A:** Python 3.14 is a pre-release version that can occasionally corrupt cached `.pyc` bytecode. Always run the app with the `-B` flag (or double-click **`run.bat`**):
```bash
python -B main.py
```
The `-B` flag tells Python not to write or read bytecode cache files, ensuring clean execution.

#### Q: Why is my session token rejected (`Token Verification Failed`)?
**A:** Q-Buz web session tokens are browser-based. If you logged out in your browser or the session expired, refresh the web player (`play.q-buz.com`), copy the new `userAuthToken` from Developer Tools (`localuser`), and save it again in Settings.

#### Q: Where are lyrics stored?
**A:** QBZ-RIP automatically queries synchronized lyrics from LRCLIB. A `.lrc` file is saved in the same directory alongside the audio file, and lyrics are also embedded directly into FLAC Vorbis comments (`LYRICS`, `UNSYNCEDLYRICS`) or MP3 ID3 tags (`USLT`).

#### Q: Where is the Digital Booklet PDF saved?
**A:** If an album includes official digital liner notes / booklets in its Q-Buz goodies, the PDF is downloaded automatically and saved as `Digital Booklet.pdf` in the album folder.

---

## 📁 Project Architecture

```
qbz-rip/
├── install.bat                 # 1-Click Windows automatic dependency installer
├── run.bat                     # 1-Click Windows launcher (bypasses bytecode cache)
├── main.py                     # Application entry point & asyncio event loop
├── requirements.txt            # Python dependencies
├── README.md                   # Complete documentation & audiophile guide
└── qbz_rip/
    ├── __init__.py             # Package initialization
    ├── config.py               # Settings manager & candidate App ID store
    ├── api.py                  # Async Q-Buz REST API client & MD5 signer
    ├── bundle_scraper.py       # Dynamic Q-Buz web player bundle scraper
    ├── downloader.py           # Bit-perfect stream downloader, Range resume & FLAC tagger
    ├── lyrics.py               # LRCLIB synced lyrics fetcher & .lrc generator
    ├── link_resolver.py        # Multi-platform link parser (Spotify/Apple/Tidal/Bandcamp/etc.)
    └── ui.py                   # CustomTkinter GUI, 60 FPS card renderer & parallel queue monitor
```

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for more information.
