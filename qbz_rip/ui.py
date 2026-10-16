import asyncio
import gc
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
try:
    import winsound
except ImportError:
    winsound = None
import aiohttp
import customtkinter as CTk
from PIL import Image
import tkinter.filedialog as filedialog
import tkinter.messagebox as messagebox

from .config import FORMAT_LABELS, DEFAULT_APP_ID, DEFAULT_APP_SECRET
from .downloader import DownloadManager, sanitize_filename
from .link_resolver import parse_qobuz_url, is_external_music_link, resolve_external_link

# Styling constants - Q-Buz Cyan & Navy Studio Palette
COLOR_DARK_BG = "#0f141c"
COLOR_SIDEBAR_BG = "#151c27"
COLOR_FRAME_BG = "#1a2332"
COLOR_ACCENT = "#00b4d8"
COLOR_ACCENT_HOVER = "#48cae4"
COLOR_TEXT_MUTED = "#8da2b5"
COLOR_GOLD = "#ffb703"

def open_in_file_manager(path):
    """Opens a folder or selects a file in file manager across Windows, macOS, and Linux."""
    try:
        norm = os.path.normpath(path)
        if os.name == 'nt':
            if os.path.isfile(norm):
                subprocess.run(["explorer.exe", "/select,", norm], check=False)
            elif os.path.isdir(norm):
                os.startfile(norm)
        elif sys.platform == 'darwin':
            if os.path.isfile(norm):
                subprocess.run(["open", "-R", norm], check=False)
            elif os.path.isdir(norm):
                subprocess.run(["open", norm], check=False)
        else:  # Linux
            target = os.path.dirname(norm) if os.path.isfile(norm) else norm
            subprocess.run(["xdg-open", target], check=False)
    except Exception as e:
        print(f"Failed to open file manager: {e}")

def get_qobuz_badge(item):
    """Generates quality badge text and color based on maximum bit depth and sample rate."""
    bit_depth = item.get("maximum_bit_depth") or item.get("bit_depth")
    sample_rate = item.get("maximum_sampling_rate") or item.get("sampling_rate")
    hires = item.get("hires", False) or item.get("hires_streamable", False)

    if bit_depth and sample_rate:
        try:
            s_float = float(sample_rate)
            sr_str = f"{int(s_float)}" if s_float.is_integer() else f"{s_float}"
        except Exception:
            sr_str = str(sample_rate)

        if bit_depth >= 24 and float(sample_rate) >= 176.4:
            return f"MASTER • {bit_depth}-bit/{sr_str}kHz", COLOR_GOLD, "black"
        elif bit_depth >= 24:
            return f"HI-RES • {bit_depth}-bit/{sr_str}kHz", COLOR_ACCENT, "black"
        else:
            return f"CD • {bit_depth}-bit/{sr_str}kHz", "#48cae4", "black"
    elif hires:
        return "HI-RES 24-BIT", COLOR_ACCENT, "black"
    else:
        return "LOSSLESS 16-BIT", "#3a506b", "white"

def extract_cover_url(item, album_info=None):
    """Robustly extracts best available cover art URL across tracks, albums, playlists, and artists."""
    candidates = []

    # 1. Album info (for tracks)
    if album_info and isinstance(album_info, dict):
        candidates.append(album_info.get("image"))
        candidates.append(album_info.get("cover"))

    # 2. Item itself
    if isinstance(item, dict):
        candidates.append(item.get("image"))
        candidates.append(item.get("cover"))
        candidates.append(item.get("picture"))
        candidates.append(item.get("images300"))
        candidates.append(item.get("images_square"))

    for cand in candidates:
        if not cand:
            continue
        if isinstance(cand, dict):
            for k in ["small", "thumbnail", "medium", "large", "default"]:
                val = cand.get(k)
                if val and isinstance(val, str) and val.startswith("http"):
                    return val
        elif isinstance(cand, list) and len(cand) > 0:
            first = cand[0]
            if isinstance(first, str) and first.startswith("http"):
                return first
            elif isinstance(first, dict):
                for k in ["small", "thumbnail", "medium", "large"]:
                    val = first.get(k)
                    if val and isinstance(val, str) and val.startswith("http"):
                        return val
        elif isinstance(cand, str) and cand.startswith("http"):
            return cand

    return None

class TrackSelectionModal(CTk.CTkToplevel):
    """Interactive Checklist Modal for selecting specific tracks to download from an Album or Playlist."""

    def __init__(self, parent, title_name, track_list, on_confirm):
        super().__init__(parent)
        self.title("Select Tracks to Download")
        self.geometry("640x550")
        self.minsize(500, 400)
        self.configure(fg_color=COLOR_DARK_BG)
        
        self.track_list = track_list
        self.on_confirm = on_confirm
        self.check_vars = []
        
        self.transient(parent)
        self.grab_set()

        # Header
        header = CTk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 10))
        
        lbl_title = CTk.CTkLabel(
            header, 
            text=f"Select Tracks: {title_name}", 
            font=CTk.CTkFont(size=16, weight="bold"),
            anchor="w"
        )
        lbl_title.pack(fill="x")
        
        # Toolbar
        toolbar = CTk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=20, pady=(5, 10))
        
        btn_all = CTk.CTkButton(toolbar, text="☑ Select All", width=95, height=30, fg_color=COLOR_FRAME_BG, hover_color="#2b374a", command=self.select_all)
        btn_all.pack(side="left", padx=(0, 6))
        
        btn_none = CTk.CTkButton(toolbar, text="☐ Deselect All", width=105, height=30, fg_color=COLOR_FRAME_BG, hover_color="#2b374a", command=self.deselect_all)
        btn_none.pack(side="left", padx=(0, 6))

        btn_inv = CTk.CTkButton(toolbar, text="🔄 Invert", width=80, height=30, fg_color=COLOR_FRAME_BG, hover_color="#2b374a", command=self.invert_selection)
        btn_inv.pack(side="left")
        
        self.count_lbl = CTk.CTkLabel(toolbar, text="", font=CTk.CTkFont(size=12, weight="bold"), text_color=COLOR_ACCENT)
        self.count_lbl.pack(side="right", padx=5)

        # Scrollable list
        scroll = CTk.CTkScrollableFrame(self, fg_color=COLOR_FRAME_BG, corner_radius=8)
        scroll.pack(fill="both", expand=True, padx=20, pady=(0, 15))

        for idx, trk in enumerate(self.track_list):
            if not isinstance(trk, dict):
                continue

            row = CTk.CTkFrame(scroll, fg_color="transparent", height=40)
            row.pack(fill="x", pady=2, padx=4)
            row.pack_propagate(False)

            var = CTk.BooleanVar(value=True)
            self.check_vars.append((trk, var))

            cb = CTk.CTkCheckBox(row, text="", variable=var, width=24, command=self.update_counter)
            cb.pack(side="left", padx=(5, 5))

            raw_trk = trk.get("track_number")
            try:
                trk_num = int(raw_trk) if raw_trk is not None else (idx + 1)
            except (ValueError, TypeError):
                trk_num = idx + 1

            raw_disc = trk.get("media_number")
            try:
                disc_num = int(raw_disc) if raw_disc is not None else 1
            except (ValueError, TypeError):
                disc_num = 1

            num_str = f"{disc_num}-{trk_num:02d}" if disc_num > 1 else f"{trk_num:02d}"

            num_lbl = CTk.CTkLabel(row, text=num_str, font=CTk.CTkFont(family="Consolas", size=11), text_color=COLOR_TEXT_MUTED, width=40, anchor="w")
            num_lbl.pack(side="left", padx=(0, 6))

            # Duration packed to right first
            dur_sec = trk.get("duration")
            if dur_sec is not None:
                try:
                    mins, secs = divmod(int(dur_sec), 60)
                    dur_lbl = CTk.CTkLabel(row, text=f"{mins}:{secs:02d}", font=CTk.CTkFont(family="Consolas", size=11), text_color=COLOR_TEXT_MUTED, width=45, anchor="e")
                    dur_lbl.pack(side="right", padx=(5, 10))
                except (ValueError, TypeError):
                    pass

            # Title & artist
            t_title = trk.get("title") or f"Track {trk.get('id', idx + 1)}"
            performer = trk.get("performer") or {}
            t_artist = performer.get("name") if isinstance(performer, dict) else ""
            if not t_artist and isinstance(trk.get("artist"), dict):
                t_artist = trk.get("artist", {}).get("name") or ""
            if not t_artist and isinstance(trk.get("album"), dict):
                alb_art = trk.get("album", {}).get("artist") or {}
                if isinstance(alb_art, dict):
                    t_artist = alb_art.get("name") or ""
            
            info_frame = CTk.CTkFrame(row, fg_color="transparent")
            info_frame.pack(side="left", fill="both", expand=True)

            display_txt = f"{t_title}  •  {t_artist}" if t_artist else t_title
            trk_lbl = CTk.CTkLabel(info_frame, text=display_txt, font=CTk.CTkFont(size=12), anchor="w")
            trk_lbl.pack(side="left", fill="x", expand=True)

            def toggle_item(v=var):
                v.set(not v.get())
                self.update_counter()

            row.bind("<Button-1>", lambda e, ti=toggle_item: ti())
            num_lbl.bind("<Button-1>", lambda e, ti=toggle_item: ti())
            info_frame.bind("<Button-1>", lambda e, ti=toggle_item: ti())
            trk_lbl.bind("<Button-1>", lambda e, ti=toggle_item: ti())

        # Footer
        footer = CTk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=20, pady=(0, 15))
        
        cancel_btn = CTk.CTkButton(footer, text="Cancel", width=90, fg_color=COLOR_FRAME_BG, hover_color="#2b374a", command=self.destroy)
        cancel_btn.pack(side="right", padx=(10, 0))

        self.confirm_btn = CTk.CTkButton(footer, text="Download Selected", fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, text_color="black", font=CTk.CTkFont(weight="bold"), command=self.confirm_selection)
        self.confirm_btn.pack(side="right")

        self.update_counter()

    def select_all(self):
        for _, var in self.check_vars:
            var.set(True)
        self.update_counter()

    def deselect_all(self):
        for _, var in self.check_vars:
            var.set(False)
        self.update_counter()

    def invert_selection(self):
        for _, var in self.check_vars:
            var.set(not var.get())
        self.update_counter()

    def update_counter(self):
        selected = sum(1 for _, v in self.check_vars if v.get())
        total = len(self.check_vars)
        self.count_lbl.configure(text=f"Selected: {selected} / {total}")
        if selected == 0:
            self.confirm_btn.configure(text="Select at least 1", state="disabled", fg_color="#3a506b")
        else:
            self.confirm_btn.configure(text=f"Download Selected ({selected})", state="normal", fg_color=COLOR_ACCENT)

    def confirm_selection(self):
        selected_tracks = [t for t, v in self.check_vars if v.get()]
        if selected_tracks:
            self.destroy()
            self.on_confirm(selected_tracks)

