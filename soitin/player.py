"""mpv-toistomoottori upotettuna Qt-ikkunaan.

libmpv purkaa äänen ja kuvan alkuperäisessä muodossaan (FFmpeg), joten
lähes mikä tahansa tiedosto toistuu ilman muunnoksia.
"""
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QWidget


def _prepare_libmpv():
    """Etsi libmpv-2.dll sovelluksen kansiosta (Windows)."""
    here = Path(__file__).resolve().parent
    candidates = [
        Path(getattr(sys, "_MEIPASS", here)),
        Path(sys.executable).resolve().parent,
        here.parent,
        here.parent / "lib",
    ]
    for d in candidates:
        if (d / "libmpv-2.dll").exists():
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(str(d))
            return


_prepare_libmpv()
import mpv  # noqa: E402

from . import cdaudio  # noqa: E402


def _s(v):
    return v.decode(errors="replace") if isinstance(v, bytes) else v


class MpvSignals(QObject):
    prop = Signal(str, object)          # ominaisuuden nimi, arvo
    end_file = Signal(str, str, str)    # syy, virhe, tiedosto
    file_loaded = Signal()
    key = Signal(str)                   # näppäin/hiiritapahtuma videoikkunassa


WATCHED = [
    "time-pos", "duration", "pause", "idle-active", "playlist", "playlist-pos",
    "media-title", "metadata", "chapter", "chapter-list", "track-list", "volume", "mute",
    "audio-params", "audio-out-params", "audio-codec-name", "current-ao",
    "video-params", "video-codec", "loop-playlist", "loop-file", "af",
    "audio-exclusive", "hwdec-current",
]

KEYS = ["MBTN_LEFT_DBL", "SPACE", "f", "F", "ESC", "RIGHT", "LEFT", "UP", "DOWN",
        "m", "n", "p", "PGUP", "PGDWN", "WHEEL_UP", "WHEEL_DOWN", "MBTN_RIGHT"]


class MpvWidget(QWidget):
    """Musta alue, johon mpv piirtää videon."""

    def __init__(self, parent=None, exclusive=False, volume=100):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self.setAttribute(Qt.WA_NativeWindow)
        self.setStyleSheet("background:black;")
        self.setMinimumSize(320, 180)
        self.signals = MpvSignals()

        opts = dict(
            wid=str(int(self.winId())),
            idle="yes",
            keep_open="no",
            force_window="yes",         # videoalue pysyy aina olemassa
            # --- Kuva ---
            vo="gpu-next,gpu,direct3d,x11,null",
            hwdec="auto-safe",          # laitteistopurku, kuvanlaatu sama
            # --- Ääni ---
            volume=volume,
            volume_max=100,             # ei vahvistusta -> ei säröä
            gapless_audio="weak",       # saumaton toisto albumeille
            prefetch_playlist="yes",
            replaygain="no",
            audio_display="embedded-first",  # näytä kansikuva
            # --- Ohjaus ---
            input_default_bindings="no",
            input_vo_keyboard="yes",
            osc="no",
            cursor_autohide=1500,
            # --- Levyt ---
            cache="yes",
        )
        if sys.platform == "win32":
            opts["ao"] = "wasapi"
            opts["audio_exclusive"] = "yes" if exclusive else "no"

        try:
            self.mpv = mpv.MPV(**opts)
        except Exception:
            # Varalla yksinkertaisemmat asetukset vanhemmille mpv-versioille
            for k in ("prefetch_playlist", "audio_display", "cursor_autohide"):
                opts.pop(k, None)
            self.mpv = mpv.MPV(**opts)

        # Paras kuvanlaatu (mpv:n valmis profiili), jos saatavilla
        try:
            self.mpv.command("apply-profile", "high-quality")
        except Exception:
            pass

        # Musiikki-CD:t: oma lukija (cdtrack://D/5)
        try:
            self.mpv.register_stream_protocol("cdtrack", cdaudio.open_stream)
        except Exception:
            pass

        for name in WATCHED:
            try:
                self.mpv.observe_property(name, self._on_prop)
            except Exception:
                pass

        @self.mpv.event_callback("end-file")
        def _end(ev):
            d = ev.as_dict()
            self.signals.end_file.emit(_s(d.get("reason", "")), _s(d.get("file_error", "")) or "",
                                       str(d.get("playlist_entry_id", "")))

        @self.mpv.event_callback("file-loaded")
        def _loaded(ev):
            self.signals.file_loaded.emit()

        for k in KEYS:
            try:
                self.mpv.register_key_binding(k, self._make_key_handler(k))
            except Exception:
                pass

    def _make_key_handler(self, key):
        def handler(state, *a):
            # "d-" = painettu alas, "p-" = yksittäinen painallus (rulla, tuplaklikkaus)
            if state and state[0] in "dp":
                self.signals.key.emit(key)
        return handler

    def _on_prop(self, name, value):
        self.signals.prop.emit(name, value)

    # --- Apurit ---
    def get(self, name, default=None):
        try:
            return self.mpv._get_property(name)
        except Exception:
            return default

    def set(self, name, value):
        try:
            self.mpv._set_property(name, value)
            return True
        except Exception:
            return False

    def cmd(self, *args):
        try:
            self.mpv.command(*args)
            return True
        except Exception:
            return False

    def osd(self, ass_text: str):
        """Pysyvä tekstikerros videon päällä (ASS-muotoilu). Tyhjä poistaa."""
        if ass_text:
            self.cmd("osd-overlay", 1, "ass-events", ass_text, 1280, 720, 0)
        else:
            self.cmd("osd-overlay", 1, "none", "")

    def set_exclusive(self, on: bool):
        """WASAPI exclusive = Windows ei sekoita/muunna ääntä (bit-perfect)."""
        if sys.platform != "win32":
            return False
        self.set("audio-exclusive", "yes" if on else "no")
        self.cmd("ao-reload")
        return True

    def shutdown(self):
        try:
            self.mpv.terminate()
        except Exception:
            pass
