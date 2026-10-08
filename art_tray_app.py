import os
import socket
import subprocess
import sys
import threading
import textwrap
from PIL import Image, ImageDraw, ImageOps
import pystray

from app_paths import get_app_data_dir, get_wallpaper_dir
from metadata_utils import UNKNOWN_DATE, normalize_artwork_date

HOST = "127.0.0.1"
PORT = 65432
ICON_SIZE = 256
DATE_UNAVAILABLE = UNKNOWN_DATE


def get_current_wallpaper_path():
    wallpaper_dir = get_wallpaper_dir()
    valid_extensions = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}

    try:
        candidates = [
            os.path.join(wallpaper_dir, filename)
            for filename in os.listdir(wallpaper_dir)
            if os.path.splitext(filename)[0] == "daily_wallpaper"
            and os.path.splitext(filename)[1].lower() in valid_extensions
        ]
    except FileNotFoundError:
        return None

    return max(candidates, key=os.path.getmtime) if candidates else None


def get_metadata_path():
    return os.path.join(get_app_data_dir(), "metadata.txt")


def read_metadata():
    path = get_metadata_path()
    if not os.path.exists(path):
        return (
            "Daily Art",
            "No metadata generated yet.",
            DATE_UNAVAILABLE,
            "Artist information unavailable.",
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]

        title = lines[0] if len(lines) > 0 else "Unknown Title"
        artist = lines[1] if len(lines) > 1 else "Unknown Artist"
        date = normalize_artwork_date(lines[2]) if len(lines) > 2 else DATE_UNAVAILABLE
        artist_blurb = (
            lines[3] if len(lines) > 3 else "Artist information unavailable."
        )
        return title, artist, date, artist_blurb
    except Exception as e:
        return (
            "Daily Art",
            f"Error reading metadata: {e}",
            DATE_UNAVAILABLE,
            "Artist information unavailable.",
        )


def create_tray_icon_image():
    wallpaper_path = get_current_wallpaper_path()
    if wallpaper_path:
        try:
            with Image.open(wallpaper_path) as wallpaper:
                return ImageOps.fit(
                    wallpaper.convert("RGB"),
                    (ICON_SIZE, ICON_SIZE),
                    method=Image.Resampling.LANCZOS,
                )
        except (OSError, ValueError) as e:
            print(f"Could not load wallpaper for tray icon: {e}")

    image = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    scale = ICON_SIZE / 64
    draw.ellipse(
        (4 * scale, 4 * scale, 60 * scale, 60 * scale),
        fill=(40, 44, 52),
        outline=(220, 220, 220),
        width=round(3 * scale),
    )
    draw.polygon(
        [(20 * scale, 44 * scale), (32 * scale, 20 * scale), (44 * scale, 44 * scale)],
        fill=(230, 126, 34),
    )
    draw.ellipse(
        (26 * scale, 36 * scale, 38 * scale, 48 * scale),
        fill=(52, 152, 219),
    )

    return image


class ArtTrayApp:
    def __init__(self):
        self.title, self.artist, self.date, self.artist_blurb = read_metadata()
        self.icon = None
        self._stop_event = threading.Event()
        self._listener_started = threading.Event()
        self._listener_error = None

    def build_tooltip(self):
        hover_text = f"{self.title} | {self.artist} | {self.date}"
        return hover_text if len(hover_text) <= 120 else f"{hover_text[:117]}..."

    def update_metadata(self):
        self.title, self.artist, self.date, self.artist_blurb = read_metadata()

        if self.icon:
            self.icon.icon = create_tray_icon_image()
            self.icon.title = self.build_tooltip()
            self.icon.menu = self.build_menu()
            message = f"{self.title}\n{self.artist}\nDate: {self.date}"
            safe_message = message[:250] + "..." if len(message) > 256 else message
            self.icon.notify(safe_message, title="Wallpaper changed")

    def on_change_wallpaper(self, icon, item):
        project_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(project_dir, "wallpaper_changer.py")
        log_path = os.path.join(get_app_data_dir(), "wallpaper_changer.log")

        try:
            os.makedirs(get_app_data_dir(), exist_ok=True)
            startupinfo = None
            creationflags = 0
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW

            with open(log_path, "a", encoding="utf-8") as log_file:
                subprocess.Popen(
                    [sys.executable, script_path],
                    cwd=project_dir,
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    startupinfo=startupinfo,
                    creationflags=creationflags,
                )
        except OSError as e:
            message = f"Could not start wallpaper changer: {e}"
            print(message)
            icon.notify(message[:250], title="Wallpaper changer error")

    def build_menu(self):
        blurb_lines = textwrap.wrap(self.artist_blurb, width=60) or [
            "Artist information unavailable."
        ]
        artist_info_menu = pystray.Menu(
            *(
                pystray.MenuItem(line, lambda: None, enabled=False)
                for line in blurb_lines
            )
        )
        return pystray.Menu(
            pystray.MenuItem(f"Title: {self.title}", lambda: None, enabled=False),
            pystray.MenuItem(f"Artist: {self.artist}", lambda: None, enabled=False),
            pystray.MenuItem(f"Date: {self.date}", lambda: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Artist information", artist_info_menu),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Change Wallpaper", self.on_change_wallpaper),
            pystray.MenuItem("Refresh Metadata", lambda: self.update_metadata()),
            pystray.MenuItem("Exit", self.on_quit)
        )

    def start_socket_listener(self):
        """Listens for reload signals sent by wallpaper-changer.py."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind((HOST, PORT))
                server.listen(5)
                server.settimeout(0.5)
                self._listener_started.set()

                while not self._stop_event.is_set():
                    try:
                        conn, _ = server.accept()
                    except socket.timeout:
                        continue

                    with conn:
                        conn.settimeout(1.0)
                        try:
                            request = conn.recv(1024).strip()
                            if request == b"UPDATE":
                                self.update_metadata()
                                conn.sendall(b"OK\n")
                            else:
                                conn.sendall(b"ERROR: unknown request\n")
                        except socket.timeout:
                            continue
                        except OSError as e:
                            print(f"IPC request failed: {e}")
                        except Exception as e:
                            print(f"Could not refresh tray metadata: {e}")
                            try:
                                conn.sendall(f"ERROR: {e}\n".encode("utf-8"))
                            except OSError:
                                pass
        except OSError as e:
            self._listener_error = e
            self._listener_started.set()
            if not self._stop_event.is_set():
                print(f"IPC Listener error: {e}")

    def on_quit(self, icon, item):
        self._stop_event.set()
        icon.stop()

    def run(self):
        self.icon = pystray.Icon(
            "DailyArtMetadata",
            create_tray_icon_image(),
            title=self.build_tooltip(),
            menu=self.build_menu()
        )

        listener_thread = threading.Thread(target=self.start_socket_listener, daemon=True)
        listener_thread.start()

        self._listener_started.wait()
        if self._listener_error:
            listener_thread.join()
            raise RuntimeError(f"Could not start tray IPC listener: {self._listener_error}")

        try:
            self.icon.run()
        finally:
            self._stop_event.set()
            listener_thread.join(timeout=2.0)


if __name__ == "__main__":
    app = ArtTrayApp()
    app.run()