import json
import os
import socket
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import wallpaper_changer
import art_tray_app
from artist_blurbs import normalize_file_title, parse_artist_blurbs
from metadata_utils import normalize_artwork_date
from selection_history import choose_random_candidates


class LoadGalleryPageTests(unittest.TestCase):
    def write_config(self, contents):
        config_file = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False
        )
        with config_file:
            config_file.write(contents)
        self.addCleanup(os.unlink, config_file.name)
        return config_file.name

    def test_loads_page_title(self):
        config_path = self.write_config(json.dumps({"gallery_page": "User:Example_User"}))

        self.assertEqual(wallpaper_changer.load_gallery_page(config_path), "User:Example User")

    def test_loads_commons_page_url(self):
        config_path = self.write_config(
            json.dumps(
                {
                    "gallery_page": (
                        "https://commons.wikimedia.org/wiki/User:Example_User"
                    )
                }
            )
        )

        self.assertEqual(wallpaper_changer.load_gallery_page(config_path), "User:Example User")

    def test_rejects_non_commons_url(self):
        config_path = self.write_config(
            json.dumps({"gallery_page": "https://example.com/wiki/User:Example"})
        )

        with self.assertRaisesRegex(ValueError, "commons.wikimedia.org"):
            wallpaper_changer.load_gallery_page(config_path)

    def test_rejects_non_object_config(self):
        config_path = self.write_config(json.dumps(["User:Example"]))

        with self.assertRaisesRegex(ValueError, "JSON object"):
            wallpaper_changer.load_gallery_page(config_path)

    def test_reports_missing_config(self):
        with self.assertRaisesRegex(ValueError, "Copy config.example.json"):
            wallpaper_changer.load_gallery_page("missing-config.json")


class GalleryImagesTests(unittest.TestCase):
    @patch.object(wallpaper_changer.requests, "get")
    def test_follows_api_continuation_and_filters_images(self, get):
        first_response = Mock()
        first_response.json.return_value = {
            "query": {
                "pages": {
                    "1": {
                        "images": [
                            {"title": "File:First.jpg"},
                            {"title": "File:Not an image.txt"},
                        ]
                    }
                }
            },
            "continue": {"imcontinue": "next-page", "continue": "||"},
        }
        second_response = Mock()
        second_response.json.return_value = {
            "query": {
                "pages": {"1": {"images": [{"title": "File:Second.png"}]}}
            }
        }
        get.side_effect = [first_response, second_response]

        images = wallpaper_changer.get_gallery_images("User:Example")

        self.assertEqual(images, ["File:First.jpg", "File:Second.png"])
        self.assertEqual(get.call_count, 2)
        self.assertEqual(
            get.call_args.kwargs["params"]["imcontinue"],
            "next-page",
        )

    def test_image_extension_ignores_url_query(self):
        extension = wallpaper_changer.get_image_extension(
            "https://upload.wikimedia.org/image.jpeg?download=1"
        )

        self.assertEqual(extension, ".jpeg")


class ArtworkDateTests(unittest.TestCase):
    def test_strips_time_from_artwork_creation_date(self):
        date = wallpaper_changer.get_artwork_date(
            {"DateTimeOriginal": {"value": "1890-05-10T16:44:28Z"}}
        )

        self.assertEqual(date, "1890-05-10")

    def test_uses_date_created_when_original_date_is_missing(self):
        date = wallpaper_changer.get_artwork_date(
            {"DateCreated": {"value": "circa 1890"}}
        )

        self.assertEqual(date, "circa 1890")

    def test_ignores_upload_timestamp_and_filename_year(self):
        date = wallpaper_changer.get_artwork_date(
            {"DateTime": {"value": "2019-12-05T16:44:28Z"}}
        )

        self.assertEqual(date, "Unknown")

    def test_reports_date_unavailable_when_artwork_date_is_missing(self):
        date = wallpaper_changer.get_artwork_date({})

        self.assertEqual(date, "Unknown")

    def test_cleans_wikimedia_structured_year(self):
        date = normalize_artwork_date(
            "1916date QS:P571,+1916-00-00T00:00:00Z/9"
        )

        self.assertEqual(date, "1916")

    def test_normalizes_saved_legacy_structured_year(self):
        with patch.object(
            art_tray_app, "get_metadata_path", return_value="unused\\metadata.txt"
        ), patch.object(art_tray_app.os.path, "exists", return_value=True), patch(
            "builtins.open",
            unittest.mock.mock_open(
                read_data=(
                    "Marsden Hartley - Handsome Drinks\n"
                    "Marsden Hartley\n"
                    "1916date QS:P571,+1916-00-00T00:00:00Z/9"
                )
            )
        ):
            self.assertEqual(
                art_tray_app.read_metadata(),
                (
                    "Marsden Hartley - Handsome Drinks",
                    "Marsden Hartley",
                    "1916",
                    "Artist information unavailable.",
                ),
            )

    def test_unrecognized_date_text_is_unknown(self):
        self.assertEqual(normalize_artwork_date("1916date extra text 83"), "Unknown")


class SelectionHistoryTests(unittest.TestCase):
    def test_reshuffles_remaining_images_on_each_run(self):
        class RotateRandom:
            def shuffle(self, items):
                items[:] = items[1:] + items[:1]

        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "selection.json")
            images = ["File:A.jpg", "File:B.jpg", "File:C.jpg", "File:D.jpg"]

            first = choose_random_candidates(
                images, state_path, count=1, rng=RotateRandom()
            )
            second = choose_random_candidates(
                images, state_path, count=1, rng=RotateRandom()
            )

        self.assertEqual(first, ["File:B.jpg"])
        self.assertEqual(second, ["File:D.jpg"])


