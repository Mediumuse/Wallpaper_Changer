from html.parser import HTMLParser
import re
import unicodedata


class _GalleryArtistParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.artist_blurbs = {}
        self._capture_kind = None
        self._capture_depth = 0
        self._capture_text = []
        self._artist = ""
        self._blurb = ""
        self._in_gallery = False
        self._gallery_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "gallery":
            self._in_gallery = True
            self._gallery_text = []
            return

        if self._capture_kind:
            self._capture_depth += 1
            return

        if tag != "div":
            return

        style = dict(attrs).get("style", "").lower()
        if "font-size: 1.5em" in style and "font-weight: bold" in style:
            self._capture_kind = "artist"
        elif "font-size: 0.9em" in style and "color: #555" in style:
            self._capture_kind = "blurb"
        else:
            return

        self._capture_depth = 1
        self._capture_text = []

    def handle_endtag(self, tag):
        if tag == "gallery" and self._in_gallery:
            self._store_gallery_artists()
            self._in_gallery = False
            return

        if not self._capture_kind:
            return

        self._capture_depth -= 1
        if self._capture_depth:
            return

        text = " ".join("".join(self._capture_text).split())
        if self._capture_kind == "artist":
            self._artist = text
        elif self._capture_kind == "blurb":
            self._blurb = text

        self._capture_kind = None
        self._capture_text = []

    def handle_data(self, data):
        if self._capture_kind:
            self._capture_text.append(data)
        elif self._in_gallery:
            self._gallery_text.append(data)

    def _store_gallery_artists(self):
        if not self._artist or not self._blurb:
            return

        for line in "".join(self._gallery_text).splitlines():
            file_title = line.split("|", 1)[0].strip()
            if file_title.lower().startswith(("file:", "image:")):
                self.artist_blurbs[normalize_file_title(file_title)] = self._blurb


def normalize_file_title(title):
    normalized = unicodedata.normalize("NFKC", title).replace("_", " ")
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def parse_artist_blurbs(wikitext):
    parser = _GalleryArtistParser()
    parser.feed(wikitext)
    return parser.artist_blurbs
