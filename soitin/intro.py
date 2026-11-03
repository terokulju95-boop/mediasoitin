"""Alkutunnarin tunnistus.

1. Jakson luvut: jos luvun nimi on esim. "Intro", "Opening" tai "Alkutunnari".
2. Äänen vertailu: saman sarjan kahden jakson alusta etsitään kohta, jossa ääni on
   samanlaista (tunnusmusiikki). Ääni puretaan nopeasti ja siitä lasketaan
   "sormenjälki" (taajuuskaistojen muutokset 20 kertaa sekunnissa).
"""
import json
import os
import re
import tempfile
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QThread, Signal

try:
    import numpy as np
except Exception:          # numpy puuttuu -> vain lukuihin perustuva tunnistus
    np = None

SR = 8000                  # näytteenottotaajuus vertailussa
HOP = 400                  # 0,05 s
WIN = 1024
SCAN_SECONDS = 600         # vertaillaan jaksojen ensimmäiset 10 min
MIN_LEN, MAX_LEN = 12.0, 180.0
CHAPTER_RE = re.compile(r"\b(intro|opening|op|oped|alkutunnari|tunnari|tunnus|theme|title sequence|"
                        r"opening credits|avaus)\b", re.IGNORECASE)


# ------------------------------------------------------------------ Luvut
def from_chapters(chapters, duration):
    """chapters = mpv:n chapter-list. Palauttaa (alku, loppu) tai None."""
    if not chapters:
        return None
    for i, c in enumerate(chapters):
        title = str(c.get("title") or "")
        if CHAPTER_RE.search(title):
            start = float(c.get("time") or 0)
            end = float(chapters[i + 1].get("time")) if i + 1 < len(chapters) else (duration or 0)
            if MIN_LEN * 0.5 <= end - start <= MAX_LEN and start < 900:
                return start, end
    return None


