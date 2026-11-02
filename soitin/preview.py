"""Aikajanan esikatselukuvat: erillinen, näkymätön mpv purkaa pienen kuvan
halutusta kohdasta taustasäikeessä."""
import threading

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from .player import mpv


class ThumbnailWorker(QThread):
    ready = Signal(float, QImage)    # aika, kuva

    def __init__(self, parent=None, width=240):
        super().__init__(parent)
        self.width = width
        self._cond = threading.Condition()
        self._request = None          # (polku, aika) – vain uusin pyyntö käsitellään
        self._path = None
        self._stop = False
        self.player = None

    def request(self, path, t):
        with self._cond:
            self._request = (path, float(t))
            self._cond.notify()

    def stop(self):
        with self._cond:
            self._stop = True
            self._cond.notify()
        self.wait(2000)

    def run(self):
        try:
            self.player = mpv.MPV(vo="null", ao="null", pause="yes", hr_seek="no",
                                  vf=f"scale={self.width}:-2", aid="no", sid="no",
                                  hwdec="no", cache="no", ytdl="no", load_scripts="no")
        except Exception:
            return
        p = self.player
        while True:
            with self._cond:
                while self._request is None and not self._stop:
                    self._cond.wait()
                if self._stop:
                    break
                path, t = self._request
                self._request = None
            try:
                if path != self._path:
                    p.command("loadfile", path)
                    p.wait_for_event("file-loaded", timeout=3)
                    self._path = path
                p.command("seek", t, "absolute+keyframes")
                p.wait_for_event("playback-restart", timeout=1.5)
                r = p.command("screenshot-raw", "video")
                if r and r.get("data"):
                    img = QImage(r["data"], r["w"], r["h"], r["stride"], QImage.Format_RGB32).copy()
                    self.ready.emit(t, img)
            except Exception:
                self._path = None
        try:
            p.terminate()
        except Exception:
            pass
