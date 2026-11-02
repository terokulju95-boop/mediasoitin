"""Musiikkikirjasto: tagien luku, kansikuvat ja kirjaston skannaus taustalla."""
import json
import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QThread, Signal

from .media import AUDIO_EXT, natural_key

try:
    import mutagen
    from mutagen.flac import Picture
except Exception:  # mutagen puuttuu -> toimitaan ilman tageja
    mutagen = None

LIB_AUDIO = AUDIO_EXT - {"cda"}
COVER_NAMES = ("cover", "folder", "front", "album", "albumart", "albumartsmall")


def _first(tags, *keys):
    for k in keys:
        try:
            v = tags.get(k)
        except Exception:
            v = None
        if v:
            v = v[0] if isinstance(v, (list, tuple)) else v
            v = getattr(v, "text", v)
            if isinstance(v, (list, tuple)):
                v = v[0] if v else ""
            if isinstance(v, tuple):  # MP4 trkn (nro, yht)
                v = v[0]
            s = str(v).strip()
            if s:
                return s
    return ""


def _num(s):
    try:
        return int(str(s).split("/")[0])
    except (ValueError, TypeError):
        return 0


def read_tags(path):
    """Palauttaa sanakirjan: title, artist, album, albumartist, genre, year, track, disc, duration."""
    p = Path(path)
    info = {"path": str(p), "title": p.stem, "artist": "", "album": "", "albumartist": "",
            "genre": "", "year": "", "track": 0, "disc": 0, "duration": 0.0}
    if mutagen is None:
        return info
    try:
        f = mutagen.File(str(p))
    except Exception:
        f = None
    if f is None:
        return info
    try:
        info["duration"] = float(getattr(f.info, "length", 0) or 0)
    except Exception:
        pass
    t = f.tags
    if not t:
        return info
    info["title"] = _first(t, "title", "TIT2", "\xa9nam", "Title", "WM/Title") or p.stem
    info["artist"] = _first(t, "artist", "TPE1", "\xa9ART", "Author", "Artist")
    info["albumartist"] = _first(t, "albumartist", "album artist", "TPE2", "aART", "WM/AlbumArtist")
    info["album"] = _first(t, "album", "TALB", "\xa9alb", "WM/AlbumTitle", "Album")
    info["genre"] = _first(t, "genre", "TCON", "\xa9gen", "WM/Genre", "Genre")
    info["year"] = _first(t, "date", "year", "TDRC", "TYER", "\xa9day", "WM/Year")[:4]
    info["track"] = _num(_first(t, "tracknumber", "TRCK", "trkn", "WM/TrackNumber", "Track"))
    info["disc"] = _num(_first(t, "discnumber", "TPOS", "disk", "WM/PartOfSet"))
    return info


def embedded_cover(path):
    """Upotettu kansikuva tavuina, tai None."""
    if mutagen is None:
        return None
    try:
        f = mutagen.File(str(path))
    except Exception:
        return None
    if f is None:
        return None
    pics = getattr(f, "pictures", None)          # FLAC
    if pics:
        front = [x for x in pics if x.type == 3] or pics
        return front[0].data
    t = f.tags
    if not t:
        return None
    try:
        apic = [v for k, v in t.items() if k.startswith("APIC")]   # MP3
        if apic:
            front = [x for x in apic if getattr(x, "type", 0) == 3] or apic
            return front[0].data
    except Exception:
        pass
    covr = t.get("covr") if hasattr(t, "get") else None             # M4A
    if covr:
        return bytes(covr[0])
    mbp = t.get("metadata_block_picture") if hasattr(t, "get") else None  # Ogg/Opus
    if mbp:
        import base64
        try:
            return Picture(base64.b64decode(mbp[0])).data
        except Exception:
            pass
    return None


def folder_cover(folder):
    """cover.jpg / folder.jpg / front.png … kansiosta."""
    try:
        files = [f for f in Path(folder).iterdir()
                 if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".bmp")]
    except OSError:
        return None
    if not files:
        return None
    for name in COVER_NAMES:
        for f in files:
            if f.stem.lower() == name:
                return f.read_bytes()
    big = max(files, key=lambda f: f.stat().st_size)      # muuten suurin kuva
    return big.read_bytes()


def find_cover(path):
    data = embedded_cover(path)
    if data:
        return data
    return folder_cover(Path(path).parent)


# ------------------------------------------------------------------ Kirjasto
def cache_file():
    d = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    os.makedirs(d, exist_ok=True)
    return Path(d) / "kirjasto.json"


def load_cache():
    try:
        return json.loads(cache_file().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(tracks: dict):
    try:
        cache_file().write_text(json.dumps(tracks, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


class LibraryScanner(QThread):
    progress = Signal(int, str)          # käsitellyt, nykyinen kansio
    finished_scan = Signal(dict)         # polku -> tagit

    def __init__(self, folders, parent=None):
        super().__init__(parent)
        self.folders = list(folders)
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        old = load_cache()
        result = {}
        n = 0
        for root in self.folders:
            for dirpath, _dirs, files in os.walk(root):
                if self._abort:
                    return
                for name in files:
                    if Path(name).suffix.lower().lstrip(".") not in LIB_AUDIO:
                        continue
                    full = os.path.join(dirpath, name)
                    try:
                        mtime = os.path.getmtime(full)
                    except OSError:
                        continue
                    cached = old.get(full)
                    if cached and cached.get("mtime") == mtime:
                        result[full] = cached          # ennallaan: ei lueta uudestaan
                    else:
                        info = read_tags(full)
                        info["mtime"] = mtime
                        result[full] = info
                    n += 1
                    if n % 50 == 0:
                        self.progress.emit(n, dirpath)
        save_cache(result)
        self.finished_scan.emit(result)


def group_library(tracks: dict):
    """artist -> album -> [kappaleet] järjestettynä."""
    tree = {}
    for t in tracks.values():
        artist = t.get("albumartist") or t.get("artist") or "Tuntematon artisti"
        album = t.get("album") or Path(t["path"]).parent.name or "Tuntematon albumi"
        tree.setdefault(artist, {}).setdefault(album, []).append(t)
    for albums in tree.values():
        for lst in albums.values():
            lst.sort(key=lambda t: (t.get("disc") or 0, t.get("track") or 0, natural_key(t["path"])))
    return tree