# ------------------------------------------------------------------ Sormenjälki
def decode(path, seconds=SCAN_SECONDS):
    """Purkaa jakson alun ääneksi (8 kHz mono) käyttäen mpv:tä. Palauttaa numpy-taulukon."""
    from .player import mpv
    fd, raw = tempfile.mkstemp(prefix="mediasoitin_intro_", suffix=".raw")
    os.close(fd)
    try:
        p = mpv.MPV(vo="null", vid="no", sid="no", ao="pcm", ao_pcm_file=raw, ao_pcm_waveheader="no",
                    audio_samplerate=SR, audio_channels="mono", audio_format="s16", end=str(seconds),
                    load_scripts="no", ytdl="no", resume_playback="no", cache="no", input_default_bindings="no")
        try:
            p.play(str(path))
            p.wait_for_playback(timeout=120)
        finally:
            p.terminate()
        data = np.fromfile(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return data
    finally:
        try:
            os.remove(raw)
        except OSError:
            pass


def fingerprint(x):
    """16-bittinen sormenjälki jokaista 0,05 s jaksoa kohden (Haitsma–Kalker-tyyppinen)."""
    n = (len(x) - WIN) // HOP
    if n < 100:
        return np.zeros(0, dtype=np.uint32)
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(WIN)[None, :]
    spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    freqs = np.fft.rfftfreq(WIN, 1.0 / SR)
    edges = np.geomspace(150, 3400, 18)
    bands = np.stack([spec[:, (freqs >= edges[i]) & (freqs < edges[i + 1])].sum(axis=1)
                      for i in range(17)], axis=1)
    # Lattiataso: hiljaiset kaistat eivät tuota satunnaisia bittejä (pakkauksen kohinaa)
    floor = bands.sum(axis=1, keepdims=True) * 1e-3 + 1e-7
    e = np.log(np.maximum(bands, floor))
    d = e[:, :-1] - e[:, 1:]                       # kaistojen erot
    bits = (d[1:] - d[:-1]) > 1e-6                 # muutos ajassa
    weights = (1 << np.arange(16)).astype(np.uint32)
    fp = (bits.astype(np.uint32) * weights).sum(axis=1).astype(np.uint32)
    return np.concatenate([[0], fp]).astype(np.uint32)


def _popcount16(v):
    v = v - ((v >> 1) & 0x5555)
    v = (v & 0x3333) + ((v >> 2) & 0x3333)
    v = (v + (v >> 4)) & 0x0F0F
    return (v + (v >> 8)) & 0x1F


def _informative(seg):
    """Hylätään yksitoikkoinen ääni (hiljaisuus, vakiovihellys), joka 'täsmäisi' kaikkeen."""
    if len(seg) == 0:
        return False
    density = float((_popcount16(seg.astype(np.int64)) / 16.0).mean())
    variety = len(np.unique(seg)) / len(seg)
    return density >= 0.10 and variety >= 0.15


def match(fa, fb):
    """Etsii yhteisen jakson kahdesta sormenjäljestä.
    Palauttaa ((alkuA, loppuA), (alkuB, loppuB)) sekunteina tai None."""
    if len(fa) < 200 or len(fb) < 200:
        return None
    # 1) Samat sormenjäljet -> todennäköisin aikaero
    pos = {}
    for i, h in enumerate(fa.tolist()):
        if h:
            pos.setdefault(h, []).append(i)
    offsets = []
    for j, h in enumerate(fb.tolist()):
        lst = pos.get(h)
        if lst and len(lst) < 20:
            offsets.extend(j - i for i in lst)
    if len(offsets) < 20:
        return None
    vals, counts = np.unique(np.array(offsets), return_counts=True)
    best = None
    for k in np.argsort(counts)[::-1][:5]:          # kokeillaan 5 parasta aikaeroa
        off = int(vals[k])
        a0, b0 = max(0, -off), max(0, off)
        n = min(len(fa) - a0, len(fb) - b0)
        if n < 200:
            continue
        diff = np.bitwise_xor(fa[a0:a0 + n], fb[b0:b0 + n]) & 0xFFFF
        ber = _popcount16(diff.astype(np.int64)).astype(np.float32) / 16.0
        win = 40                                        # 2 s liukuva keskiarvo
        smooth = np.convolve(ber, np.ones(win) / win, mode="same")
        good = smooth < 0.30
        # pisin yhtenäinen samanlainen jakso
        run_start, best_len, best_start, cur = 0, 0, 0, 0
        for i, g in enumerate(good):
            if g:
                if cur == 0:
                    run_start = i
                cur += 1
                if cur > best_len:
                    best_len, best_start = cur, run_start
            else:
                cur = 0
        length = best_len * HOP / SR
        seg_a = fa[a0 + best_start:a0 + best_start + best_len]
        seg_b = fb[b0 + best_start:b0 + best_start + best_len]
        if (MIN_LEN <= length <= MAX_LEN and _informative(seg_a) and _informative(seg_b)
                and (best is None or length > best[0])):
            sa = (a0 + best_start) * HOP / SR
            sb = (b0 + best_start) * HOP / SR
            best = (length, (sa, sa + length), (sb, sb + length))
    if best is None:
        return None
    return best[1], best[2]


# ------------------------------------------------------------------ Välimuisti
def _cache_path():
    d = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation) or Path.home())
    d.mkdir(parents=True, exist_ok=True)
    return d / "alkutunnarit.json"


def load_cache():
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(c):
    try:
        if len(c) > 3000:
            c = dict(list(c.items())[-3000:])
        _cache_path().write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _key(path):
    try:
        st = os.stat(path)
        return f"{os.path.abspath(path)}|{st.st_size}"
    except OSError:
        return str(path)


def cached(path):
    v = load_cache().get(_key(path), "?")
    return v           # "?" = ei tutkittu, None = ei tunnaria, [alku, loppu] = löytyi


class IntroScanner(QThread):
    """Vertaa jaksoa saman sarjan toiseen jaksoon taustalla."""
    found = Signal(str, object)        # polku, (alku, loppu) tai None

    def __init__(self, path, other, parent=None):
        super().__init__(parent)
        self.path, self.other = str(path), str(other)

    def run(self):
        result = None
        try:
            if np is not None:
                fa = fingerprint(decode(self.path))
                fb = fingerprint(decode(self.other))
                m = match(fa, fb)
                c = load_cache()
                if m:
                    (sa, ea), (sb, eb) = m
                    result = (round(sa, 2), round(ea, 2))
                    c[_key(self.path)] = list(result)
                    c[_key(self.other)] = [round(sb, 2), round(eb, 2)]
                else:
                    c[_key(self.path)] = None
                save_cache(c)
        except Exception:
            result = None
        self.found.emit(self.path, result)
