import json
import os
import pathlib

# Default public app keys
DEFAULT_APP_ID = "712108782"
DEFAULT_APP_SECRET = "e91240c345167dbdbef56e07a68e98ec"

# Known public Qobuz client app credentials for auto-probing
KNOWN_APP_PAIRS = [
    ("798273057", "abb21364945c0583309667d13ca3d93a", "Web Client v8.2"),
    ("712108782", "e91240c345167dbdbef56e07a68e98ec", "Desktop Client"),
    ("809633634", "b27926955a50d249f3e46c76dbb4fc7d", "Web Bundle"),
    ("285431633", "a4f3b764b82d029519398f6d2f7881be", "Android Client"),
    ("385651648", "b27926955a50d249f3e46c76dbb4fc7d", "iOS Client"),
    ("598925120", "b27926955a50d249f3e46c76dbb4fc7d", "Soundgenic"),
    ("100000000", "b27926955a50d249f3e46c76dbb4fc7d", "Legacy Web Player"),
]

# Audio format definitions in Qobuz
FORMAT_LABELS = {
    27: "24-bit / up to 192kHz (Studio Master)",
    7: "24-bit / up to 96kHz (Hi-Res)",
    6: "16-bit / 44.1kHz (CD Lossless)",
    5: "MP3 320 kbps"
}

class Config:
    """Manages application configuration, user credentials, and preferences."""
    
    def __init__(self):
        self.config_dir = os.path.join(pathlib.Path.home(), ".qbz_rip")
        self.config_file = os.path.join(self.config_dir, "config.json")
        
        # Audio Quality (27 = Studio Master 24-bit / up to 192 kHz)
        self.format_id = 27
        
        # Paths & Naming
        default_music = os.path.join(pathlib.Path.home(), "Music", "Qobuz")
        self.download_directory = default_music
        self.naming_template = "{artist}/{album}/{track_num} - {title}.{ext}"
        
        # Performance & Notifications
        self.concurrent_downloads = 3
        self.play_sound_on_complete = True
        
        # API Credentials
        self.app_id = DEFAULT_APP_ID
        self.app_secret = DEFAULT_APP_SECRET
        
        # User Session
        self.user_auth_token = ""
        self.user_id = ""
        self.user_email = ""
        self.user_display_name = ""
        self.subscription_plan = ""

        # Search History
        self.recent_searches = []
        
        self.load()

    def load(self):
        """Loads configuration from JSON file."""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.format_id = int(data.get("format_id", 27))
                    self.download_directory = data.get("download_directory", self.download_directory)
                    self.naming_template = data.get("naming_template", self.naming_template)
                    self.concurrent_downloads = int(data.get("concurrent_downloads", 3))
                    self.play_sound_on_complete = bool(data.get("play_sound_on_complete", True))
                    
                    self.app_id = data.get("app_id") or DEFAULT_APP_ID
                    self.app_secret = data.get("app_secret") or DEFAULT_APP_SECRET
                    if self.app_id == "100000000":
                        self.app_id = DEFAULT_APP_ID
                        self.app_secret = DEFAULT_APP_SECRET
                    
                    self.user_auth_token = data.get("user_auth_token", "")
                    self.user_id = data.get("user_id", "")
                    self.user_email = data.get("user_email", "")
                    self.user_display_name = data.get("user_display_name", "")
                    self.subscription_plan = data.get("subscription_plan", "")
                    self.recent_searches = [s for s in data.get("recent_searches", []) if isinstance(s, str) and s.strip()]
            except Exception as e:
                print(f"Error loading config: {e}")

    def save(self):
        """Saves configuration to JSON file."""
        os.makedirs(self.config_dir, exist_ok=True)
        data = {
            "format_id": self.format_id,
            "download_directory": self.download_directory,
            "naming_template": self.naming_template,
            "concurrent_downloads": self.concurrent_downloads,
            "play_sound_on_complete": self.play_sound_on_complete,
            "app_id": self.app_id,
            "app_secret": self.app_secret,
            "user_auth_token": self.user_auth_token,
            "user_id": self.user_id,
            "user_email": self.user_email,
            "user_display_name": self.user_display_name,
            "subscription_plan": self.subscription_plan,
            "recent_searches": self.recent_searches[:10]
        }
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving config: {e}")

    def clear_session(self):
        """Clears user session on logout."""
        self.user_auth_token = ""
        self.user_id = ""
        self.user_email = ""
        self.user_display_name = ""
        self.subscription_plan = ""
        self.save()
