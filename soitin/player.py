"""mpv-toistomoottori piirrettynä sovelluksen omaan OpenGL-näkymään.

Video piirretään mpv:n render-rajapinnalla suoraan Qt-ikkunaan. Näin hiiri ja
näppäimistö tulevat aina sovellukselle (klikkaus = tauko, tuplaklikkaus = koko
näyttö), ja palkit voi näyttää videon päällä.

libmpv purkaa äänen ja kuvan alkuperäisessä muodossaan (FFmpeg).
"""
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QOpenGLContext, QPainter
from PySide6.QtOpenGLWidgets import QOpenGLWidget


def _prepare_libmpv():
    """Etsi libmpv-2.dll sovelluksen kansiosta (Windows)."""
    here = Path(__file__).resolve().parent
    for d in (Path(getattr(sys, "_MEIPASS", here)), Path(sys.executable).resolve().parent,
              here.parent, here.parent / "lib"):
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
    end_file = Signal(str, str, str)    # syy, virhe, soittolistan id
    file_loaded = Signal()
    redraw = Signal()


WATCHED = [
    "time-pos", "duration", "pause", "idle-active", "playlist", "playlist-pos",
    "media-title", "metadata", "chapter", "chapter-list", "track-list", "volume", "mute",
    "audio-params", "audio-out-params", "audio-codec-name", "current-ao",
    "video-params", "video-codec", "loop-playlist", "loop-file", "af",
    "audio-exclusive", "hwdec-current", "speed", "path",
]


class MpvWidget(QOpenGLWidget):
    clicked = Signal()
    double_clicked = Signal()
    right_clicked = Signal()
    wheel = Signal(int)          # +1 ylös, -1 alas
    mouse_moved = Signal()

    def __init__(self, parent=None, options=None):
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.signals = MpvSignals()
        self.signals.redraw.connect(self.update)
        self.render_ctx = None
        self.show_frame = False       # onko mpv:llä kuvaa (video tai kansikuva)
        self.info = None              # (rivit, alhaalla?) tekstinäkymä
        self.accent = QColor("#D35400")
        # Varmistus: pyydetään piirtoa säännöllisesti, ettei kuva jää jumiin esim.
        # koko näytön vaihdon jälkeen (mpv odottaa, että edellinen ruutu piirretään).
        self.kick = QTimer(self, interval=250, timeout=self.update)

        opts = dict(
            vo="libmpv",
            idle="yes",
            keep_open="no",
            hwdec="auto-safe",            # laitteistopurku, kuvanlaatu sama
            volume_max=100,               # ei vahvistusta -> ei säröä
            gapless_audio="weak",         # saumaton toisto albumeille
            prefetch_playlist="yes",
            replaygain="no",
            audio_display="embedded-first",
            input_default_bindings="no",
            input_vo_keyboard="no",
            osc="no",
            cache="yes",
        )
        if sys.platform == "win32":
            opts["ao"] = "wasapi"
        opts.update(options or {})
        try:
            self.mpv = mpv.MPV(**opts)
        except Exception:
            for k in ("prefetch_playlist", "audio_display"):
                opts.pop(k, None)
            self.mpv = mpv.MPV(**opts)

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

    def _on_prop(self, name, value):
        self.signals.prop.emit(name, value)

    # ---------------------------------------------------------- OpenGL
    def initializeGL(self):
        def get_proc_address(_ctx, name):
            ctx = QOpenGLContext.currentContext()
            if ctx is None:
                return 0
            addr = ctx.getProcAddress(name.decode())
            return int(addr) if addr else 0

        self._proc_fn = mpv.MpvGlGetProcAddressFn(get_proc_address)  # pidetään viite
        self.render_ctx = mpv.MpvRenderContext(
            self.mpv, "opengl", opengl_init_params={"get_proc_address": self._proc_fn})
        self.render_ctx.update_cb = self.signals.redraw.emit

    def paintGL(self):
        r = self.devicePixelRatioF()
        w, h = int(self.width() * r), int(self.height() * r)
        if self.render_ctx is not None and self.show_frame:
            self.render_ctx.render(flip_y=True, opengl_fbo={
                "w": w, "h": h, "fbo": self.defaultFramebufferObject()})
            if self.info:
                self._paint_info(clear=False)
        else:
            self._paint_info(clear=True)

    def _paint_info(self, clear):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        if clear:
            p.fillRect(self.rect(), QColor("#000000"))
        if not self.info:
            p.end()
            return
        lines, bottom = self.info
        scale = max(0.6, min(1.6, self.height() / 600))
        metrics = []
        total = 0
        for text, size, color, bold in lines:
            f = QFont(self.font())
            f.setPointSizeF(size * scale)
            f.setBold(bold)
            p.setFont(f)
            hgt = p.fontMetrics().height() * 1.15
            metrics.append((text, f, color, hgt))
            total += hgt
        y = (self.height() - total - 40 * scale) if bottom else (self.height() - total) / 2
        if bottom:
            p.fillRect(QRectF(0, y - 16 * scale, self.width(), total + 56 * scale), QColor(0, 0, 0, 170))
        for text, f, color, hgt in metrics:
            p.setFont(f)
            p.setPen(QColor(color))
            p.drawText(QRectF(20, y, self.width() - 40, hgt), Qt.AlignHCenter | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(text, Qt.ElideRight, self.width() - 40))
            y += hgt
        p.end()

    def set_info(self, lines, bottom=False):
        """lines = [(teksti, pistekoko, väri, lihavoitu), ...]; None poistaa."""
        self.info = (lines, bottom) if lines else None
        self.update()

    def set_show_frame(self, on):
        if on != self.show_frame:
            self.show_frame = on
            self.kick.start() if on else self.kick.stop()
            self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.update()

    # ---------------------------------------------------------- Hiiri
    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
        elif e.button() == Qt.RightButton:
            self.right_clicked.emit()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.double_clicked.emit()

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if d:
            self.wheel.emit(1 if d > 0 else -1)

    def mouseMoveEvent(self, e):
        self.mouse_moved.emit()

    # ---------------------------------------------------------- Apurit
    # Komennot lähetetään asynkronisesti: käyttöliittymä ei koskaan jää odottamaan
    # mpv:tä (synkroninen kutsu piirtosäikeestä voi jumittaa kuvan hetkeksi).
    def get(self, name, default=None):
        try:
            return self.mpv._get_property(name)
        except Exception:
            return default

    @staticmethod
    def _str(value):
        if isinstance(value, bool):
            return "yes" if value else "no"
        return str(value)

    def set(self, name, value):
        try:
            self.mpv.command_async("set", name, self._str(value), callback=lambda e, r: None)
            return True
        except Exception:
            return False

    def cmd(self, *args):
        try:
            self.mpv.command_async(*[self._str(a) if not isinstance(a, str) else a for a in args],
                                   callback=lambda e, r: None)
            return True
        except Exception:
            return False

    def set_exclusive(self, on: bool):
        """WASAPI exclusive = Windows ei sekoita/muunna ääntä (bit-perfect)."""
        if sys.platform != "win32":
            return False
        self.set("audio-exclusive", "yes" if on else "no")
        self.cmd("ao-reload")
        return True

    def shutdown(self):
        try:
            if self.render_ctx is not None:
                self.makeCurrent()
                self.render_ctx.free()
                self.render_ctx = None
                self.doneCurrent()
        except Exception:
            pass
        try:
            self.mpv.terminate()
        except Exception:
            pass