class TrayNotificationTests(unittest.TestCase):
    def test_artist_blurb_round_trips_through_metadata_file(self):
        with tempfile.TemporaryDirectory() as app_data_dir:
            with patch.object(
                wallpaper_changer, "get_app_data_dir", return_value=app_data_dir
            ), patch.object(wallpaper_changer, "notify_tray_app"):
                wallpaper_changer.export_artwork_metadata(
                    "Test painting",
                    artist="Test artist",
                    date="1916",
                    artist_blurb="A short artist biography.",
                )

            with patch.object(
                art_tray_app, "get_app_data_dir", return_value=app_data_dir
            ):
                self.assertEqual(
                    art_tray_app.read_metadata(),
                    (
                        "Test painting",
                        "Test artist",
                        "1916",
                        "A short artist biography.",
                    ),
                )

    def test_tray_refresh_shows_all_artwork_metadata(self):
        class FakeIcon:
            def notify(self, message, title=None):
                self.notification = (title, message)

        app = art_tray_app.ArtTrayApp()
        app.icon = FakeIcon()
        with patch.object(
            art_tray_app,
            "read_metadata",
            return_value=(
                "Test painting",
                "Test artist",
                "1916",
                "A test artist biography.",
            ),
        ), patch.object(art_tray_app, "create_tray_icon_image", return_value="image"):
            app.update_metadata()

        title, message = app.icon.notification
        self.assertEqual(title, "Wallpaper changed")
        self.assertIn("Test painting", message)
        self.assertIn("Test artist", message)
        self.assertIn("Date: 1916", message)

    def test_artist_blurb_stays_in_submenu_and_hover_shows_artwork_metadata(self):
        blurb = ("A notable painter. " * 12).strip()
        app = art_tray_app.ArtTrayApp()
        app.title = "Test painting"
        app.artist = "Test artist"
        app.date = "1916"
        app.artist_blurb = blurb

        artist_info_item = next(
            item for item in app.build_menu().items if item.text == "Artist information"
        )

        self.assertIsNotNone(artist_info_item.submenu)
        self.assertEqual(
            " ".join(item.text for item in artist_info_item.submenu.items),
            blurb,
        )
        tooltip = app.build_tooltip()
        self.assertLessEqual(len(tooltip), 120)
        self.assertIn("Test painting", tooltip)
        self.assertIn("Test artist", tooltip)
        self.assertIn("1916", tooltip)
        self.assertNotIn(blurb, tooltip)

    def test_change_wallpaper_menu_item_launches_without_visible_console(self):
        app = art_tray_app.ArtTrayApp()
        menu_item = next(
            item for item in app.build_menu().items if item.text == "Change Wallpaper"
        )
        fake_icon = Mock()

        with tempfile.TemporaryDirectory() as app_data_dir, patch.object(
            art_tray_app, "get_app_data_dir", return_value=app_data_dir
        ), patch.object(art_tray_app.subprocess, "Popen") as popen:
            menu_item(fake_icon)

        project_dir = os.path.dirname(os.path.abspath(art_tray_app.__file__))
        args, kwargs = popen.call_args
        self.assertEqual(
            args[0],
            [art_tray_app.sys.executable, os.path.join(project_dir, "wallpaper_changer.py")],
        )
        self.assertEqual(kwargs["cwd"], project_dir)
        self.assertEqual(kwargs["stdin"], art_tray_app.subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], art_tray_app.subprocess.STDOUT)
        self.assertEqual(kwargs["stdout"].name, os.path.join(app_data_dir, "wallpaper_changer.log"))
        if os.name == "nt":
            self.assertEqual(kwargs["creationflags"], art_tray_app.subprocess.CREATE_NO_WINDOW)
            self.assertTrue(kwargs["startupinfo"].dwFlags & art_tray_app.subprocess.STARTF_USESHOWWINDOW)
            self.assertEqual(kwargs["startupinfo"].wShowWindow, art_tray_app.subprocess.SW_HIDE)

    def test_wallpaper_changer_receives_ack_after_tray_refresh(self):
        with socket.socket() as probe:
            probe.bind((art_tray_app.HOST, 0))
            port = probe.getsockname()[1]

        app = art_tray_app.ArtTrayApp()
        with patch.object(art_tray_app, "PORT", port), patch.object(
            app, "update_metadata"
        ) as refresh:
            listener = threading.Thread(target=app.start_socket_listener, daemon=True)
            listener.start()
            self.assertTrue(app._listener_started.wait(2))
            with patch.object(wallpaper_changer, "TRAY_PORT", port):
                self.assertTrue(wallpaper_changer.notify_tray_app())
            refresh.assert_called_once_with()
            app._stop_event.set()
            listener.join(2)
            self.assertFalse(listener.is_alive())


class ArtistBlurbParsingTests(unittest.TestCase):
    def test_maps_blurbs_to_gallery_file_titles(self):
        wikitext = """
<div style="font-size: 1.5em; font-weight: bold;">Paul Klee</div>
<div style="font-size: 0.9em; color: #555;">Swiss-German painter of <i>Der Blaue Reiter</i>.</div>
<gallery mode="packed-hover">
File:Paul_Klee_Artwork.jpg|Artwork caption
File:Other image.png
</gallery>
"""

        blurbs = parse_artist_blurbs(wikitext)

        self.assertEqual(
            blurbs[normalize_file_title("File:Paul Klee Artwork.jpg")],
            "Swiss-German painter of Der Blaue Reiter.",
        )
        self.assertEqual(
            blurbs[normalize_file_title("File:Other image.png")],
            "Swiss-German painter of Der Blaue Reiter.",
        )


if __name__ == "__main__":
    unittest.main()
