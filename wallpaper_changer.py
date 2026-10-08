import ctypes
import os
import random
import re
import socket
import sys
from urllib.parse import urlparse
import winreg
import requests

WIKI_USER_PAGE = "User:Medium_Loud"

HEADERS = {
    "User-Agent": "WikiWallpaperBot/1.0 (https://commons.wikimedia.org/wiki/User:Medium_Loud; desktop-wallpaper-tool)"
}

TRAY_HOST = "127.0.0.1"
TRAY_PORT = 65432
API_TIMEOUT = 15


def set_windows_wallpaper_style(style="Fit"):
    if sys.platform != "win32":
        return

    styles = {
        "Fill": ("10", "0"),
        "Fit": ("6", "0"),
        "Stretch": ("2", "0"),
        "Center": ("0", "0"),
    }

    wallpaper_style, tile_wallpaper = styles.get(style, ("6", "0"))

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Control Panel\Desktop",
            0,
            winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, wallpaper_style)
        winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, tile_wallpaper)
        winreg.CloseKey(key)
    except Exception as e:
        print(f"Failed to update Windows registry for wallpaper style: {e}")


def get_gallery_images(user_page):
    endpoint = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "titles": user_page,
        "prop": "images",
        "imlimit": "max",
        "format": "json",
    }

    try:
        response = requests.get(
            endpoint, headers=HEADERS, params=params, timeout=API_TIMEOUT
        )
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", {})

        image_titles = []
        for _, page in pages.items():
            if "images" in page:
                for img in page["images"]:
                    title = img["title"]
                    if title.lower().endswith(
                        (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")
                    ):
                        image_titles.append(title)

        return image_titles
    except Exception as e:
        print(f"Error querying gallery page: {e}")
        return []


def get_wikimedia_image_details(image_title):
    """
    Queries Wikimedia Commons API for direct image URL, artist metadata, and creation date.
    Strips HTML tags and parses metadata or fallback title dates.
    """
    endpoint = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "titles": image_title,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "format": "json",
    }

    try:
        response = requests.get(
            endpoint, headers=HEADERS, params=params, timeout=API_TIMEOUT
        )
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", {})

        for _, page in pages.items():
            if "imageinfo" in page:
                info = page["imageinfo"][0]
                url = info.get("url")
                extmetadata = info.get("extmetadata", {})

                # Extract and clean Artist
                raw_artist = extmetadata.get("Artist", {}).get("value", "")
                clean_artist = re.sub(r"<[^>]+>", "", raw_artist).strip()
                if not clean_artist:
                    clean_artist = "Unknown Artist"

                # Extract Date (DateTimeOriginal or DateTime)
                raw_date = extmetadata.get("DateTimeOriginal", {}).get("value", "")
                if not raw_date:
                    raw_date = extmetadata.get("DateTime", {}).get("value", "")

                clean_date = re.sub(r"<[^>]+>", "", raw_date).strip()

                # Clean up ISO timestamps (e.g., '1912-05-10T00:00:00' -> '1912-05-10')
                if "T" in clean_date:
                    clean_date = clean_date.split("T")[0]

                # Fallback: Extract 4-digit year from the filename if API date is missing or generic
                if not clean_date or len(clean_date) > 25:
                    year_match = re.search(r"\b(1[5-9]\d{2}|20[0-2]\d)\b", image_title)
                    clean_date = year_match.group(0) if year_match else "Unknown Date"

                return url, clean_artist, clean_date
    except Exception as e:
        print(f"Error fetching image details for {image_title}: {e}")

    return None, "Unknown Artist", "Unknown Date"


def download_image(url, save_path):
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code == 200:
            with open(save_path, "wb") as f:
                f.write(res.content)
            return True
        else:
            print(f"HTTP Download Error: Server returned status code {res.status_code}")
            return False
    except Exception as e:
        print(f"Network error during download: {e}")
        return False


def notify_tray_app():
    """Triggers the running system tray icon app to re-read metadata.txt."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(2.0)
            client.connect((TRAY_HOST, TRAY_PORT))
            client.sendall(b"UPDATE")
        print("Notified system tray app of metadata update.")
    except OSError as e:
        print(f"Could not notify tray app: {e}")


def export_artwork_metadata(title, artist="Unknown Artist", date="Unknown Date"):
    try:
        if getattr(sys, "frozen", False):
            project_dir = os.path.dirname(sys.executable)
        elif "__file__" in globals():
            project_dir = os.path.dirname(os.path.abspath(__file__))
        else:
            project_dir = os.getcwd()

        metadata_path = os.path.join(project_dir, "metadata.txt")

        # Format: Line 1 = Title, Line 2 = Artist, Line 3 = Date
        content = f"{title}\n{artist}\n{date}"

        with open(metadata_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Exported metadata to: {metadata_path}")

        notify_tray_app()

    except Exception as e:
        print(f"Failed to export metadata: {e}")


def set_wallpaper(image_path, fit_mode="Fit"):
    abs_path = os.path.abspath(image_path)

    if sys.platform == "win32":
        set_windows_wallpaper_style(fit_mode)
        ctypes.windll.user32.SystemParametersInfoW(20, 0, abs_path, 3)
    elif sys.platform == "darwin":
        os.system(
            f'osascript -e \'tell application "Finder" to set desktop picture to POSIX file "{abs_path}"\''
        )
    elif sys.platform.startswith("linux"):
        os.system(
            f"gsettings set org.gnome.desktop.background picture-uri file://{abs_path}"
        )


def main():
    print(
        f"Fetching gallery images from https://commons.wikimedia.org/wiki/{WIKI_USER_PAGE}..."
    )
    images = get_gallery_images(WIKI_USER_PAGE)

    if not images:
        print("No images found on your gallery page or failed to query API.")
        return

    print(f"Found {len(images)} images in your gallery.")

    random.shuffle(images)
    for selected_image in images[:3]:
        print(f"\nTrying image: {selected_image}")
        image_url, artist_name, art_date = get_wikimedia_image_details(selected_image)

        if not image_url:
            print("Failed to resolve direct image URL. Trying next image...")
            continue

        save_dir = os.path.expanduser("~/ArtWallpapers")
        os.makedirs(save_dir, exist_ok=True)
        ext = os.path.splitext(urlparse(image_url).path)[1]
        save_path = os.path.join(save_dir, f"daily_wallpaper{ext}")

        print(f"Downloading from: {image_url}")
        if download_image(image_url, save_path):
            set_wallpaper(save_path, fit_mode="Fit")

            # Clean artwork title
            clean_title = selected_image.replace("File:", "")
            clean_title = os.path.splitext(clean_title)[0]
            clean_title = clean_title.replace("_", " ")

            export_artwork_metadata(title=clean_title, artist=artist_name, date=art_date)

            print(
                f"\nSuccess! Updated wallpaper.\nTitle: {clean_title}\nArtist: {artist_name}\nDate: {art_date}"
            )
            return

    print("\nFailed to download after trying multiple images.")


if __name__ == "__main__":
    main()