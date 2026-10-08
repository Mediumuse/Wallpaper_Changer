import ctypes
import json
import os
import random
import re
import socket
import sys
from urllib.parse import unquote, urlparse
import winreg
import requests

from app_paths import get_app_data_dir, get_wallpaper_dir
from artist_blurbs import normalize_file_title, parse_artist_blurbs
from metadata_utils import UNKNOWN_DATE, normalize_artwork_date
from selection_history import choose_random_candidates, get_selection_state_path

HEADERS = {
    "User-Agent": "WallpaperChanger/1.0 (https://github.com/Mediumuse/Wallpaper_Changer)"
}

TRAY_HOST = "127.0.0.1"
TRAY_PORT = 65432
API_TIMEOUT = 15
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")
DATE_UNAVAILABLE = UNKNOWN_DATE
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_gallery_page(config_path=CONFIG_PATH):
    try:
        with open(config_path, "r", encoding="utf-8") as config_file:
            configuration = json.load(config_file)
    except FileNotFoundError as e:
        raise ValueError(
            "Configuration file not found. Copy config.example.json to config.json "
            "and set gallery_page to your Wikimedia Commons user or gallery page."
        ) from e
    except (json.JSONDecodeError, OSError) as e:
        raise ValueError(f"Could not read configuration file {config_path}: {e}") from e

    if not isinstance(configuration, dict):
        raise ValueError(f"Configuration file {config_path} must contain a JSON object.")
    gallery_page = configuration.get("gallery_page")
    if not isinstance(gallery_page, str) or not gallery_page.strip():
        raise ValueError(f"Set a non-empty gallery_page in {config_path}.")

    gallery_page = gallery_page.strip()
    parsed = urlparse(gallery_page)
    if "://" in gallery_page or parsed.netloc:
        if parsed.scheme != "https" or parsed.netloc.lower() != "commons.wikimedia.org":
            raise ValueError(
                "gallery_page URLs must use https://commons.wikimedia.org/wiki/."
            )
        if not parsed.path.startswith("/wiki/"):
            raise ValueError(
                "gallery_page URL must point to a Wikimedia Commons wiki page."
            )
        gallery_page = unquote(parsed.path[len("/wiki/") :])

    if not gallery_page.strip():
        raise ValueError("gallery_page must name a Wikimedia Commons page.")

    return gallery_page.replace("_", " ")


def get_image_extension(image_url):
    return os.path.splitext(urlparse(image_url).path)[1]


def get_artwork_date(extmetadata):
    for field in ("DateTimeOriginal", "DateCreated"):
        raw_date = extmetadata.get(field, {}).get("value", "")
        clean_date = normalize_artwork_date(raw_date)
        if clean_date != UNKNOWN_DATE:
            return clean_date

    return UNKNOWN_DATE


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
        image_titles = []
        while True:
            response = requests.get(
                endpoint, headers=HEADERS, params=params, timeout=API_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
            pages = data.get("query", {}).get("pages", {})

            for page in pages.values():
                for image in page.get("images", []):
                    title = image.get("title", "")
                    if title.lower().endswith(IMAGE_EXTENSIONS):
                        image_titles.append(title)

            continuation = data.get("continue")
            if not continuation:
                break
            params.update(continuation)

        return image_titles
    except Exception as e:
        print(f"Error querying gallery page: {e}")
        return []


def get_gallery_artist_blurbs(user_page):
    endpoint = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "parse",
        "page": user_page,
        "prop": "wikitext",
        "format": "json",
    }

    try:
        response = requests.get(
            endpoint, headers=HEADERS, params=params, timeout=API_TIMEOUT
        )
        response.raise_for_status()
        wikitext = response.json().get("parse", {}).get("wikitext", {}).get("*", "")
        blurbs = parse_artist_blurbs(wikitext)
        if not blurbs:
            print(f"No artist blurbs were found on the Commons page {user_page}.")
        return blurbs
    except Exception as e:
        print(f"Error fetching artist blurbs from {user_page}: {e}")
        return {}


