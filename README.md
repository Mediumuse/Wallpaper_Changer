# Wikimedia Commons Wallpaper Changer

Download an image from a Wikimedia Commons user or gallery page, set it as the
Windows desktop wallpaper, and optionally show its artwork details and image in
a system-tray icon.

## Requirements

- Windows 10 or later
- Python 3.9 or later
- Internet access
- A Wikimedia Commons page that contains image links

## Install

Clone or download this repository, open a terminal in the project folder, and
install the dependencies:

```powershell
python -m pip install -r requirements.txt
```

Copy the example configuration and open it:

```powershell
Copy-Item config.example.json config.json
notepad config.json
```

Set `gallery_page` to your Wikimedia Commons page title or URL. For example:

```json
{
  "gallery_page": "User:YourWikimediaUsername"
}
```

Or use a full page URL:

```json
{
  "gallery_page": "https://commons.wikimedia.org/wiki/User:YourWikimediaUsername"
}
```

The selected page must contain image links; the script searches files embedded
on that page. `config.json` is local and is not tracked by Git.

## Run

Change the wallpaper:

```powershell
python wallpaper_changer.py
```

Optionally, keep the artwork details and matching wallpaper image in the system
tray by starting the tray app in another terminal:

```powershell
python art_tray_app.py
```

Use the tray icon menu to refresh metadata or exit the tray app. The wallpaper
changer also notifies a running tray app when it downloads a new image. Choose
**Change Wallpaper** from the tray menu to run the wallpaper changer without
opening a console window. Output and errors are appended to
`%LOCALAPPDATA%\WallpaperChanger\wallpaper_changer.log`. The
tray app updates its icon, menu, and tooltip and displays the artwork title,
artist, and date in a Windows notification. Where the configured Commons page
lists the selected file under an artist biography, the full blurb appears in
the tray's **Artist information** submenu and a short excerpt appears on hover.

## Files and behavior

- Wallpapers are saved to `%USERPROFILE%\ArtWallpapers`.
- Generated metadata is saved under `%LOCALAPPDATA%\WallpaperChanger`.
- `metadata.example.txt` illustrates the generated metadata format; it is not
  read by the app.
- The wallpaper changer tries up to three random images if a download fails.
- Artwork dates come only from Commons artwork-creation fields; upload
  timestamps are not used. When Commons has no artwork date, the tray shows
  `Unknown`.
- Wikimedia Commons API requests use timeouts and include a descriptive
  User-Agent.

## Troubleshooting

- If startup reports a configuration error, create `config.json` from
  `config.example.json` and check the page title or URL.
- If no images are found, confirm the Commons page embeds images and is publicly
  accessible.
- If the tray app is not running, the wallpaper changer still works; metadata
  remains available for the next tray-app startup.
- Run both commands from a terminal to see error messages.

## Tests

Run the standard-library tests with:

```powershell
python -m unittest discover -s tests
```
