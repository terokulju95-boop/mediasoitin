"""Tiedostotyypit ja apufunktiot."""
import re
from pathlib import Path

AUDIO_EXT = {
    "mp3", "mp2", "mp1", "flac", "wav", "w64", "rf64", "aif", "aiff", "aifc",
    "ape", "wv", "m4a", "m4b", "aac", "alac", "ogg", "oga", "opus", "spx",
    "wma", "dsf", "dff", "mka", "ac3", "eac3", "dts", "dtshd", "thd", "mlp",
    "tta", "mpc", "amr", "au", "snd", "caf", "tak", "ofr", "shn", "ra",
    "cda",
}
VIDEO_EXT = {
    "mp4", "m4v", "mkv", "mk3d", "webm", "avi", "mov", "qt", "wmv", "asf",
    "flv", "f4v", "mpg", "mpeg", "mpe", "m1v", "m2v", "ts", "m2ts", "mts",
    "tp", "trp", "vob", "3gp", "3g2", "ogv", "rm", "rmvb", "divx", "xvid",
    "hevc", "h264", "h265", "264", "265", "y4m", "dv", "mxf", "nut", "ivf",
    "iso",
}
PLAYLIST_EXT = {"m3u", "m3u8", "pls", "cue"}

MEDIA_EXT = AUDIO_EXT | VIDEO_EXT | PLAYLIST_EXT
NAME_FILTERS = sorted(f"*.{e}" for e in MEDIA_EXT) + sorted(f"*.{e.upper()}" for e in MEDIA_EXT)


def is_media(path) -> bool:
    return Path(path).suffix.lower().lstrip(".") in MEDIA_EXT


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]


def media_in_folder(folder, recursive=False):
    folder = Path(folder)
    try:
        it = folder.rglob("*") if recursive else folder.iterdir()
        files = [p for p in it if p.is_file() and is_media(p) and p.suffix.lower() != ".cda"]
    except OSError:
        return []
    return sorted(files, key=lambda p: natural_key(str(p.relative_to(folder))))


def cda_track_number(path) -> int:
    """Track05.cda -> 5"""
    m = re.search(r"(\d+)", Path(path).stem)
    return int(m.group(1)) if m else 1


def fmt_time(sec) -> str:
    if sec is None or sec < 0:
        return "--:--"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


SAMPLE_FORMATS = {
    "u8": "8-bit", "s16": "16-bit", "s32": "24/32-bit", "float": "32-bit float",
    "double": "64-bit float", "s64": "64-bit int",
}


def describe_format(fmt) -> str:
    if not fmt:
        return ""
    base = fmt.rstrip("p")
    return SAMPLE_FORMATS.get(base, fmt)


def display_name(entry: dict) -> str:
    """Nimi mpv:n soittolistarivistä."""
    if entry.get("title"):
        return entry["title"]
    fn = entry.get("filename", "")
    if fn.startswith("cdtrack://"):
        return f"CD – kappale {fn.rsplit('/', 1)[-1]}"
    if fn.startswith("cdda://"):
        return "Musiikki-CD"
    if fn.startswith("dvd://"):
        return "DVD"
    if fn.startswith("bd://"):
        return "Blu-ray"
    return Path(fn).name or fn
