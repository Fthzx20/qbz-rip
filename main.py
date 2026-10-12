import asyncio
import sys
import threading
import customtkinter as CTk

from qbz_rip.config import Config
from qbz_rip.api import QobuzAPI
from qbz_rip.ui import QBZRipUI

def start_event_loop(loop):
    """Runs the asyncio event loop in a background daemon thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()

def main():
    # 1. Initialize Asyncio Event Loop in Background Thread
    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=start_event_loop, args=(loop,), daemon=True)
    loop_thread.start()

    # 2. Initialize Configuration & Qobuz API Client
    config = Config()
    api = QobuzAPI(config)

    # 3. Configure CustomTkinter Theme
    CTk.set_appearance_mode("dark")
    CTk.set_default_color_theme("blue")

    # 4. Launch Application UI
    app = QBZRipUI(api, config, loop)

    try:
        app.mainloop()
    finally:
        # Graceful cleanup on window close
        async def cleanup():
            current = asyncio.current_task()
            tasks = [t for t in asyncio.all_tasks() if t is not current]
            for t in tasks:
                t.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await api.close()

        future = asyncio.run_coroutine_threadsafe(cleanup(), loop)
        try:
            future.result(timeout=3)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)

if __name__ == "__main__":
    main()
