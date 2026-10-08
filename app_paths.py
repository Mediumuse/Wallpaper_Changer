import os


def get_app_data_dir():
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return os.path.join(local_app_data, "WallpaperChanger")
    return os.path.join(
        os.path.expanduser("~"), ".local", "share", "WallpaperChanger"
    )


def get_wallpaper_dir():
    return os.path.join(os.path.expanduser("~"), "ArtWallpapers")