class BatchImportModal(CTk.CTkToplevel):
    """Modal dialog for batch importing and downloading multiple URLs / track IDs."""

    def __init__(self, parent, on_process_batch):
        super().__init__(parent)
        self.title("Batch URL / ID Importer")
        self.geometry("640x520")
        self.minsize(520, 380)
        self.configure(fg_color=COLOR_DARK_BG)
        self.on_process_batch = on_process_batch

        self.transient(parent)
        self.grab_set()

        # Header
        header = CTk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(20, 10))

        CTk.CTkLabel(
            header,
            text="📋 Batch Import (Paste Multiple URLs / IDs)",
            font=CTk.CTkFont(size=16, weight="bold"),
            text_color=COLOR_ACCENT
        ).pack(anchor="w")

        guide_txt = "Paste multiple links or IDs below (one per line).\nSupports Q-Buz, Spotify, Apple Music, Tidal, Deezer, YouTube, SoundCloud, Bandcamp, and Amazon Music."
        CTk.CTkLabel(header, text=guide_txt, font=CTk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED, justify="left").pack(anchor="w", pady=(4, 0))

        # Text Area
        self.textbox = CTk.CTkTextbox(self, fg_color=COLOR_FRAME_BG, font=CTk.CTkFont(family="Consolas", size=12))
        self.textbox.pack(fill="both", expand=True, padx=20, pady=(5, 10))
        self.textbox.focus_set()

        # Toolbar
        toolbar = CTk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=20, pady=(0, 15))

        paste_btn = CTk.CTkButton(toolbar, text="📋 Paste Clipboard", width=120, height=32, fg_color=COLOR_FRAME_BG, hover_color="#2b374a", command=self.paste_clipboard)
        paste_btn.pack(side="left", padx=(0, 6))

        file_btn = CTk.CTkButton(toolbar, text="📁 Load .txt File", width=110, height=32, fg_color=COLOR_FRAME_BG, hover_color="#2b374a", command=self.load_from_file)
        file_btn.pack(side="left", padx=(0, 6))

        clear_btn = CTk.CTkButton(toolbar, text="Clear", width=70, height=32, fg_color=COLOR_FRAME_BG, hover_color="#2b374a", command=lambda: self.textbox.delete("1.0", "end"))
        clear_btn.pack(side="left")

        cancel_btn = CTk.CTkButton(toolbar, text="Cancel", width=80, height=32, fg_color=COLOR_FRAME_BG, hover_color="#2b374a", command=self.destroy)
        cancel_btn.pack(side="right", padx=(8, 0))

        self.submit_btn = CTk.CTkButton(
            toolbar,
            text="🚀 Queue All Links",
            height=32,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            text_color="black",
            font=CTk.CTkFont(weight="bold"),
            command=self.submit
        )
        self.submit_btn.pack(side="right")

    def paste_clipboard(self):
        try:
            txt = self.clipboard_get()
            if txt:
                self.textbox.insert("end", txt + "\n")
        except Exception:
            pass

    def load_from_file(self):
        fpath = filedialog.askopenfilename(filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")])
        if fpath:
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    self.textbox.insert("end", content + "\n")
            except Exception as e:
                messagebox.showerror("File Error", f"Could not read file: {e}")

    def submit(self):
        raw = self.textbox.get("1.0", "end").strip()
        lines = [line.strip() for line in raw.splitlines() if line.strip() and not line.strip().startswith("#")]
        if not lines:
            messagebox.showwarning("Empty List", "Please paste at least one URL or ID.")
            return

        self.destroy()
        self.on_process_batch(lines)

class QBZRipUI(CTk.CTk):
    """Main CustomTkinter application window for QBZ Rip."""

    def __init__(self, api, config, async_loop):
        super().__init__()
        self.api = api
        self.config = config
        self.async_loop = async_loop
        self.downloader = DownloadManager(self.api, self.config)

        self.title("QBZ RIP - 24-bit/192kHz Studio Master Hi-Res Downloader")
        self.geometry("980x620")
        self.minsize(820, 520)
        self.configure(fg_color=COLOR_DARK_BG)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # State
        self.queue_items = {}
        self.queue_order = []
        self.pending_downloads = []
        self._image_refs = []
        self._image_cache = {}
        self._img_semaphore = asyncio.Semaphore(6)
        self._render_batch_id = 0
        self._search_gen = 0
        self.preview_proc = None
        self.preview_tid = None
        self._preview_wav = None
        self._active_preview_btn = None
        self._background_futures = set()
        self._worker_running = True

        # Search & Catalog State
        self.recent_searches = list(self.config.recent_searches) if hasattr(self.config, "recent_searches") else []
        self._raw_search_items = []
        self._current_search_query = ""
        self._current_search_type = "all"
        self._current_search_offset = 0
        self._current_search_total = 0
        self._is_loading_more = False

        # Global Keybindings
        self.bind("<Control-f>", lambda e: self.focus_search())
        self.bind("<Control-F>", lambda e: self.focus_search())
        self.bind("<Escape>", lambda e: self.clear_search())

        self.setup_layout()
        self._worker_future = self.run_async(self.download_worker())
        self.check_login_status()
        self.after(500, self.load_session)

    def focus_search(self):
        self.switch_view("search")
        if hasattr(self, "search_entry"):
            self.search_entry.focus_set()
            self.search_entry.select_range(0, "end")

    def run_async(self, coro):
        """Helper to run a coroutine in background event loop with strong reference retention."""
        fut = asyncio.run_coroutine_threadsafe(coro, self.async_loop)
        self._background_futures.add(fut)
        fut.add_done_callback(lambda f: self._background_futures.discard(f))
        return fut

    def setup_layout(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # --- Sidebar ---
        self.sidebar = CTk.CTkFrame(self, width=200, corner_radius=0, fg_color=COLOR_SIDEBAR_BG)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(4, weight=1)

        logo_title = CTk.CTkLabel(self.sidebar, text="⚡ QBZ RIP", font=CTk.CTkFont(size=20, weight="bold"), text_color=COLOR_ACCENT)
        logo_title.grid(row=0, column=0, padx=20, pady=(25, 2), sticky="w")
        
        logo_sub = CTk.CTkLabel(self.sidebar, text="24-bit/192kHz Studio Master", font=CTk.CTkFont(size=11), text_color=COLOR_GOLD)
        logo_sub.grid(row=1, column=0, padx=20, pady=(0, 25), sticky="w")

        # Nav Buttons
        self.btn_search = CTk.CTkButton(self.sidebar, text="🔍 Search", height=40, fg_color="transparent", hover_color=COLOR_FRAME_BG, anchor="w", font=CTk.CTkFont(size=13, weight="bold"), command=lambda: self.switch_view("search"))
        self.btn_search.grid(row=2, column=0, sticky="ew", padx=10, pady=4)

        self.btn_queue = CTk.CTkButton(self.sidebar, text="📥 Queue Monitor", height=40, fg_color="transparent", hover_color=COLOR_FRAME_BG, anchor="w", font=CTk.CTkFont(size=13, weight="bold"), command=lambda: self.switch_view("queue"))
        self.btn_queue.grid(row=3, column=0, sticky="ew", padx=10, pady=4)

        self.btn_settings = CTk.CTkButton(self.sidebar, text="⚙️ Settings", height=40, fg_color="transparent", hover_color=COLOR_FRAME_BG, anchor="w", font=CTk.CTkFont(size=13, weight="bold"), command=lambda: self.switch_view("settings"))
        self.btn_settings.grid(row=5, column=0, sticky="ew", padx=10, pady=4)

        # Login Info Card in Sidebar
        self.user_card = CTk.CTkFrame(self.sidebar, fg_color=COLOR_FRAME_BG, corner_radius=8)
        self.user_card.grid(row=6, column=0, padx=10, pady=15, sticky="ew")

        self.user_name_lbl = CTk.CTkLabel(self.user_card, text="Not Logged In", font=CTk.CTkFont(size=12, weight="bold"), anchor="w")
        self.user_name_lbl.pack(fill="x", padx=10, pady=(8, 2))

        self.user_sub_lbl = CTk.CTkLabel(self.user_card, text="Hi-Res Studio Master", font=CTk.CTkFont(size=10), text_color=COLOR_TEXT_MUTED, anchor="w")
        self.user_sub_lbl.pack(fill="x", padx=10, pady=(0, 8))

        # --- Main Container ---
        self.main_container = CTk.CTkFrame(self, fg_color="transparent")
        self.main_container.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_container.grid_rowconfigure(0, weight=1)
        self.main_container.grid_columnconfigure(0, weight=1)

        self.create_search_view()
        self.create_queue_view()
        self.create_settings_view()

        self.switch_view("search")

    def switch_view(self, name):
        """Switches visible active view."""
        self.search_view.grid_forget()
        self.queue_view.grid_forget()
        self.settings_view.grid_forget()

        self.btn_search.configure(fg_color=COLOR_FRAME_BG if name == "search" else "transparent")
        self.btn_queue.configure(fg_color=COLOR_FRAME_BG if name == "queue" else "transparent")
        self.btn_settings.configure(fg_color=COLOR_FRAME_BG if name == "settings" else "transparent")

        if name == "search":
            self.search_view.grid(row=0, column=0, sticky="nsew")
        elif name == "queue":
            self.queue_view.grid(row=0, column=0, sticky="nsew")
        elif name == "settings":
            self.settings_view.grid(row=0, column=0, sticky="nsew")

    # --- Search View ---

    def create_search_view(self):
        self.search_view = CTk.CTkFrame(self.main_container, fg_color="transparent")
        self.search_view.grid_rowconfigure(3, weight=1)
        self.search_view.grid_columnconfigure(0, weight=1)

        # 1. Primary Controls Bar
        ctrl_bar = CTk.CTkFrame(self.search_view, fg_color="transparent")
        ctrl_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctrl_bar.grid_columnconfigure(0, weight=1)

        entry_box = CTk.CTkFrame(ctrl_bar, fg_color="transparent")
        entry_box.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        entry_box.grid_columnconfigure(0, weight=1)

        self.search_entry = CTk.CTkEntry(
            entry_box,
            placeholder_text="Search terms, ISRC, Barcode, or paste Qobuz / Spotify / Apple Music / Tidal URL...",
            height=40,
            font=CTk.CTkFont(size=13)
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.search_entry.bind("<Return>", lambda e: self.trigger_search())

        self.clear_btn = CTk.CTkButton(
            entry_box,
            text="✕",
            width=36,
            height=40,
            fg_color=COLOR_FRAME_BG,
            hover_color="#2b374a",
            text_color=COLOR_TEXT_MUTED,
            font=CTk.CTkFont(size=13, weight="bold"),
            command=self.clear_search
        )
        self.clear_btn.grid(row=0, column=1, sticky="e")

        self.search_type_menu = CTk.CTkOptionMenu(
            ctrl_bar,
            values=["All", "Tracks", "Albums", "Artists", "Playlists"],
            width=105,
            height=40,
            fg_color=COLOR_FRAME_BG,
            button_color=COLOR_FRAME_BG,
            button_hover_color="#2b374a",
            dropdown_fg_color=COLOR_FRAME_BG
        )
        self.search_type_menu.grid(row=0, column=1, sticky="w", padx=(0, 8))
        self.search_type_menu.set("All")

        self.search_btn = CTk.CTkButton(
            ctrl_bar,
            text="Search",
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER,
            text_color="black",
            width=95,
            height=40,
            font=CTk.CTkFont(size=13, weight="bold"),
            command=self.trigger_search
        )
        self.search_btn.grid(row=0, column=2, sticky="e")

        self.batch_btn = CTk.CTkButton(
            ctrl_bar,
            text="📋 Batch Import",
            fg_color=COLOR_FRAME_BG,
            hover_color="#2b374a",
            text_color="white",
            width=110,
            height=40,
            font=CTk.CTkFont(size=12, weight="bold"),
            command=self.open_batch_import_modal
        )
        self.batch_btn.grid(row=0, column=3, sticky="e", padx=(8, 0))

        # 2. Audiophile Filters & Sorting Toolbar
        toolbar = CTk.CTkFrame(self.search_view, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        toolbar.grid_columnconfigure(2, weight=1)

        self.filter_quality_menu = CTk.CTkOptionMenu(
            toolbar,
            values=["All Qualities", "✨ Hi-Res (24-bit+)", "🏆 192kHz Master", "💿 CD Lossless (16-bit)"],
            width=150,
            height=28,
            font=CTk.CTkFont(size=11),
            fg_color=COLOR_FRAME_BG,
            button_color=COLOR_FRAME_BG,
            button_hover_color="#2b374a",
            dropdown_fg_color=COLOR_FRAME_BG,
            command=lambda v: self.apply_filter_and_sort()
        )
        self.filter_quality_menu.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.sort_menu = CTk.CTkOptionMenu(
            toolbar,
            values=["Sort: Best Match", "Sort: Highest Quality", "Sort: Newest", "Sort: Title (A-Z)"],
            width=150,
            height=28,
            font=CTk.CTkFont(size=11),
            fg_color=COLOR_FRAME_BG,
            button_color=COLOR_FRAME_BG,
            button_hover_color="#2b374a",
            dropdown_fg_color=COLOR_FRAME_BG,
            command=lambda v: self.apply_filter_and_sort()
        )
        self.sort_menu.grid(row=0, column=1, sticky="w", padx=(0, 10))

        self.results_stats_lbl = CTk.CTkLabel(
            toolbar,
            text="",
            font=CTk.CTkFont(size=11),
            text_color=COLOR_TEXT_MUTED,
            anchor="e"
        )
        self.results_stats_lbl.grid(row=0, column=2, sticky="e")

        # 3. Recent Searches Chips Frame
        self.recent_frame = CTk.CTkFrame(self.search_view, fg_color="transparent")
        self.recent_frame.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        self.update_recent_searches_ui()

        # 4. Results Scrollable Frame
        self.results_scroll = CTk.CTkScrollableFrame(self.search_view, fg_color=COLOR_FRAME_BG)
        self.results_scroll.grid(row=3, column=0, sticky="nsew")

    def update_recent_searches_ui(self):
        for child in self.recent_frame.winfo_children():
            child.destroy()
        if not self.recent_searches:
            self.recent_frame.grid_remove()
            return
        self.recent_frame.grid()
        lbl = CTk.CTkLabel(self.recent_frame, text="Recent:", font=CTk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED)
        lbl.pack(side="left", padx=(0, 6))
        for q in self.recent_searches[:5]:
            btn = CTk.CTkButton(
                self.recent_frame,
                text=q if len(q) <= 22 else f"{q[:20]}...",
                height=22,
                font=CTk.CTkFont(size=10),
                fg_color="#182230",
                hover_color="#233245",
                text_color="#a0b4c8",
                corner_radius=11,
                command=lambda term=q: self.quick_search(term)
            )
            btn.pack(side="left", padx=3)
        clear_btn = CTk.CTkButton(
            self.recent_frame,
            text="✕ Clear",
            height=22,
            font=CTk.CTkFont(size=10),
            fg_color="transparent",
            hover_color="#2b374a",
            text_color=COLOR_TEXT_MUTED,
            command=self.clear_recent_searches
        )
        clear_btn.pack(side="left", padx=6)

    def quick_search(self, term):
        self.search_entry.delete(0, "end")
        self.search_entry.insert(0, term)
        self.trigger_search()

    def clear_recent_searches(self):
        self.recent_searches.clear()
        if hasattr(self.config, "recent_searches"):
            self.config.recent_searches = []
            self.config.save()
        self.update_recent_searches_ui()

    def clear_search(self):
        self._render_batch_id = getattr(self, "_render_batch_id", 0) + 1
        self.stop_preview()
        self.search_entry.delete(0, "end")
        self.search_entry.focus_set()

    def show_search_status(self, text):
        self._render_batch_id = getattr(self, "_render_batch_id", 0) + 1
        self.stop_preview()
        for child in self.results_scroll.winfo_children():
            child.destroy()
        lbl = CTk.CTkLabel(self.results_scroll, text=text, font=CTk.CTkFont(size=14, slant="italic"))
        lbl.pack(pady=40)

    def trigger_search(self):
        query = self.search_entry.get().strip()
        if not query:
            return

        # Record in recent searches if not a URL
        if not is_external_music_link(query) and not parse_qobuz_url(query)[0]:
            if query in self.recent_searches:
                self.recent_searches.remove(query)
            self.recent_searches.insert(0, query)
            self.recent_searches = self.recent_searches[:8]
            if hasattr(self.config, "recent_searches"):
                self.config.recent_searches = self.recent_searches
                self.config.save()
            self.update_recent_searches_ui()

        self._search_gen += 1
        my_gen = self._search_gen

        self.search_btn.configure(state="disabled", text="Searching...")
        self.show_search_status("Searching Qobuz catalog...")

        search_type = self.search_type_menu.get().lower()
        self._current_search_query = query
        self._current_search_type = search_type
        self._current_search_offset = 0
        self._raw_search_items = []

        self.run_async(self.perform_search(query, search_type, my_gen))

    def finish_search(self, data, search_type, error_msg=None, gen=None):
        if self.search_btn.winfo_exists():
            self.search_btn.configure(state="normal", text="Search")
        if gen is not None and self._search_gen != gen:
            return
        if error_msg:
            messagebox.showerror("Search Error", error_msg)
        elif data is not None:
            self.populate_results(data, search_type)

    async def perform_search(self, query, search_type, gen):
        # 1. External Links (Spotify, Apple, Tidal, Deezer, YouTube, SoundCloud)
        if is_external_music_link(query):
            self.after(0, lambda: self.show_search_status("Resolving external streaming link..."))
            resolved_query, resolved_type, display_info, service_name = await resolve_external_link(query)
            if resolved_query:
                target_type = resolved_type or ("tracks" if search_type in ("all", "everything") else search_type)
                self.after(0, lambda t=target_type.capitalize(): self.search_type_menu.set(t))
                svc_title = service_name or "Service"
                self.after(0, lambda info=display_info, svc=svc_title: self.show_search_status(f"Found on {svc}: {info}\nSearching Q-Buz catalog..."))
                try:
                    res = await self.api.smart_search(resolved_query, search_type=target_type, limit=50)
                    self.after(0, self.finish_search, res, target_type, None, gen)
                except Exception as e:
                    self.after(0, self.finish_search, None, target_type, f"Q-Buz catalog search error: {e}", gen)
                return
            else:
                self.after(0, self.finish_search, None, search_type, "Could not extract metadata from this link. Please try searching by song title or artist directly.", gen)
                return

        # 2. Direct Q-Buz URLs or Raw IDs
        q_type, q_id = parse_qobuz_url(query)
        if q_type:
            try:
                if q_type == "raw_id":
                    self.after(0, lambda: self.show_search_status(f"Fetching Q-Buz release (ID: {q_id})..."))
                    if search_type == "albums" or len(q_id) >= 12:
                        try:
                            album = await self.api.get_album(q_id)
                            if album and isinstance(album, dict) and album.get("id"):
                                self.after(0, lambda: self.search_type_menu.set("Albums"))
                                self.after(0, self.finish_search, {"albums": {"items": [album], "total": 1}}, "albums", None, gen)
                                return
                        except Exception:
                            pass
                        track = await self.api.get_track(q_id)
                        if track and isinstance(track, dict) and track.get("id"):
                            self.after(0, lambda: self.search_type_menu.set("Tracks"))
                            self.after(0, self.finish_search, {"tracks": {"items": [track], "total": 1}}, "tracks", None, gen)
                            return
                    else:
                        try:
                            track = await self.api.get_track(q_id)
                            if track and isinstance(track, dict) and track.get("id"):
                                self.after(0, lambda: self.search_type_menu.set("Tracks"))
                                self.after(0, self.finish_search, {"tracks": {"items": [track], "total": 1}}, "tracks", None, gen)
                                return
                        except Exception:
                            pass
                        album = await self.api.get_album(q_id)
                        if album and isinstance(album, dict) and album.get("id"):
                            self.after(0, lambda: self.search_type_menu.set("Albums"))
                            self.after(0, self.finish_search, {"albums": {"items": [album], "total": 1}}, "albums", None, gen)
                            return
                    self.after(0, self.finish_search, None, search_type, f"No Q-Buz track or album found matching ID {q_id}.", gen)
                    return

                elif q_type == "track":
                    self.after(0, lambda: self.search_type_menu.set("Tracks"))
                    self.after(0, lambda: self.show_search_status(f"Fetching Q-Buz track (ID: {q_id})..."))
                    track = await self.api.get_track(q_id)
                    if track and isinstance(track, dict) and track.get("id"):
                        res = {"tracks": {"items": [track], "total": 1}}
                        self.after(0, self.finish_search, res, "tracks", None, gen)
                    else:
                        self.after(0, self.finish_search, None, "tracks", f"Q-Buz track not found or geo-restricted (ID: {q_id}).", gen)

                elif q_type == "album":
                    self.after(0, lambda: self.search_type_menu.set("Albums"))
                    self.after(0, lambda: self.show_search_status(f"Fetching Q-Buz album (ID: {q_id})..."))
                    album = await self.api.get_album(q_id)
                    if album and isinstance(album, dict) and album.get("id"):
                        res = {"albums": {"items": [album], "total": 1}}
                        self.after(0, self.finish_search, res, "albums", None, gen)
                    else:
                        self.after(0, self.finish_search, None, "albums", f"Q-Buz album not found or geo-restricted (ID: {q_id}).", gen)

                elif q_type == "playlist":
                    self.after(0, lambda: self.search_type_menu.set("Playlists"))
                    self.after(0, lambda: self.show_search_status(f"Fetching Q-Buz playlist (ID: {q_id})..."))
                    pl = await self.api.get_playlist(q_id)
                    if pl and isinstance(pl, dict) and pl.get("id"):
                        res = {"playlists": {"items": [pl], "total": 1}}
                        self.after(0, self.finish_search, res, "playlists", None, gen)
                    else:
                        self.after(0, self.finish_search, None, "playlists", f"Q-Buz playlist not found (ID: {q_id}).", gen)

                elif q_type == "artist":
                    self.after(0, lambda: self.search_type_menu.set("Albums"))
                    self.after(0, lambda: self.show_search_status(f"Fetching discography for artist (ID: {q_id})..."))
                    art = await self.api.get_artist(q_id)
                    a_obj = art.get("albums") if isinstance(art, dict) else None
                    if isinstance(a_obj, dict):
                        albums = a_obj.get("items", [])
                    elif isinstance(a_obj, list):
                        albums = a_obj
                    else:
                        albums = []
                    res = {"albums": {"items": albums, "total": len(albums)}}
                    self.after(0, self.finish_search, res, "albums", None, gen)
            except Exception as e:
                self.after(0, self.finish_search, None, search_type, f"Error fetching Q-Buz item: {e}", gen)
            return

        # 3. Smart Catalog Search
        try:
            res = await self.api.smart_search(query, search_type=search_type, limit=50)
            self.after(0, self.finish_search, res, search_type, None, gen)
        except Exception as e:
            self.after(0, self.finish_search, None, search_type, f"Search failed: {e}", gen)

    def populate_results(self, data, search_type):
        self.stop_preview()
        items = []
        total = 0
        effective_type = search_type

        if isinstance(data, dict):
            key = "all" if search_type in ("all", "everything") else search_type
            if key in data and isinstance(data[key], dict) and "items" in data[key]:
                items = data[key]["items"]
                total = data[key].get("total") or len(items)
            elif "items" in data:
                items = data["items"]
                total = data.get("total") or len(items)

            # If chosen category was empty, check if other categories have items
            if not items:
                for cat in ["all", "tracks", "albums", "artists", "playlists"]:
                    if cat in data and isinstance(data[cat], dict) and len(data[cat].get("items", [])) > 0:
                        items = data[cat]["items"]
                        total = data[cat].get("total") or len(items)
                        effective_type = cat
                        self.search_type_menu.set(cat.capitalize())
                        break

        self._raw_search_items = [it for it in items if isinstance(it, dict) and "id" in it]
        self._current_search_total = max(total, len(self._raw_search_items))
        self._current_search_type = effective_type
        for it in self._raw_search_items:
            if "_category" not in it and effective_type not in ("all", "everything"):
                it["_category"] = effective_type
        self.apply_filter_and_sort()

    def apply_filter_and_sort(self):
        self._render_batch_id = getattr(self, "_render_batch_id", 0) + 1
        current_batch_id = self._render_batch_id
        self.stop_preview()

        for child in self.results_scroll.winfo_children():
            child.destroy()

        if not self._raw_search_items:
            self.results_stats_lbl.configure(text="")
            lbl = CTk.CTkLabel(self.results_scroll, text="No results found in Q-Buz catalog.", font=CTk.CTkFont(size=14))
            lbl.pack(pady=40)
            return

        quality_filter = self.filter_quality_menu.get()
        sort_mode = self.sort_menu.get()

        # 1. Filter by audio quality
        filtered = []
        hires_count = 0
        master_count = 0
        for itm in self._raw_search_items:
            if not isinstance(itm, dict):
                continue
            bd = int(itm.get("maximum_bit_depth") or itm.get("bit_depth") or 16)
            try:
                sr = float(itm.get("maximum_sampling_rate") or itm.get("sampling_rate") or 44.1)
            except Exception:
                sr = 44.1

            is_hires = bd >= 24 or bool(itm.get("hires") or itm.get("hires_streamable"))
            is_master = bd >= 24 and sr >= 176.4

            if is_hires:
                hires_count += 1
            if is_master:
                master_count += 1

            if quality_filter == "✨ Hi-Res (24-bit+)":
                if not is_hires:
                    continue
            elif quality_filter == "🏆 192kHz Master":
                if not is_master:
                    continue
            elif quality_filter == "💿 CD Lossless (16-bit)":
                if bd > 16:
                    continue
            filtered.append(itm)

        # 2. Sort
        if sort_mode == "Sort: Highest Quality":
            def quality_key(x):
                bd = int(x.get("maximum_bit_depth") or x.get("bit_depth") or 16)
                try:
                    sr = float(x.get("maximum_sampling_rate") or x.get("sampling_rate") or 44.1)
                except Exception:
                    sr = 44.1
                return bd * 1000 + sr
            filtered.sort(key=quality_key, reverse=True)
        elif sort_mode == "Sort: Newest":
            def date_key(x):
                return str(x.get("released_at") or x.get("release_date_original") or x.get("year") or "")
            filtered.sort(key=date_key, reverse=True)
        elif sort_mode == "Sort: Title (A-Z)":
            def title_key(x):
                return str(x.get("title") or x.get("name") or "").lower()
            filtered.sort(key=title_key)

        # 3. Stats update
        total_raw = len(self._raw_search_items)
        shown_count = len(filtered)
        stats_txt = f"Showing {shown_count} of {total_raw} results • {hires_count} Hi-Res (24-bit) • {master_count} Master (192kHz)"
        if self._current_search_total > total_raw:
            stats_txt = f"{stats_txt} (Catalog: {self._current_search_total}+)"
        self.results_stats_lbl.configure(text=stats_txt)

        if not filtered:
            lbl = CTk.CTkLabel(self.results_scroll, text="No items match the selected quality filter.", font=CTk.CTkFont(size=14, slant="italic"))
            lbl.pack(pady=40)
            return

        # 4. Progressive Chunked Rendering (Smooth 60 FPS UI)
        # Render initial 6 items immediately (<10ms)
        initial_chunk = min(6, len(filtered))
        for i in range(initial_chunk):
            self._render_result_row(filtered[i], current_batch_id)

        # Stream remaining items in background 5-item chunks spaced with after(22)
        if initial_chunk < len(filtered):
            def render_chunks(start_idx, b_id):
                if b_id != getattr(self, "_render_batch_id", 0):
                    return
                end_idx = min(start_idx + 5, len(filtered))
                for idx in range(start_idx, end_idx):
                    self._render_result_row(filtered[idx], b_id)
                if end_idx < len(filtered):
                    self.after(22, lambda: render_chunks(end_idx, b_id))
                else:
                    self._append_load_more_btn_if_needed()

            self.after(22, lambda: render_chunks(initial_chunk, current_batch_id))
        else:
            self._append_load_more_btn_if_needed()

    def _append_load_more_btn_if_needed(self):
        if self._current_search_total > len(self._raw_search_items) and self._current_search_type not in ("playlists", "artists"):
            more_box = CTk.CTkFrame(self.results_scroll, fg_color="transparent")
            more_box.pack(fill="x", pady=15)
            more_btn = CTk.CTkButton(
                more_box,
                text=f"📥 Load More Results (Showing {len(self._raw_search_items)} of {self._current_search_total})",
                fg_color=COLOR_FRAME_BG,
                hover_color="#2b374a",
                text_color="white",
                height=36,
                font=CTk.CTkFont(size=12, weight="bold"),
                command=self.load_more_results
            )
            more_btn.pack(expand=True)

    def _render_result_row(self, item, batch_id=None):
        item_cat = item.get("_category")
        if not item_cat or item_cat in ("all", "everything"):
            # Accurate detection based on Q-Buz API object schemas
            if ("tracks_count" in item and ("artist" in item or "label" in item)) or "upc" in item or ("tracks" in item and "is_collaborative" not in item):
                item_cat = "albums"
            elif "tracks_count" in item and ("owner" in item or "is_collaborative" in item or "playlist" in str(item.get("id"))):
                item_cat = "playlists"
            elif "tracks_count" in item:
                item_cat = "albums"
            elif "albums_count" in item or ("name" in item and "title" not in item):
                item_cat = "artists"
            elif "track_number" in item or ("album" in item and isinstance(item.get("album"), dict)) or "isrc" in item:
                item_cat = "tracks"
            elif self._current_search_type not in ("all", "everything"):
                item_cat = self._current_search_type
            elif not str(item.get("id", "")).isdigit():
                # Alphanumeric IDs (like 'es45w03nwb5eb') are always albums on Q-Buz
                item_cat = "albums"
            else:
                item_cat = "tracks"

        # Modern card frame: eliminates separate divider frames to save RAM and widget overhead
        row = CTk.CTkFrame(self.results_scroll, fg_color="#141c28", corner_radius=6, height=88)
        row.pack(fill="x", pady=3, padx=5)
        row.pack_propagate(False)

        # Thumbnail with clean placeholder
        img_lbl = CTk.CTkLabel(row, text="⏳", width=70, height=70, corner_radius=4, fg_color="#101620")
        img_lbl.pack(side="left", padx=(8, 10))

        badge_text, badge_bg, badge_fg = get_qobuz_badge(item)

        album_info = item.get("album") if isinstance(item.get("album"), dict) else {}
        album_id_for_jump = None
        album_title_for_jump = None

        if item_cat == "tracks":
            title = item.get("title", "Unknown Track")
            performer = item.get("performer") if isinstance(item.get("performer"), dict) else {}
            artist = performer.get("name") if isinstance(performer, dict) else "Unknown Artist"
            album_title = album_info.get("title", "")
            album_id_for_jump = album_info.get("id")
            album_title_for_jump = album_title

            dur_sec = item.get("duration", 0)
            dur_str = f"{dur_sec // 60}:{dur_sec % 60:02d}" if dur_sec else ""
            year_val = str(item.get("released_at") or album_info.get("release_date_original") or "")[:4]

            extras = [e for e in [dur_str, year_val] if e]
            extra_suffix = f" • {' • '.join(extras)}" if extras else ""
            display_txt = f"{title}\nBy {artist} — {album_title}{extra_suffix}" if album_title else f"{title}\nBy {artist}{extra_suffix}"

        elif item_cat == "albums":
            title = item.get("title", "Unknown Album")
            artist_info = item.get("artist") if isinstance(item.get("artist"), dict) else {}
            artist = artist_info.get("name") if isinstance(artist_info, dict) else "Unknown Artist"
            tracks_count = item.get("tracks_count", "?")
            year_val = str(item.get("released_at") or item.get("release_date_original") or "")[:4]
            extra_year = f" • {year_val}" if year_val else ""
            display_txt = f"Album: {title}\nBy {artist} • {tracks_count} Tracks{extra_year}"

        elif item_cat == "playlists":
            title = item.get("title", "Unknown Playlist")
            tracks_count = item.get("tracks_count", "?")
            owner_info = item.get("owner", {}) if isinstance(item.get("owner"), dict) else {}
            owner_name = owner_info.get("name", "")
            owner_str = f" • By {owner_name}" if owner_name else ""
            display_txt = f"Playlist: {title}\nTracks: {tracks_count}{owner_str}"

        elif item_cat == "artists":
            title = item.get("name", "Unknown Artist")
            albums_cnt = item.get("albums_count")
            alb_str = f" • {albums_cnt} Albums" if albums_cnt else ""
            display_txt = f"Artist: {title}{alb_str}"
        else:
            title = item.get("title", "Item")
            display_txt = title

        # Robust cover art extraction across all categories
        cover_url = extract_cover_url(item, album_info if item_cat == "tracks" else None)
        if cover_url:
            self.run_async(self.load_image(cover_url, img_lbl, batch_id))
        else:
            img_lbl.configure(text="🎵", text_color=COLOR_TEXT_MUTED)

        # Action Buttons Box on Right
        btn_box = CTk.CTkFrame(row, fg_color="transparent")
        btn_box.pack(side="right", padx=(5, 12), pady=16)

        if item_cat == "albums":
            dl_btn = CTk.CTkButton(
                btn_box,
                text="Download",
                fg_color=COLOR_ACCENT,
                hover_color=COLOR_ACCENT_HOVER,
                text_color="black",
                width=100,
                font=CTk.CTkFont(size=11, weight="bold")
            )
            dl_btn.configure(command=lambda i=item["id"], t=title, b=dl_btn: self.queue_album_downloads(i, t, b))
            dl_btn.pack(side="right", padx=(5, 0))

        elif item_cat == "playlists":
            dl_btn = CTk.CTkButton(
                btn_box,
                text="Download",
                fg_color=COLOR_ACCENT,
                hover_color=COLOR_ACCENT_HOVER,
                text_color="black",
                width=100,
                font=CTk.CTkFont(size=11, weight="bold")
            )
            dl_btn.configure(command=lambda i=item["id"], t=title, b=dl_btn: self.queue_playlist_downloads(i, t, b))
            dl_btn.pack(side="right", padx=(5, 0))

        elif item_cat == "artists":
            art_btn = CTk.CTkButton(
                btn_box,
                text="View Discography",
                fg_color=COLOR_ACCENT,
                hover_color=COLOR_ACCENT_HOVER,
                text_color="black",
                width=130,
                font=CTk.CTkFont(size=11, weight="bold")
            )
            art_btn.configure(command=lambda i=item["id"], n=item.get("name", "Unknown Artist"): self.trigger_artist_search(i, n))
            art_btn.pack(side="right", padx=(5, 0))

        else:  # tracks
            dl_btn = CTk.CTkButton(
                btn_box,
                text="Download",
                fg_color=COLOR_ACCENT,
                hover_color=COLOR_ACCENT_HOVER,
                text_color="black",
                width=95,
                font=CTk.CTkFont(size=11, weight="bold")
            )
            dl_btn.configure(command=lambda i=item["id"], t=title, b=dl_btn, tm=dict(item): self.queue_track_download(i, t, btn=b, track_meta=tm))
            dl_btn.pack(side="right", padx=(5, 0))

            prev_btn = CTk.CTkButton(
                btn_box,
                text="▶ Preview",
                fg_color=COLOR_FRAME_BG,
                hover_color="#2b374a",
                text_color="white",
                width=75,
                font=CTk.CTkFont(size=11)
            )
            prev_btn.configure(command=lambda i=item["id"], b=prev_btn: self.toggle_preview(i, b))
            prev_btn.pack(side="right", padx=(4, 0))

            if album_id_for_jump:
                alb_jump_btn = CTk.CTkButton(
                    btn_box,
                    text="💽 Album",
                    fg_color=COLOR_FRAME_BG,
                    hover_color="#2b374a",
                    text_color="#c0d4e8",
                    width=75,
                    font=CTk.CTkFont(size=11)
                )
                alb_jump_btn.configure(command=lambda aid=album_id_for_jump, atitle=album_title_for_jump: self.trigger_album_view(aid, atitle))
                alb_jump_btn.pack(side="right", padx=(4, 0))

        # Text and Badges in Middle
        text_frame = CTk.CTkFrame(row, fg_color="transparent")
        text_frame.pack(side="left", fill="both", expand=True, pady=6)

        info_lbl = CTk.CTkLabel(text_frame, text=display_txt, font=CTk.CTkFont(size=12), anchor="w", justify="left")
        info_lbl.pack(anchor="w", pady=(0, 2))

        badges_box = CTk.CTkFrame(text_frame, fg_color="transparent")
        badges_box.pack(anchor="w")

        # Category indicator if in unified "All" mode
        if self._current_search_type in ("all", "everything"):
            cat_label = item_cat.upper().rstrip("S")
            cat_badge = CTk.CTkLabel(
                badges_box,
                text=cat_label,
                font=CTk.CTkFont(size=9, weight="bold"),
                text_color="#8da2b5",
                fg_color="#1f2c3d",
                corner_radius=3,
                padx=5,
                height=18
            )
            cat_badge.pack(side="left", padx=(0, 6))

        badge = CTk.CTkLabel(
            badges_box,
            text=badge_text,
            font=CTk.CTkFont(size=10, weight="bold"),
            text_color=badge_fg,
            fg_color=badge_bg,
            corner_radius=4,
            padx=6,
            height=20
        )
        badge.pack(side="left")

    def trigger_album_view(self, album_id, album_title=""):
        self.search_entry.delete(0, "end")
        self.search_entry.insert(0, f"https://www.qobuz.com/album/{album_id}")
        self.search_type_menu.set("Albums")
        self.show_search_status(f"Fetching album: {album_title or album_id}...")

        async def fetch():
            try:
                alb = await self.api.get_album(album_id)
                if alb and isinstance(alb, dict) and alb.get("id"):
                    self.after(0, self.finish_search, {"albums": {"items": [alb], "total": 1}}, "albums")
                else:
                    self.after(0, self.finish_search, None, "albums", "Album could not be loaded.")
            except Exception as e:
                self.after(0, self.finish_search, None, "albums", str(e))
        self.run_async(fetch())

    def load_more_results(self):
        if self._is_loading_more:
            return
        self._is_loading_more = True
        offset = len(self._raw_search_items)
        q = self._current_search_query
        st = self._current_search_type

        async def fetch():
            try:
                res = await self.api.search(q, search_type=st, limit=50, offset=offset)
                new_items = []
                if isinstance(res, dict):
                    key = "all" if st in ("all", "everything") else st
                    if key in res and isinstance(res[key], dict):
                        new_items = res[key].get("items", [])
                    elif "items" in res:
                        new_items = res["items"]

                def update_ui():
                    self._is_loading_more = False
                    if new_items:
                        seen_ids = {it.get("id") for it in self._raw_search_items if isinstance(it, dict) and "id" in it}
                        for it in new_items:
                            if isinstance(it, dict) and it.get("id") not in seen_ids:
                                seen_ids.add(it.get("id"))
                                self._raw_search_items.append(it)
                        self.apply_filter_and_sort()
                    else:
                        self._current_search_total = len(self._raw_search_items)
                        self.apply_filter_and_sort()
                self.after(0, update_ui)
            except Exception as e:
                def on_err():
                    self._is_loading_more = False
                    messagebox.showerror("Load More Error", str(e))
                self.after(0, on_err)

        self.run_async(fetch())

    def stop_preview(self):
        """Stops any currently playing audio preview and cleans temporary audio files."""
        if winsound:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass

        if hasattr(self, "preview_proc") and self.preview_proc:
            try:
                self.preview_proc.terminate()
            except Exception:
                pass
            self.preview_proc = None

        if hasattr(self, "_preview_wav") and self._preview_wav:
            wav_path = self._preview_wav
            self._preview_wav = None
            try:
                if os.path.exists(wav_path):
                    os.remove(wav_path)
            except Exception:
                pass

        if hasattr(self, "_active_preview_btn") and self._active_preview_btn:
            try:
                if self._active_preview_btn.winfo_exists():
                    self._active_preview_btn.configure(text="▶ Preview", fg_color=COLOR_FRAME_BG, text_color="white")
            except Exception:
                pass
            self._active_preview_btn = None

        self.preview_tid = None

    def toggle_preview(self, track_id, btn):
        """Toggles 30-second audio preview playback for a track using imageio-ffmpeg / winsound."""
        if self.preview_tid == track_id:
            self.stop_preview()
            return

        self.stop_preview()
        self.preview_tid = track_id
        self._active_preview_btn = btn
        if btn and btn.winfo_exists():
            btn.configure(text="⏳ Loading...", fg_color="#3a506b", text_color="white")

        async def play():
            try:
                url = await self.api.get_preview_url(track_id)
                if not url:
                    def on_fail():
                        if self.preview_tid == track_id:
                            self.stop_preview()
                        messagebox.showwarning("Preview Unavailable", "Sample preview is unavailable for this track.")
                    self.after(0, on_fail)
                    return

                import tempfile
                temp_mp3 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
                temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name

                # Stream audio chunks (30s sample is ~1MB max)
                session = await self.api.get_session()
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status not in (200, 206):
                        raise Exception(f"HTTP {resp.status}")
                    with open(temp_mp3, "wb") as f:
                        async for chunk in resp.content.iter_chunked(64 * 1024):
                            if self.preview_tid != track_id:
                                break
                            f.write(chunk)
                            if os.path.getsize(temp_mp3) > 1.2 * 1024 * 1024:
                                break

                if self.preview_tid != track_id:
                    for p in [temp_mp3, temp_wav]:
                        if os.path.exists(p):
                            try:
                                os.remove(p)
                            except Exception:
                                pass
                    return

                # Convert to standard WAV via imageio-ffmpeg
                ffmpeg_bin = None
                try:
                    import imageio_ffmpeg
                    ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
                except Exception:
                    pass

                converted = False
                if ffmpeg_bin and os.path.exists(ffmpeg_bin):
                    proc = await asyncio.create_subprocess_exec(
                        ffmpeg_bin, "-y", "-i", temp_mp3, "-t", "30", "-ar", "44100", "-ac", "2", temp_wav,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL
                    )
                    self.preview_proc = proc
                    await proc.wait()
                    self.preview_proc = None
                    if os.path.exists(temp_wav) and os.path.getsize(temp_wav) > 1000:
                        converted = True

                if os.path.exists(temp_mp3):
                    try:
                        os.remove(temp_mp3)
                    except Exception:
                        pass

                if converted and self.preview_tid == track_id:
                    self._preview_wav = temp_wav
                    def start_sound():
                        if btn and btn.winfo_exists():
                            btn.configure(text="⏹ Stop", fg_color="#ff9800", hover_color="#f57c00", text_color="black")
                        if winsound:
                            winsound.PlaySound(temp_wav, winsound.SND_ASYNC | winsound.SND_FILENAME)
                    self.after(0, start_sound)
                else:
                    if os.path.exists(temp_wav):
                        try:
                            os.remove(temp_wav)
                        except Exception:
                            pass
                    def fallback_fail():
                        if self.preview_tid == track_id:
                            self.stop_preview()
                    self.after(0, fallback_fail)

            except Exception as e:
                print(f"[Preview Error]: {e}")
                def on_err():
                    if self.preview_tid == track_id:
                        self.stop_preview()
                self.after(0, on_err)

        self.run_async(play())

    async def load_image(self, url, label, batch_id=None):
        """Loads and caches thumbnail images with memory-optimized downsampling and browser headers."""
        if not url:
            self.after(0, lambda: self._fallback_img(label))
            return

        if batch_id is not None and batch_id != getattr(self, "_render_batch_id", 0):
            return

        # Upgrading http to https prevents unnecessary 301/302 redirects
        if url.startswith("http://"):
            url = "https://" + url[7:]

        # Check existing cached image
        if url in self._image_cache:
            img = self._image_cache[url]
            self.after(0, lambda: self._safe_set_img(label, img, batch_id))
            return

        # Semaphore prevents network saturation and event loop queue choking
        semaphore = getattr(self, "_img_semaphore", None)
        if semaphore is None:
            semaphore = asyncio.Semaphore(6)
            self._img_semaphore = semaphore

        async with semaphore:
            if batch_id is not None and batch_id != getattr(self, "_render_batch_id", 0):
                return

            if not label or not label.winfo_exists():
                return

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                "Referer": "https://play.qobuz.com/",
            }

            try:
                session = await self.api.get_session()
                # Disable SSL verification for static CDN assets to handle unbundled Windows root certs
                timeout = aiohttp.ClientTimeout(total=5, sock_connect=3)
                async with session.get(url, headers=headers, ssl=False, timeout=timeout) as resp:
                    if resp.status == 200:
                        if batch_id is not None and batch_id != getattr(self, "_render_batch_id", 0):
                            return
                        if not label or not label.winfo_exists():
                            return

                        data = await resp.read()
                        if not data or len(data) > 10 * 1024 * 1024:
                            self.after(0, lambda: self._fallback_img(label))
                            return

                        def process_image(raw_bytes):
                            raw_img = Image.open(io.BytesIO(raw_bytes))
                            if raw_img.mode not in ("RGB", "RGBA"):
                                raw_img = raw_img.convert("RGB")
                            # Bilinear downsampling is 5x faster than Lanczos, saves substantial CPU
                            resample = getattr(Image, "Resampling", Image).BILINEAR
                            raw_img.thumbnail((140, 140), resample)
                            return raw_img

                        pil_img = await asyncio.to_thread(process_image, data)

                        if batch_id is not None and batch_id != getattr(self, "_render_batch_id", 0):
                            return

                        def apply_img(p_img=pil_img, u=url, b_id=batch_id):
                            if b_id is not None and b_id != getattr(self, "_render_batch_id", 0):
                                return
                            if not label.winfo_exists():
                                return
                            ctk_img = CTk.CTkImage(light_image=p_img, dark_image=p_img, size=(70, 70))
                            # Keep cache size capped at 150 items
                            if len(self._image_cache) >= 150:
                                for _ in range(30):
                                    self._image_cache.pop(next(iter(self._image_cache)), None)
                            self._image_cache[u] = ctk_img
                            label.configure(image=ctk_img, text="")

                        self.after(0, apply_img)
                    else:
                        self.after(0, lambda: self._fallback_img(label))
            except Exception:
                self.after(0, lambda: self._fallback_img(label))

    def _fallback_img(self, label):
        try:
            if label and label.winfo_exists() and label.cget("text") in ("Loading...", "⏳"):
                label.configure(text="🎵", text_color=COLOR_TEXT_MUTED)
        except Exception:
            pass

    def _safe_set_img(self, label, ctk_img, batch_id=None):
        try:
            if batch_id is not None and batch_id != getattr(self, "_render_batch_id", 0):
                return
            if label.winfo_exists():
                label.configure(image=ctk_img, text="")
        except Exception:
            pass

    def trigger_artist_search(self, artist_id, artist_name):
        self.search_entry.delete(0, "end")
        self.search_entry.insert(0, f"https://www.qobuz.com/artist/{artist_id}")
        self.search_type_menu.set("Albums")
        self.show_search_status(f"Fetching complete discography for {artist_name}...")

        async def fetch():
            try:
                art = await self.api.get_artist(artist_id)
                a_obj = art.get("albums") if isinstance(art, dict) else None
                if isinstance(a_obj, dict):
                    albums = a_obj.get("items", [])
                elif isinstance(a_obj, list):
                    albums = a_obj
                else:
                    albums = []
                self.after(0, self.finish_search, {"albums": {"items": albums}}, "albums")
            except Exception as e:
                self.after(0, self.finish_search, None, "albums", str(e))
        self.run_async(fetch())

    def trigger_album_view(self, album_id, album_title):
        """Fetches album details and opens the interactive track selection checklist modal."""
        if not album_id:
            return
        self.search_entry.delete(0, "end")
        self.search_entry.insert(0, f"https://play.qobuz.com/album/{album_id}")
        self.queue_album_downloads(album_id, album_title or f"Album {album_id}")


    # --- Queue View ---

    def create_queue_view(self):
        self.queue_view = CTk.CTkFrame(self.main_container, fg_color="transparent")
        self.queue_view.grid_rowconfigure(1, weight=1)
        self.queue_view.grid_columnconfigure(0, weight=1)

        # Header
        header = CTk.CTkFrame(self.queue_view, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        title_lbl = CTk.CTkLabel(header, text="Download Queue Monitor", font=CTk.CTkFont(size=16, weight="bold"))
        title_lbl.pack(side="left")

        self.queue_summary_lbl = CTk.CTkLabel(header, text="", font=CTk.CTkFont(size=12), text_color=COLOR_TEXT_MUTED)
        self.queue_summary_lbl.pack(side="left", padx=15)

        self.pause_btn = CTk.CTkButton(header, text="Pause", width=80, fg_color="#ff9800", hover_color="#f57c00", text_color="black", command=self.toggle_pause)
        self.pause_btn.pack(side="right", padx=4)

        cancel_btn = CTk.CTkButton(header, text="Cancel All", width=80, fg_color="#f44336", hover_color="#d32f2f", text_color="white", command=self.cancel_all_downloads)
        cancel_btn.pack(side="right", padx=4)

        retry_all_btn = CTk.CTkButton(header, text="🔁 Retry Failed", width=100, fg_color=COLOR_FRAME_BG, hover_color="#2b374a", text_color="white", command=self.retry_all_failed_downloads)
        retry_all_btn.pack(side="right", padx=4)

        batch_q_btn = CTk.CTkButton(header, text="📋 Batch Import", width=110, fg_color=COLOR_FRAME_BG, hover_color="#2b374a", text_color="white", command=self.open_batch_import_modal)
        batch_q_btn.pack(side="right", padx=4)

        open_dir_btn = CTk.CTkButton(header, text="📁 Open Folder", width=105, fg_color=COLOR_FRAME_BG, hover_color="#2b374a", text_color="white", command=lambda: open_in_file_manager(self.config.download_directory))
        open_dir_btn.pack(side="right", padx=4)

        clear_btn = CTk.CTkButton(header, text="Clear Finished", width=100, fg_color=COLOR_FRAME_BG, hover_color="#2b374a", text_color="white", command=self.clear_finished_downloads)
        clear_btn.pack(side="right", padx=4)

        self.queue_scroll = CTk.CTkScrollableFrame(self.queue_view, fg_color=COLOR_FRAME_BG)
        self.queue_scroll.grid(row=1, column=0, sticky="nsew")

    def retry_all_failed_downloads(self):
        retried = 0
        for tid, item in list(self.queue_items.items()):
            if item.get("status") in ["failed", "cancelled"]:
                retry_fn = item.get("retry_func")
                if retry_fn:
                    retry_fn()
                    retried += 1
        if retried > 0:
            self.update_queue_summary()

    def toggle_pause(self):
        if self.downloader.is_paused:
            self.downloader.is_paused = False
            self.pause_btn.configure(text="Pause")
        else:
            self.downloader.is_paused = True
            self.pause_btn.configure(text="Resume")

    def cancel_all_downloads(self):
        if messagebox.askyesno("Cancel Downloads", "Are you sure you want to cancel all downloads?"):
            self.downloader.is_cancelled = True
            self.pending_downloads.clear()
            for tid, item in self.queue_items.items():
                if item["status"] in ["queued", "downloading"]:
                    item["status"] = "cancelled"
                    if item.get("task_state"):
                        item["task_state"]["is_cancelled"] = True
                    def sc(i=item):
                        if i["status_lbl"].winfo_exists():
                            i["status_lbl"].configure(text="Cancelled", text_color="#f44336")
                        if "retry_btn" in i and i["retry_btn"].winfo_exists():
                            i["retry_btn"].pack(side="left", padx=2)
                    self.after(0, sc)
            self.update_queue_summary()
            self.after(1500, lambda: setattr(self.downloader, "is_cancelled", False))

    def clear_finished_downloads(self):
        cleared_any = False
        for tid in list(self.queue_items.keys()):
            item = self.queue_items[tid]
            if item["status"] in ["completed", "failed", "cancelled"]:
                item["row"].destroy()
                del self.queue_items[tid]
                if tid in self.queue_order:
                    self.queue_order.remove(tid)
                cleared_any = True
        self.update_queue_summary()
        if cleared_any:
            gc.collect()

    def update_queue_summary(self):
        total = len(self.queue_items)
        if total == 0:
            self.queue_summary_lbl.configure(text="")
            return
        completed = sum(1 for i in self.queue_items.values() if i["status"] == "completed")
        failed = sum(1 for i in self.queue_items.values() if i["status"] == "failed")
        cancelled = sum(1 for i in self.queue_items.values() if i["status"] == "cancelled")
        pending = sum(1 for i in self.queue_items.values() if i["status"] in ["queued", "downloading"])
        status_parts = [f"Total: {total}", f"Completed: {completed}"]
        if failed > 0:
            status_parts.append(f"Failed: {failed}")
        if cancelled > 0:
            status_parts.append(f"Cancelled: {cancelled}")
        status_parts.append(f"Pending: {pending}")
        self.queue_summary_lbl.configure(text=" | ".join(status_parts))

        # Completion Chime
        if getattr(self, "_queue_active", False) and pending == 0 and completed > 0:
            self._queue_active = False
            if self.config.play_sound_on_complete and winsound:
                threading.Thread(target=lambda: winsound.MessageBeep(winsound.MB_ICONASTERISK), daemon=True).start()
        elif pending > 0:
            self._queue_active = True

    def queue_track_download(self, track_id, title, parent_folder=None, btn=None, track_meta=None):
        clean_track_id = str(track_id).strip()

        # Intercept if track_id is actually an album ID or track_meta is an album object
        is_album = False
        if not clean_track_id.isdigit():
            is_album = True
        elif track_meta and isinstance(track_meta, dict):
            if "tracks_count" in track_meta and "track_number" not in track_meta:
                is_album = True

        if is_album:
            print(f"[Q-Buz UI] Intercepted album ID '{clean_track_id}' in queue_track_download, redirecting to queue_album_downloads...")
            self.queue_album_downloads(clean_track_id, title, btn=btn)
            return

        existing_key = None
        if clean_track_id in self.queue_items:
            existing_key = clean_track_id
        elif isinstance(track_id, int) and track_id in self.queue_items:
            existing_key = track_id

        if existing_key is not None:
            item = self.queue_items[existing_key]
            st = item.get("status")
            if st in ["failed", "cancelled"]:
                retry_fn = item.get("retry_func")
                if retry_fn:
                    retry_fn()
                if btn and btn.winfo_exists():
                    btn.configure(text="Queued ✓", state="disabled", fg_color="#2b374a")
                return
            elif st == "completed":
                if btn and btn.winfo_exists():
                    btn.configure(text="Downloaded ✓", state="disabled", fg_color="#2b374a")
                return
            else:
                # Already queued or downloading
                if btn and btn.winfo_exists():
                    btn.configure(text="Queued ✓", state="disabled", fg_color="#2b374a")
                return

        track_id = clean_track_id

        if btn and btn.winfo_exists():
            btn.configure(text="Queued ✓", state="disabled", fg_color="#2b374a")

        row = CTk.CTkFrame(self.queue_scroll, fg_color="#141c28", height=70)
        row.pack(fill="x", pady=4, padx=5)
        row.pack_propagate(False)

        lbl = CTk.CTkLabel(row, text=title, font=CTk.CTkFont(size=12, weight="bold"), anchor="w")
        lbl.pack(side="top", fill="x", padx=15, pady=(6, 0))

        prog_frame = CTk.CTkFrame(row, fg_color="transparent")
        prog_frame.pack(side="bottom", fill="x", padx=15, pady=(0, 10))

        # Control Frame packed to right FIRST
        ctrl_frame = CTk.CTkFrame(prog_frame, fg_color="transparent")
        ctrl_frame.pack(side="right")

        lbl_frame = CTk.CTkFrame(ctrl_frame, width=280, height=20, fg_color="transparent")
        lbl_frame.pack(side="left", padx=(0, 10))
        lbl_frame.pack_propagate(False)

        status_lbl = CTk.CTkLabel(lbl_frame, text="Queued", font=CTk.CTkFont(family="Consolas", size=11), text_color=COLOR_TEXT_MUTED, anchor="w")
        status_lbl.pack(side="left", fill="both", expand=True)

        pause_btn = CTk.CTkButton(ctrl_frame, text="⏸", width=25, height=20, fg_color="#ff9800", hover_color="#f57c00", text_color="black")
        pause_btn.pack(side="left", padx=2)

        cancel_btn = CTk.CTkButton(ctrl_frame, text="✖", width=25, height=20, fg_color="#f44336", hover_color="#d32f2f", text_color="white")
        cancel_btn.pack(side="left", padx=2)

        top_btn = CTk.CTkButton(ctrl_frame, text="⬆", width=25, height=20, fg_color="#4caf50", hover_color="#388e3c", text_color="white")
        top_btn.pack(side="left", padx=2)

        retry_btn = CTk.CTkButton(ctrl_frame, text="🔁", width=25, height=20, fg_color="#2196f3", hover_color="#1976d2", text_color="white")

        # Progress bar packed with expand=True
        prog_bar = CTk.CTkProgressBar(prog_frame, fg_color="#2b374a", progress_color=COLOR_ACCENT)
        prog_bar.pack(side="left", fill="x", expand=True, padx=(0, 15))
        prog_bar.set(0.0)

        task_state = {"is_paused": False, "is_cancelled": False}

        def toggle_item():
            if task_state["is_paused"]:
                task_state["is_paused"] = False
                pause_btn.configure(text="⏸")
                status_lbl.configure(text="Resuming...", text_color=COLOR_ACCENT)
            else:
                task_state["is_paused"] = True
                pause_btn.configure(text="▶")
                status_lbl.configure(text="Paused ⏸", text_color="#ff9800")

        def cancel_item():
            task_state["is_cancelled"] = True
            if self.queue_items.get(track_id, {}).get("status") == "queued":
                self.queue_items[track_id]["status"] = "cancelled"
                status_lbl.configure(text="Cancelled", text_color="#f44336")
                if retry_btn.winfo_exists():
                    retry_btn.pack(side="left", padx=2)
                self.update_queue_summary()

        def move_top():
            if track_id in self.pending_downloads:
                self.pending_downloads.remove(track_id)
                self.pending_downloads.insert(0, track_id)
                row.pack_forget()
                kids = [c for c in self.queue_scroll.winfo_children() if c != row]
                if kids:
                    row.pack(before=kids[0], fill="x", pady=4, padx=5)
                else:
                    row.pack(fill="x", pady=4, padx=5)
                status_lbl.configure(text="Moved to Top Priority")

        def retry_item():
            if self.queue_items.get(track_id, {}).get("status") in ["failed", "cancelled"]:
                self.queue_items[track_id]["status"] = "queued"
                status_lbl.configure(text="Queued", text_color=COLOR_TEXT_MUTED)
                prog_bar.set(0.0)
                prog_bar.configure(progress_color=COLOR_ACCENT)
                task_state["is_paused"] = False
                task_state["is_cancelled"] = False
                if pause_btn.winfo_exists():
                    pause_btn.configure(text="⏸", state="normal")
                if cancel_btn.winfo_exists():
                    cancel_btn.configure(state="normal")
                if retry_btn.winfo_exists():
                    retry_btn.pack_forget()
                if track_id not in self.pending_downloads:
                    self.pending_downloads.append(track_id)
                self.update_queue_summary()

        pause_btn.configure(command=toggle_item)
        cancel_btn.configure(command=cancel_item)
        top_btn.configure(command=move_top)
        retry_btn.configure(command=retry_item)

        self.queue_items[track_id] = {
            "title": title,
            "row": row,
            "progress_bar": prog_bar,
            "status_lbl": status_lbl,
            "status": "queued",
            "parent_folder": parent_folder,
            "track_meta": track_meta,
            "task_state": task_state,
            "ctrl_frame": ctrl_frame,
            "pause_btn": pause_btn,
            "cancel_btn": cancel_btn,
            "top_btn": top_btn,
            "retry_btn": retry_btn,
            "retry_func": retry_item
        }
        self.queue_order.append(track_id)
        self.pending_downloads.append(track_id)
        self.update_queue_summary()

    def queue_album_downloads(self, album_id, album_title, btn=None):
        if btn and btn.winfo_exists():
            btn.configure(text="Loading...", state="disabled")

        async def fetch():
            try:
                alb = await self.api.get_album(album_id)
                tracks = []
                if isinstance(alb, dict):
                    t_obj = alb.get("tracks")
                    if isinstance(t_obj, dict):
                        tracks = t_obj.get("items", [])
                    elif isinstance(t_obj, list):
                        tracks = t_obj
                    elif "items" in alb:
                        tracks = alb.get("items", [])

                if not tracks:
                    self.after(0, lambda: messagebox.showwarning("Empty Album", "No tracks found in this album."))
                    return

                def start_dl(selected):
                    art_obj = alb.get("artist") if isinstance(alb, dict) else {}
                    art_name = (art_obj.get("name") if isinstance(art_obj, dict) else None) or "Unknown Artist"
                    safe_artist = sanitize_filename(art_name)
                    safe_album = sanitize_filename(album_title)
                    folder_name = f"{safe_artist} - {safe_album}"
                    if len(folder_name) > 100:
                        folder_name = folder_name[:100].rstrip(". ")
                    parent_dir = os.path.join(self.config.download_directory, folder_name)
                    for t in selected:
                        if not isinstance(t, dict) or not t.get("id"):
                            continue
                        t_meta = dict(t)
                        if "album" not in t_meta or not t_meta.get("album"):
                            t_meta["album"] = alb
                        t_title = t.get("title") or f"Track {t.get('id')}"
                        self.queue_track_download(
                            t["id"],
                            f"{album_title} - {t_title}",
                            parent_folder=parent_dir,
                            track_meta=t_meta
                        )
                    self.switch_view("queue")

                self.after(0, lambda: TrackSelectionModal(self, album_title, tracks, start_dl))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Album Error", str(e)))
            finally:
                if btn and btn.winfo_exists():
                    self.after(0, lambda: btn.configure(text="Download", state="normal"))
        self.run_async(fetch())

    def queue_playlist_downloads(self, playlist_id, playlist_title, btn=None):
        if btn and btn.winfo_exists():
            btn.configure(text="Loading...", state="disabled")

        async def fetch():
            try:
                pl = await self.api.get_playlist(playlist_id)
                tracks = []
                if isinstance(pl, dict):
                    t_obj = pl.get("tracks")
                    if isinstance(t_obj, dict):
                        tracks = t_obj.get("items", [])
                    elif isinstance(t_obj, list):
                        tracks = t_obj
                    elif "items" in pl:
                        tracks = pl.get("items", [])

                if not tracks:
                    self.after(0, lambda: messagebox.showwarning("Empty Playlist", "No tracks found in this playlist."))
                    return

                def start_dl(selected):
                    safe_pl = sanitize_filename(playlist_title)
                    if len(safe_pl) > 100:
                        safe_pl = safe_pl[:100].rstrip(". ")
                    parent_dir = os.path.join(self.config.download_directory, safe_pl)
                    for t in selected:
                        if not isinstance(t, dict) or not t.get("id"):
                            continue
                        t_meta = dict(t)
                        t_title = t.get('title') or f"Track {t.get('id')}"
                        t_perf = t.get('performer') if isinstance(t.get('performer'), dict) else {}
                        t_art = t_perf.get('name', '')
                        if not t_art and isinstance(t.get('artist'), dict):
                            t_art = t.get('artist', {}).get('name', '')
                        disp_name = f"{t_title} - {t_art}" if t_art else f"{playlist_title} - {t_title}"
                        self.queue_track_download(t["id"], disp_name, parent_folder=parent_dir, track_meta=t_meta)
                    self.switch_view("queue")

                self.after(0, lambda: TrackSelectionModal(self, playlist_title, tracks, start_dl))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Playlist Error", str(e)))
            finally:
                if btn and btn.winfo_exists():
                    self.after(0, lambda: btn.configure(text="Download", state="normal"))
        self.run_async(fetch())

    def open_batch_import_modal(self):
        BatchImportModal(self, self.start_batch_import)

    def start_batch_import(self, urls):
        """Processes a list of URLs or IDs and queues them for download."""
        self.switch_view("queue")

        async def worker():
            total = len(urls)
            queued_count = 0
            for idx, raw_url in enumerate(urls):
                url = raw_url.strip()
                if not url:
                    continue

                try:
                    # 1. External streaming links
                    if is_external_music_link(url):
                        resolved_q, res_type, _, _ = await resolve_external_link(url)
                        if resolved_q:
                            t_type = res_type or "tracks"
                            res = await self.api.smart_search(resolved_q, search_type=t_type, limit=1)
                            items = res.get(t_type, {}).get("items", []) if isinstance(res, dict) else []
                            if items:
                                itm = items[0]
                                if t_type == "albums":
                                    self.after(0, lambda i=itm["id"], t=itm.get("title", "Album"): self._queue_entire_album(i, t))
                                else:
                                    performer = itm.get('performer') if isinstance(itm.get('performer'), dict) else {}
                                    artist_name = performer.get('name', '')
                                    t_title = f"{itm.get('title')} - {artist_name}" if artist_name else itm.get('title', 'Track')
                                    self.after(0, lambda i=itm["id"], t=t_title, tm=itm: self.queue_track_download(i, t, track_meta=tm))
                                queued_count += 1
                        continue

                    # 2. Direct Q-Buz URLs or IDs
                    q_type, q_id = parse_qobuz_url(url)
                    if q_type == "track":
                        trk = await self.api.get_track(q_id)
                        if trk and trk.get("id"):
                            performer = trk.get('performer') if isinstance(trk.get('performer'), dict) else {}
                            artist_name = performer.get('name', '')
                            t_title = f"{trk.get('title')} - {artist_name}" if artist_name else trk.get('title', 'Track')
                            self.after(0, lambda i=trk["id"], t=t_title, tm=trk: self.queue_track_download(i, t, track_meta=tm))
                            queued_count += 1
                    elif q_type == "album":
                        alb = await self.api.get_album(q_id)
                        if alb and alb.get("id"):
                            self.after(0, lambda i=alb["id"], t=alb.get("title", "Album"): self._queue_entire_album(i, t))
                            queued_count += 1
                    elif q_type == "playlist":
                        pl = await self.api.get_playlist(q_id)
                        if pl and pl.get("id"):
                            self.after(0, lambda i=pl["id"], t=pl.get("title", "Playlist"): self._queue_entire_playlist(i, t))
                            queued_count += 1
                    elif q_type == "raw_id":
                        try:
                            trk = await self.api.get_track(q_id)
                            if trk and trk.get("id"):
                                performer = trk.get('performer') if isinstance(trk.get('performer'), dict) else {}
                                artist_name = performer.get('name', '')
                                t_title = f"{trk.get('title')} - {artist_name}" if artist_name else trk.get('title', 'Track')
                                self.after(0, lambda i=trk["id"], t=t_title, tm=trk: self.queue_track_download(i, t, track_meta=tm))
                                queued_count += 1
                                continue
                        except Exception:
                            pass
                        try:
                            alb = await self.api.get_album(q_id)
                            if alb and alb.get("id"):
                                self.after(0, lambda i=alb["id"], t=alb.get("title", "Album"): self._queue_entire_album(i, t))
                                queued_count += 1
                        except Exception:
                            pass
                    else:
                        res = await self.api.smart_search(url, search_type="tracks", limit=1)
                        trks = res.get("tracks", {}).get("items", []) if isinstance(res, dict) else []
                        if trks:
                            t = trks[0]
                            performer = t.get('performer') if isinstance(t.get('performer'), dict) else {}
                            artist_name = performer.get('name', '')
                            t_title = f"{t.get('title')} - {artist_name}" if artist_name else t.get('title', 'Track')
                            self.after(0, lambda i=t["id"], tt=t_title: self.queue_track_download(i, tt))
                            queued_count += 1

                except Exception as e:
                    print(f"[Batch Import] Error on '{url}': {e}")

            def done():
                messagebox.showinfo("Batch Import Complete", f"Successfully imported and queued {queued_count} of {total} items!")
            self.after(0, done)

        self.run_async(worker())

    def _queue_entire_album(self, album_id, album_title):
        async def f():
            try:
                alb = await self.api.get_album(album_id)
                tracks = []
                if isinstance(alb, dict):
                    t_obj = alb.get("tracks")
                    if isinstance(t_obj, dict):
                        tracks = t_obj.get("items", [])
                    elif isinstance(t_obj, list):
                        tracks = t_obj
                    elif "items" in alb:
                        tracks = alb.get("items", [])

                art_obj = alb.get("artist") if isinstance(alb, dict) else {}
                art_name = (art_obj.get("name") if isinstance(art_obj, dict) else None) or "Unknown Artist"
                safe_artist = sanitize_filename(art_name)
                safe_album = sanitize_filename(album_title)
                folder_name = f"{safe_artist} - {safe_album}"
                if len(folder_name) > 100:
                    folder_name = folder_name[:100].rstrip(". ")
                parent_dir = os.path.join(self.config.download_directory, folder_name)
                for t in tracks:
                    if isinstance(t, dict) and t.get("id"):
                        t_meta = dict(t)
                        if "album" not in t_meta or not t_meta.get("album"):
                            t_meta["album"] = alb
                        t_title = t.get('title') or f"Track {t.get('id')}"
                        self.after(0, lambda tid=t["id"], tt=f"{album_title} - {t_title}", pd=parent_dir, tm=t_meta: self.queue_track_download(tid, tt, parent_folder=pd, track_meta=tm))
            except Exception as e:
                print(f"Failed to queue entire album: {e}")
        self.run_async(f())

    def _queue_entire_playlist(self, playlist_id, playlist_title):
        async def f():
            try:
                pl = await self.api.get_playlist(playlist_id)
                tracks = []
                if isinstance(pl, dict):
                    t_obj = pl.get("tracks")
                    if isinstance(t_obj, dict):
                        tracks = t_obj.get("items", [])
                    elif isinstance(t_obj, list):
                        tracks = t_obj
                    elif "items" in pl:
                        tracks = pl.get("items", [])

                safe_pl = sanitize_filename(playlist_title)
                if len(safe_pl) > 100:
                    safe_pl = safe_pl[:100].rstrip(". ")
                parent_dir = os.path.join(self.config.download_directory, safe_pl)
                for t in tracks:
                    if not isinstance(t, dict) or not t.get("id"):
                        continue
                    t_meta = dict(t)
                    t_title = t.get('title') or f"Track {t.get('id')}"
                    t_perf = t.get('performer') if isinstance(t.get('performer'), dict) else {}
                    t_art = t_perf.get('name', '')
                    if not t_art and isinstance(t.get('artist'), dict):
                        t_art = t.get('artist', {}).get('name', '')
                    disp_name = f"{t_title} - {t_art}" if t_art else f"{playlist_title} - {t_title}"
                    self.after(0, lambda tid=t["id"], tt=disp_name, pd=parent_dir, tm=t_meta: self.queue_track_download(tid, tt, parent_folder=pd, track_meta=tm))
            except Exception as e:
                print(f"Failed to queue entire playlist: {e}")
        self.run_async(f())

    async def download_worker(self):
        """Worker loop managing concurrent download tasks."""
        active_tasks = set()
        try:
            while self._worker_running:
                # Clean up finished tasks
                active_tasks = {t for t in active_tasks if not t.done()}

                # If room for more downloads and items are pending
                while len(active_tasks) < self.config.concurrent_downloads and self.pending_downloads:
                    track_id = self.pending_downloads.pop(0)
                    if track_id not in self.queue_items:
                        continue
                    item = self.queue_items[track_id]
                    if item["status"] == "cancelled":
                        continue

                    task = asyncio.create_task(self._execute_download_task(track_id, item))
                    active_tasks.add(task)

                await asyncio.sleep(0.3)
        except asyncio.CancelledError:
            pass
        finally:
            for t in active_tasks:
                if not t.done():
                    t.cancel()

    async def _execute_download_task(self, track_id, item):
        item["status"] = "downloading"

        def update_ui(pct, txt):
            def cb():
                try:
                    if item["progress_bar"].winfo_exists():
                        item["progress_bar"].set(pct)
                    if item["status_lbl"].winfo_exists():
                        item["status_lbl"].configure(text=txt, text_color=COLOR_ACCENT if pct < 1.0 else "#4caf50")
                except Exception:
                    pass
            self.after(0, cb)

        try:
            res = await self.downloader.download_track(
                track_id,
                progress_callback=update_ui,
                task_state=item["task_state"],
                parent_folder=item["parent_folder"],
                track_meta=item.get("track_meta")
            )
            success = res[0]
            msg = res[1]
            target_path = res[2] if len(res) > 2 else None
            if target_path:
                item["target_path"] = target_path

            if success:
                item["status"] = "completed"
                final_path = target_path or item.get("parent_folder") or self.config.download_directory
                def on_complete(fp=final_path):
                    try:
                        if item["status_lbl"].winfo_exists():
                            item["status_lbl"].configure(text=msg, text_color="#4caf50")
                        for btn_k in ["pause_btn", "cancel_btn", "top_btn", "retry_btn"]:
                            if btn_k in item and item[btn_k].winfo_exists():
                                item[btn_k].destroy()
                        if item["ctrl_frame"].winfo_exists():
                            reveal_btn = CTk.CTkButton(
                                item["ctrl_frame"],
                                text="📁",
                                width=30,
                                height=20,
                                fg_color="#3a506b",
                                hover_color=COLOR_ACCENT,
                                command=lambda: open_in_file_manager(fp)
                            )
                            reveal_btn.pack(side="left", padx=2)
                    except Exception:
                        pass
                self.after(0, on_complete)
            else:
                item["status"] = "cancelled" if msg == "Cancelled" else "failed"
                def on_fail():
                    try:
                        if item["status_lbl"].winfo_exists():
                            item["status_lbl"].configure(text=msg, text_color="#f44336")
                        if item.get("status") in ["failed", "cancelled"] and "retry_btn" in item and item["retry_btn"].winfo_exists():
                            item["retry_btn"].pack(side="left", padx=2)
                    except Exception:
                        pass
                self.after(0, on_fail)
        except Exception as e:
            item["status"] = "failed"
            err_text = str(e)
            print(f"[Download Error] Track {track_id} failed: {err_text}")
            if "API error" not in err_text and "404" not in err_text:
                import traceback
                traceback.print_exc()
            def on_err():
                try:
                    if item["status_lbl"].winfo_exists():
                        disp_err = err_text
                        if "404" in err_text or "No result matching" in err_text:
                            disp_err = "Delisted / Unavailable (404)"
                        elif "401" in err_text or "403" in err_text:
                            disp_err = "Auth / Geo-restricted (403)"
                        item["status_lbl"].configure(text=f"Failed: {disp_err[:35]}", text_color="#f44336")
                    if "retry_btn" in item and item["retry_btn"].winfo_exists():
                        item["retry_btn"].pack(side="left", padx=2)
                except Exception:
                    pass
            self.after(0, on_err)

        self.after(0, self.update_queue_summary)

    # --- Settings View ---

    def create_settings_view(self):
        self.settings_view = CTk.CTkScrollableFrame(self.main_container, fg_color=COLOR_FRAME_BG)
        self.settings_view.grid_columnconfigure(0, weight=1)

        # Title
        hdr = CTk.CTkLabel(self.settings_view, text="⚙️ Preferences & Q-Buz Credentials", font=CTk.CTkFont(size=18, weight="bold"))
        hdr.pack(anchor="w", padx=20, pady=(15, 20))

        # 1. Download Quality Tier
        q_frame = CTk.CTkFrame(self.settings_view, fg_color="#141c28")
        q_frame.pack(fill="x", padx=20, pady=8)
        
        CTk.CTkLabel(q_frame, text="Preferred Studio Audio Quality:", font=CTk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=15, pady=(10, 4))
        
        quality_options = [
            "24-bit / up to 192kHz (Studio Master)",
            "24-bit / up to 96kHz (Hi-Res)",
            "16-bit / 44.1kHz (CD Lossless)",
            "MP3 320 kbps"
        ]
        self.quality_menu = CTk.CTkOptionMenu(
            q_frame,
            values=quality_options,
            command=self.on_change_quality
        )
        self.quality_menu.pack(anchor="w", padx=15, pady=(0, 10))
        cur_label = FORMAT_LABELS.get(self.config.format_id, quality_options[0])
        self.quality_menu.set(cur_label)

        # 2. Download Folder
        dir_frame = CTk.CTkFrame(self.settings_view, fg_color="#141c28")
        dir_frame.pack(fill="x", padx=20, pady=8)

        CTk.CTkLabel(dir_frame, text="Download Directory:", font=CTk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=15, pady=(10, 4))
        
        dir_box = CTk.CTkFrame(dir_frame, fg_color="transparent")
        dir_box.pack(fill="x", padx=15, pady=(0, 10))
        dir_box.grid_columnconfigure(0, weight=1)

        self.dir_entry = CTk.CTkEntry(dir_box)
        self.dir_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.dir_entry.insert(0, self.config.download_directory)

        browse_btn = CTk.CTkButton(dir_box, text="Browse", width=80, fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, text_color="black", command=self.browse_dir)
        browse_btn.grid(row=0, column=1)

        # 3. Naming Template
        tpl_frame = CTk.CTkFrame(self.settings_view, fg_color="#141c28")
        tpl_frame.pack(fill="x", padx=20, pady=8)

        CTk.CTkLabel(tpl_frame, text="File Path Template:", font=CTk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=15, pady=(10, 2))
        CTk.CTkLabel(tpl_frame, text="Tags: {artist}, {album}, {title}, {track_num}, {disc_num}, {year}, {bit_depth}, {sample_rate}, {quality}, {label}, {composer}, {ext}", font=CTk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED).pack(anchor="w", padx=15, pady=(0, 6))

        self.tpl_entry = CTk.CTkEntry(tpl_frame)
        self.tpl_entry.pack(fill="x", padx=15, pady=(0, 10))
        self.tpl_entry.insert(0, self.config.naming_template)

        # 4. Concurrency Slider
        con_frame = CTk.CTkFrame(self.settings_view, fg_color="#141c28")
        con_frame.pack(fill="x", padx=20, pady=8)

        con_header = CTk.CTkFrame(con_frame, fg_color="transparent")
        con_header.pack(fill="x", padx=15, pady=(10, 5))
        
        CTk.CTkLabel(con_header, text="Concurrent Downloads (1-5):", font=CTk.CTkFont(size=13, weight="bold")).pack(side="left")
        self.con_val_lbl = CTk.CTkLabel(con_header, text=str(self.config.concurrent_downloads), font=CTk.CTkFont(size=13, weight="bold"), text_color=COLOR_ACCENT)
        self.con_val_lbl.pack(side="left", padx=10)

        self.con_slider = CTk.CTkSlider(
            con_frame,
            from_=1,
            to=5,
            number_of_steps=4,
            command=self.on_change_concurrency
        )
        self.con_slider.pack(fill="x", padx=15, pady=(0, 10))
        self.con_slider.set(self.config.concurrent_downloads)

        # 5. Q-Buz Authentication - Primary: Web Session Token
        token_frame = CTk.CTkFrame(self.settings_view, fg_color="#141c28")
        token_frame.pack(fill="x", padx=20, pady=8)

        CTk.CTkLabel(token_frame, text="🔑 Q-Buz Login (Metode Utama: Web Session Token)", font=CTk.CTkFont(size=14, weight="bold"), text_color=COLOR_ACCENT).pack(anchor="w", padx=15, pady=(12, 4))
        
        guide_text = (
            "Karena Q-Buz membatasi login password langsung pada aplikasi pihak ketiga, gunakan token dari browser:\n"
            "1. Buka play.qobuz.com di browser (Chrome/Edge/Firefox) & pastikan sudah login akun Q-Buz.\n"
            "2. Tekan tombol F12 (Developer Tools) -> pilih tab 'Application' (atau 'Storage' di Firefox).\n"
            "3. Di panel kiri, klik 'Local Storage' -> https://play.qobuz.com\n"
            "4. Klik 'localuser' -> salin (copy) nilai teks 'userAuthToken' atau 'token'.\n"
            "5. Tempelkan (paste) di kolom bawah ini lalu klik 'Sign In with Token'."
        )
        guide_lbl = CTk.CTkLabel(token_frame, text=guide_text, font=CTk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED, justify="left", anchor="w")
        guide_lbl.pack(fill="x", padx=15, pady=(0, 10))

        token_input_box = CTk.CTkFrame(token_frame, fg_color="transparent")
        token_input_box.pack(fill="x", padx=15, pady=4)
        token_input_box.grid_columnconfigure(0, weight=1)

        self.token_entry = CTk.CTkEntry(token_input_box, placeholder_text="Tempelkan user_auth_token di sini...")
        self.token_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        if self.config.user_auth_token:
            self.token_entry.insert(0, self.config.user_auth_token)

        paste_btn = CTk.CTkButton(token_input_box, text="📋 Paste", width=70, fg_color=COLOR_FRAME_BG, hover_color="#2b374a", command=self.paste_token)
        paste_btn.grid(row=0, column=1)

        token_btn_row = CTk.CTkFrame(token_frame, fg_color="transparent")
        token_btn_row.pack(fill="x", padx=15, pady=10)

        self.save_token_btn = CTk.CTkButton(token_btn_row, text="Sign In with Token", fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, text_color="black", font=CTk.CTkFont(weight="bold"), command=self.do_save_token)
        self.save_token_btn.pack(side="left")

        self.logout_token_btn = CTk.CTkButton(token_btn_row, text="Logout", fg_color="#f44336", hover_color="#d32f2f", command=self.do_logout)
        self.logout_token_btn.pack(side="left", padx=10)

        # 5B. Q-Buz App ID (X-App-Id) Configuration & Auto-Scraper
        appid_frame = CTk.CTkFrame(self.settings_view, fg_color="#141c28")
        appid_frame.pack(fill="x", padx=20, pady=8)

        CTk.CTkLabel(appid_frame, text="🛡️ Q-Buz Client App ID (X-App-Id)", font=CTk.CTkFont(size=14, weight="bold"), text_color=COLOR_ACCENT).pack(anchor="w", padx=15, pady=(12, 4))

        appid_guide = (
            "App ID diperlukan Q-Buz untuk pencarian katalog & streaming audio.\n"
            "• Klik '🔍 Auto-Detect' untuk mendeteksi App ID aktif dari web player secara otomatis.\n"
            "• Atau salin nilai 'X-App-Id' (9 angka) dari browser DevTools (F12) -> Network tab (filter: api.json/0.2)."
        )
        CTk.CTkLabel(appid_frame, text=appid_guide, font=CTk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED, justify="left", anchor="w").pack(fill="x", padx=15, pady=(0, 10))

        appid_input_box = CTk.CTkFrame(appid_frame, fg_color="transparent")
        appid_input_box.pack(fill="x", padx=15, pady=4)
        appid_input_box.grid_columnconfigure(0, weight=1)

        self.appid_entry = CTk.CTkEntry(appid_input_box, placeholder_text="9-digit App ID (misal: 798273057)...")
        self.appid_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        if self.config.app_id:
            self.appid_entry.insert(0, self.config.app_id)

        self.detect_appid_btn = CTk.CTkButton(appid_input_box, text="🔍 Auto-Detect", width=110, fg_color=COLOR_FRAME_BG, hover_color="#2b374a", command=self.do_detect_appid)
        self.detect_appid_btn.grid(row=0, column=1)

        # 6. Alternative: Email & Password
        pwd_frame = CTk.CTkFrame(self.settings_view, fg_color="#141c28")
        pwd_frame.pack(fill="x", padx=20, pady=8)

        CTk.CTkLabel(pwd_frame, text="✉️ Metode Alternatif: Email & Password", font=CTk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=15, pady=(10, 2))
        CTk.CTkLabel(pwd_frame, text="(Catatan: Akun yang dibuat via Google/Apple atau versi baru wajib menggunakan metode token di atas).", font=CTk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED).pack(anchor="w", padx=15, pady=(0, 6))

        self.email_entry = CTk.CTkEntry(pwd_frame, placeholder_text="Email Q-Buz")
        self.email_entry.pack(fill="x", padx=15, pady=4)
        if self.config.user_email:
            self.email_entry.insert(0, self.config.user_email)

        self.pwd_entry = CTk.CTkEntry(pwd_frame, placeholder_text="Password Q-Buz", show="*")
        self.pwd_entry.pack(fill="x", padx=15, pady=4)

        pwd_btn_row = CTk.CTkFrame(pwd_frame, fg_color="transparent")
        pwd_btn_row.pack(fill="x", padx=15, pady=10)

        self.login_btn = CTk.CTkButton(pwd_btn_row, text="Login with Password", fg_color=COLOR_FRAME_BG, hover_color="#2b374a", command=self.do_login)
        self.login_btn.pack(side="left")

        # Save Settings button
        save_btn = CTk.CTkButton(self.settings_view, text="💾 Save All Settings", height=40, fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, text_color="black", font=CTk.CTkFont(size=13, weight="bold"), command=self.save_settings)
        save_btn.pack(anchor="w", padx=20, pady=20)

    def on_change_quality(self, val):
        rev = {v: k for k, v in FORMAT_LABELS.items()}
        self.config.format_id = rev.get(val, 27)
        self.config.save()

    def on_change_concurrency(self, val):
        iv = int(val)
        self.con_val_lbl.configure(text=str(iv))
        self.config.concurrent_downloads = iv
        self.downloader.update_concurrency(iv)
        self.config.save()

    def browse_dir(self):
        new_dir = filedialog.askdirectory(initialdir=self.config.download_directory)
        if new_dir:
            norm_dir = os.path.normpath(new_dir)
            self.dir_entry.delete(0, "end")
            self.dir_entry.insert(0, norm_dir)
            self.config.download_directory = norm_dir
            self.config.save()

    def do_detect_appid(self):
        self.detect_appid_btn.configure(state="disabled", text="Detecting...")

        async def detect():
            try:
                from .bundle_scraper import scrape_qobuz_web_credentials
                res = await scrape_qobuz_web_credentials(timeout_sec=15)
                if res and res.get("app_id"):
                    new_aid = res["app_id"]
                    self.config.app_id = new_aid
                    if res.get("app_secret"):
                        self.config.app_secret = res["app_secret"]
                    self.config.save()
                    def ok():
                        self.appid_entry.delete(0, "end")
                        self.appid_entry.insert(0, new_aid)
                        messagebox.showinfo("App ID Detected", f"Berhasil mendeteksi App ID aktif dari Web Player:\n\nApp ID: {new_aid}")
                    self.after(0, ok)
                else:
                    refreshed = await self.api.auto_refresh_app_credentials()
                    if refreshed:
                        def ok_cand():
                            self.appid_entry.delete(0, "end")
                            self.appid_entry.insert(0, self.config.app_id)
                            messagebox.showinfo("App ID Active", f"Menggunakan App ID valid yang terverifikasi:\n\nApp ID: {self.config.app_id}")
                        self.after(0, ok_cand)
                    else:
                        def fail():
                            messagebox.showwarning("Auto-Detect Failed", "Tidak dapat mendeteksi App ID secara otomatis dari web player.\n\nSilakan salin nilai 'X-App-Id' dari browser F12 Developer Tools -> tab Network (filter: api.json/0.2).")
                        self.after(0, fail)
            finally:
                self.after(0, lambda: self.detect_appid_btn.configure(state="normal", text="🔍 Auto-Detect"))

        self.run_async(detect())

    def save_settings(self):
        raw_dir = self.dir_entry.get().strip()
        if raw_dir:
            self.config.download_directory = os.path.normpath(raw_dir)
        self.config.naming_template = self.tpl_entry.get().strip()
        if hasattr(self, "appid_entry"):
            new_aid = self.appid_entry.get().strip()
            if new_aid:
                self.config.app_id = new_aid
        self.config.save()
        messagebox.showinfo("Settings Saved", "Your preferences have been saved successfully.")

    def do_login(self):
        email = self.email_entry.get().strip()
        pwd = self.pwd_entry.get().strip()
        if not email or not pwd:
            messagebox.showwarning("Incomplete", "Please enter your Q-Buz email and password.")
            return

        self.login_btn.configure(state="disabled", text="Logging in...")

        async def login_coro():
            try:
                data = await self.api.login(email, pwd)
                def ok():
                    self.login_btn.configure(state="normal", text="Login to Q-Buz")
                    self.update_user_display(True)
                    messagebox.showinfo("Login Succeeded", f"Welcome, {self.config.user_display_name}!\nPlan: {self.config.subscription_plan}")
                self.after(0, ok)
            except Exception as e:
                err_msg = str(e)
                def fail():
                    self.login_btn.configure(state="normal", text="Login to Q-Buz")
                    self.update_user_display(False)
                    messagebox.showerror("Login Failed", f"Could not log in to Q-Buz:\n{err_msg}")
                self.after(0, fail)
        self.run_async(login_coro())

    def _extract_token(self, raw_text):
        text = (raw_text or "").strip()
        if not text:
            return ""
        if "token" in text.lower():
            try:
                tok_obj = json.loads(text)
                clean = tok_obj.get("token") or tok_obj.get("userAuthToken")
                if clean:
                    return str(clean).strip(" \t\r\n\"'")
            except Exception:
                pass
            m = re.search(r'["\']?(?:userAuthToken|token)["\']?\s*:\s*["\']([^"\']+)["\']', text, re.I)
            if m:
                return m.group(1).strip()
        return text.strip(" \t\r\n\"'")

    def paste_token(self):
        try:
            cb_text = self._extract_token(self.clipboard_get())
            if cb_text:
                self.token_entry.delete(0, "end")
                self.token_entry.insert(0, cb_text)
        except Exception:
            pass

    def do_save_token(self):
        tok = self._extract_token(self.token_entry.get())
        if not tok:
            messagebox.showwarning("Empty Token", "Please paste your Q-Buz user_auth_token.")
            return

        # Ensure cleaned token is in entry box
        self.token_entry.delete(0, "end")
        self.token_entry.insert(0, tok)

        if hasattr(self, "save_token_btn") and self.save_token_btn.winfo_exists():
            self.save_token_btn.configure(state="disabled", text="Verifying Token...")

        async def verify():
            try:
                res = await self.api.verify_auth_token(tok)
                if res:
                    name = self.config.user_display_name or "Q-Buz Member"
                    plan = self.config.subscription_plan or "Studio Active"
                    def on_ok():
                        if hasattr(self, "appid_entry") and self.appid_entry.winfo_exists():
                            self.appid_entry.delete(0, "end")
                            self.appid_entry.insert(0, self.config.app_id)
                        messagebox.showinfo(
                            "Authentication Succeeded",
                            f"Login Berhasil!\n\nUser: {name}\nPlan: {plan}\nActive App ID: {self.config.app_id}"
                        )
                    self.after(0, on_ok)
                    self.after(0, lambda: self.update_user_display(True))
                else:
                    self.after(0, lambda: messagebox.showerror(
                        "Token Verification Failed",
                        "Token tidak dapat diverifikasi oleh Q-Buz API.\n\n"
                        "Penyebab umum:\n"
                        "1. Token sudah expired dari browser sebelumnya.\n"
                        "2. Token tersalin tidak lengkap.\n\n"
                        "Solusi:\n"
                        "Buka play.qobuz.com -> F12 -> Application -> Local Storage -> localuser -> salin ulang nilai 'userAuthToken' terbaru."
                    ))
                    self.after(0, lambda: self.update_user_display(False))
            finally:
                if hasattr(self, "save_token_btn") and self.save_token_btn.winfo_exists():
                    self.after(0, lambda: self.save_token_btn.configure(state="normal", text="Sign In with Token"))
        self.run_async(verify())

    def do_logout(self):
        self.config.clear_session()
        self.token_entry.delete(0, "end")
        self.pwd_entry.delete(0, "end")
        self.update_user_display(False)
        messagebox.showinfo("Logged Out", "You have been logged out from Q-Buz.")

    def check_login_status(self):
        if self.config.user_auth_token:
            if self.config.user_display_name or self.config.user_email:
                self.update_user_display(True)
            async def v():
                res = await self.api.verify_auth_token()
                self.after(0, lambda: self.update_user_display(bool(res)))
            self.run_async(v())
        else:
            self.update_user_display(False)

    def update_user_display(self, is_logged_in):
        if is_logged_in:
            name = self.config.user_display_name or self.config.user_email
            plan = self.config.subscription_plan or "Studio Master"
            self.user_name_lbl.configure(text=name, text_color=COLOR_ACCENT)
            self.user_sub_lbl.configure(text=f"Plan: {plan}", text_color=COLOR_GOLD)
        else:
            self.user_name_lbl.configure(text="Not Logged In", text_color="white")
            self.user_sub_lbl.configure(text="Hi-Res Studio Master", text_color=COLOR_TEXT_MUTED)

    def on_closing_save_session(self):
        """Saves unfinished download tasks (queued and downloading) to session.json so they can be resumed later."""
        try:
            session_data = []
            seen_tids = set()
            candidate_tids = list(self.queue_order) + [tid for tid in self.queue_items.keys() if tid not in self.queue_order]
            for tid in candidate_tids:
                if tid in seen_tids:
                    continue
                seen_tids.add(tid)
                item = self.queue_items.get(tid)
                if item and item.get("status") in ["queued", "downloading"]:
                    session_data.append({
                        "track_id": tid,
                        "title": item.get("title", f"Track {tid}"),
                        "parent_folder": item.get("parent_folder"),
                        "track_meta": item.get("track_meta")
                    })

            session_file = os.path.join(self.config.config_dir, "session.json")
            if session_data:
                os.makedirs(self.config.config_dir, exist_ok=True)
                with open(session_file, "w", encoding="utf-8") as f:
                    json.dump(session_data, f, ensure_ascii=False, indent=2)
            elif os.path.exists(session_file):
                try:
                    os.remove(session_file)
                except Exception:
                    pass
        except Exception as e:
            print(f"[Session Preservation] Failed to save session: {e}")

        # Cleanup preview temporary audio files
        try:
            import glob
            for target_dir in [self.config.config_dir, self.config.download_directory]:
                if target_dir and os.path.exists(target_dir):
                    for pat in ["preview_*.wav", "preview_*.mp3", "preview_*.tmp"]:
                        for fpath in glob.glob(os.path.join(target_dir, pat)):
                            try:
                                os.remove(fpath)
                            except Exception:
                                pass
        except Exception:
            pass

    def load_session(self):
        """Restores pending downloads from previous session if session.json exists."""
        try:
            session_file = os.path.join(self.config.config_dir, "session.json")
            if os.path.exists(session_file):
                with open(session_file, "r", encoding="utf-8") as f:
                    session_data = json.load(f)

                if session_data and isinstance(session_data, list):
                    restored_count = 0
                    for data in session_data:
                        tid = data.get("track_id")
                        title = data.get("title")
                        parent_folder = data.get("parent_folder")
                        track_meta = data.get("track_meta")
                        is_already_queued = (
                            tid in self.queue_items
                            or (isinstance(tid, int) and str(tid) in self.queue_items)
                            or (isinstance(tid, str) and str(tid).isdigit() and int(tid) in self.queue_items)
                        )
                        if tid and not is_already_queued:
                            self.queue_track_download(tid, title, parent_folder=parent_folder, track_meta=track_meta)
                            restored_count += 1

                    if restored_count > 0:
                        messagebox.showinfo(
                            "Session Restored",
                            f"Restored {restored_count} pending downloads from your previous session."
                        )

                try:
                    os.remove(session_file)
                except Exception:
                    pass
        except Exception as e:
            print(f"[Session Preservation] Failed to restore session: {e}")

    def on_closing(self):
        try:
            self.on_closing_save_session()
        except Exception as e:
            print(f"Error during on_closing_save_session: {e}")
        self.stop_preview()
        self._worker_running = False
        if hasattr(self, "_worker_future") and self._worker_future:
            self._worker_future.cancel()
        self.downloader.is_cancelled = True
        self._image_cache.clear()
        gc.collect()
        self.destroy()