def get_wikimedia_image_details(image_title):
    """
    Queries Wikimedia Commons API for direct image URL, artist, and artwork date.
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

                clean_date = get_artwork_date(extmetadata)

                return url, clean_artist, clean_date
    except Exception as e:
        print(f"Error fetching image details for {image_title}: {e}")

    return None, "Unknown Artist", DATE_UNAVAILABLE


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
    """Requests a tray refresh and verifies that it was applied."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(2.0)
            client.connect((TRAY_HOST, TRAY_PORT))
            client.sendall(b"UPDATE\n")
            client.shutdown(socket.SHUT_WR)
            response = client.recv(1024).decode("utf-8").strip()
        if response != "OK":
            print(f"Tray app did not confirm its update: {response or 'no response'}")
            return False
        print("Tray app refreshed and displayed the artwork notification.")
        return True
    except OSError as e:
        print(f"Could not notify tray app: {e}")
        return False


def export_artwork_metadata(
    title,
    artist="Unknown Artist",
    date=DATE_UNAVAILABLE,
    artist_blurb="Artist information unavailable.",
):
    try:
        os.makedirs(get_app_data_dir(), exist_ok=True)
        metadata_path = os.path.join(get_app_data_dir(), "metadata.txt")

        clean_blurb = " ".join(artist_blurb.splitlines()).strip()
        content = f"{title}\n{artist}\n{date}\n{clean_blurb}"

        temporary_path = f"{metadata_path}.tmp"
        with open(temporary_path, "w", encoding="utf-8") as metadata_file:
            metadata_file.write(content)
        os.replace(temporary_path, metadata_path)
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
    for output_stream in (sys.stdout, sys.stderr):
        if hasattr(output_stream, "reconfigure"):
            output_stream.reconfigure(errors="backslashreplace")

    try:
        gallery_page = load_gallery_page()
    except ValueError as e:
        print(f"Configuration error: {e}")
        return 2

    print(
        f"Fetching gallery images from https://commons.wikimedia.org/wiki/{gallery_page.replace(' ', '_')}..."
    )
    images = get_gallery_images(gallery_page)

    if not images:
        print("No images found on your gallery page or failed to query API.")
        return 1

    print(f"Found {len(images)} images in your gallery.")
    artist_blurbs = get_gallery_artist_blurbs(gallery_page)

    try:
        current_wallpaper = get_wallpaper_dir()
        current_metadata_path = os.path.join(get_app_data_dir(), "metadata.txt")
        previous_image = None
        try:
            with open(current_metadata_path, "r", encoding="utf-8") as metadata_file:
                previous_title = metadata_file.readline().strip()
            if previous_title:
                previous_image = f"File:{previous_title}"
        except FileNotFoundError:
            pass

        candidates = choose_random_candidates(
            images,
            get_selection_state_path(gallery_page),
            count=3,
            previous_image=previous_image,
        )
    except (OSError, ValueError) as e:
        print(f"Could not update wallpaper selection history: {e}")
        return 2

    for selected_image in candidates:
        print(f"\nTrying image: {selected_image}")
        image_url, artist_name, art_date = get_wikimedia_image_details(selected_image)

        if not image_url:
            print("Failed to resolve direct image URL. Trying next image...")
            continue

        save_dir = get_wallpaper_dir()
        os.makedirs(save_dir, exist_ok=True)
        ext = get_image_extension(image_url)
        save_path = os.path.join(save_dir, f"daily_wallpaper{ext}")

        print(f"Downloading from: {image_url}")
        if download_image(image_url, save_path):
            set_wallpaper(save_path, fit_mode="Fit")

            # Clean artwork title
            clean_title = selected_image.replace("File:", "")
            clean_title = os.path.splitext(clean_title)[0]
            clean_title = clean_title.replace("_", " ")
            artist_blurb = artist_blurbs.get(
                normalize_file_title(selected_image),
                "Artist information unavailable.",
            )

            export_artwork_metadata(
                title=clean_title,
                artist=artist_name,
                date=art_date,
                artist_blurb=artist_blurb,
            )

            print(
                f"\nSuccess! Updated wallpaper.\nTitle: {clean_title}\nArtist: {artist_name}\nDate: {art_date}"
            )
            return 0

    print("\nFailed to download after trying multiple images.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())