import ctypes
import os
import random
import sys
import winreg
import requests

# Link to your Wikimedia Commons user page gallery
WIKI_USER_PAGE = "User:Medium_Loud"

# Wikimedia requires a descriptive User-Agent header
HEADERS = {
    "User-Agent": "WikiWallpaperBot/1.0 (https://commons.wikimedia.org/wiki/User:Medium_Loud; desktop-wallpaper-tool)"
}


def set_windows_wallpaper_style(style="Fit"):
    """
    Sets the Windows Desktop Wallpaper style in the Registry.
    Options: 'Fill' (10, 0), 'Fit' (6, 0), 'Stretch' (2, 0), 'Center' (0, 0)
    """
    if sys.platform != "win32":
        return

    # Registry styles configuration: WallpaperStyle, TileWallpaper
    styles = {
        "Fill": ("10", "0"),  # Resizes image to fill screen (crops edges if aspect ratio differs)
        "Fit": ("6", "0"),   # Scales full image onto screen (adds letterbox bars if needed)
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
    """Fetches all image filenames embedded on the given Wikimedia Commons page."""
    endpoint = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "titles": user_page,
        "prop": "images",
        "imlimit": "max",
        "format": "json",
    }

    try:
        response = requests.get(endpoint, headers=HEADERS, params=params)
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


def get_wikimedia_image_url(image_title):
    """Queries Wikimedia Commons API for the direct full-resolution image download link."""
    endpoint = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "titles": image_title,
        "prop": "imageinfo",
        "iiprop": "url",
        "format": "json",
    }

    try:
        response = requests.get(endpoint, headers=HEADERS, params=params)
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", {})
        for _, page in pages.items():
            if "imageinfo" in page:
                return page["imageinfo"][0]["url"]
    except Exception as e:
        print(f"Error fetching image URL for {image_title}: {e}")

    return None


def download_image(url, save_path):
    """Downloads the image binary payload from the URL with error reporting."""
    try:
        res = requests.get(url, headers=HEADERS, timeout=15)
        if res.status_code == 200:
            with open(save_path, "wb") as f:
                f.write(res.content)
            return True
        else:
            print(
                f"HTTP Download Error: Server returned status code {res.status_code}"
            )
            return False
    except Exception as e:
        print(f"Network error during download: {e}")
        return False


def set_wallpaper(image_path, fit_mode="Fit"):
    """Applies the downloaded image as system wallpaper scaled to the display."""
    abs_path = os.path.abspath(image_path)
    
    if sys.platform == "win32":
        # 1. Update Windows Registry scaling preference
        set_windows_wallpaper_style(fit_mode)
        # 2. Apply desktop wallpaper change
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
        image_url = get_wikimedia_image_url(selected_image)

        if not image_url:
            print("Failed to resolve direct image URL. Trying next image...")
            continue

        save_dir = os.path.expanduser("~/ArtWallpapers")
        os.makedirs(save_dir, exist_ok=True)
        ext = os.path.splitext(image_url)[1]
        save_path = os.path.join(save_dir, f"daily_wallpaper{ext}")

        print(f"Downloading from: {image_url}")
        if download_image(image_url, save_path):
            # Set to "Fit" so full artwork is visible
            set_wallpaper(save_path, fit_mode="Fit")
            print("\nSuccess! Wallpaper updated in Fit mode.")
            return

    print("\nFailed to download after trying multiple images.")


if __name__ == "__main__":
    main()
