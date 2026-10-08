import os
import socket
import sys
import threading
from PIL import Image, ImageDraw, ImageOps
import pystray

HOST = "127.0.0.1"
PORT = 65432


def get_current_wallpaper_path():
    wallpaper_dir = os.path.expanduser("~/ArtWallpapers")
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
    if getattr(sys, "frozen", False):
        project_dir = os.path.dirname(sys.executable)
    elif "__file__" in globals():
        project_dir = os.path.dirname(os.path.abspath(__file__))
    else:
        project_dir = os.getcwd()
    return os.path.join(project_dir, "metadata.txt")


def read_metadata():
    path = get_metadata_path()
    if not os.path.exists(path):
        return "Daily Art", "No metadata generated yet.", "Unknown Date"

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]

        title = lines[0] if len(lines) > 0 else "Unknown Title"
        artist = lines[1] if len(lines) > 1 else "Unknown Artist"
        date = lines[2] if len(lines) > 2 else "Unknown Date"
        return title, artist, date
    except Exception as e:
        return "Daily Art", f"Error reading metadata: {e}", "Unknown Date"


def create_tray_icon_image():
    wallpaper_path = get_current_wallpaper_path()
    if wallpaper_path:
        try:
            with Image.open(wallpaper_path) as wallpaper:
                return ImageOps.fit(
                    wallpaper.convert("RGB"),
                    (64, 64),
                    method=Image.Resampling.LANCZOS,
                )
        except (OSError, ValueError) as e:
            print(f"Could not load wallpaper for tray icon: {e}")

    image = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Outer ring
    draw.ellipse((4, 4, 60, 60), fill=(40, 44, 52), outline=(220, 220, 220), width=3)
    
    # Artistic shapes
    draw.polygon([(20, 44), (32, 20), (44, 44)], fill=(230, 126, 34))
    draw.ellipse((26, 36, 38, 48), fill=(52, 152, 219))
    
    return image


class ArtTrayApp:
    def __init__(self):
        self.title, self.artist, self.date = read_metadata()
        self.icon = None
        self._stop_event = threading.Event()
        self._listener_started = threading.Event()
        self._listener_error = None

    def build_tooltip(self):
        return f"🎨 {self.title}\n👤 {self.artist}\n📅 {self.date}"

    def update_metadata(self):
        self.title, self.artist, self.date = read_metadata()

        title = f"Wallpaper: {self.title}"
        message = f"Artist: {self.artist} ({self.date})"
        safe_title = title[:60] + "..." if len(title) > 64 else title
        safe_msg = message[:250] + "..." if len(message) > 256 else message

        if self.icon:
            self.icon.icon = create_tray_icon_image()
            self.icon.title = self.build_tooltip()
            self.icon.menu = self.build_menu()
            self.icon.notify(safe_msg, title=safe_title)

    def build_menu(self):
        return pystray.Menu(
            pystray.MenuItem(f"Title: {self.title}", lambda: None, enabled=False),
            pystray.MenuItem(f"Artist: {self.artist}", lambda: None, enabled=False),
            pystray.MenuItem(f"Date: {self.date}", lambda: None, enabled=False),
            pystray.Menu.SEPARATOR,
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
                            data = conn.recv(1024)
                        except socket.timeout:
                            continue
                        if data == b"UPDATE":
                            self.update_metadata()
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