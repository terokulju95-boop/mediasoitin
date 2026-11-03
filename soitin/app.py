"""Mediasoittimen pääikkuna."""
import sys
import time
from pathlib import Path

from PySide6.QtCore import (QDir, QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation,
                            QSize, QStandardPaths, Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import (QAction, QActionGroup, QColor, QCursor, QDesktopServices, QIcon,
                           QKeySequence, QPixmap)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QFileSystemModel,
    QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMenu, QMessageBox, QProgressDialog, QSlider, QSplitter, QStyle, QTabWidget,
    QToolButton, QTreeView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__, cdaudio, library, subtitles, theme, updater, videoadjust
from .radio import RadioPanel
from . import inputsim
from .remote import PairCodeDialog, RemoteDialog, RemoteServer
from .dvdcopy import DvdCopyWorker, disc_size, safe_name, unique_folder
from .preview import ThumbnailWorker
from .drives import NETWORK, OPTICAL, REMOVABLE, list_drives, quick_locations
from .icons import icon
from .media import (NAME_FILTERS, cda_track_number, describe_format, display_name,
                    fmt_time, media_in_folder, natural_key)
from .player import MpvWidget
from .settings import ACTIONS, Config, SettingsDialog

IS_WIN = sys.platform == "win32"
ASSETS = Path(__file__).resolve().parent / "assets"
ASPECTS = [("-1", "Alkuperäinen"), ("16:9", "16:9"), ("4:3", "4:3"), ("2.39:1", "21:9 (elokuva 2.39:1)"),
           ("1.85:1", "1.85:1"), ("1:1", "1:1")]
NAV_KEYS = {Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp,
            Qt.Key_PageDown, Qt.Key_Home, Qt.Key_End}


class NavKeyFilter(QObject):
    """Kun tiedosto- tai soittolista on valittuna, nuolinäppäimet liikkuvat listassa
    eivätkä kelaa. Muualla (esim. videon päällä) ne toimivat pikanäppäiminä."""

    def eventFilter(self, obj, e):
        if e.type() == QEvent.ShortcutOverride and isinstance(obj, QAbstractItemView):
            if e.key() in NAV_KEYS and not (e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier)):
                e.accept()
                return True
        return False


class SeekSlider(QSlider):
    """Aikajana: klikkaus hyppää suoraan kohtaan."""
    seek = Signal(float)

    hover = Signal(float, QPoint)    # aika (s), kohta näytöllä
    hover_end = Signal()

    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.dragging = False
        self.setRange(0, 0)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

    def _value_at(self, e):
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
                                              int(e.position().x()), max(1, self.width()))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.maximum() > 0:
            self.dragging = True
            self.setValue(self._value_at(e))

    def mouseMoveEvent(self, e):
        if self.dragging:
            self.setValue(self._value_at(e))
        if self.maximum() > 0:
            x = int(min(max(e.position().x(), 0), self.width()))
            self.hover.emit(self._value_at(e) / 1000.0, self.mapToGlobal(QPoint(x, 0)))

    def leaveEvent(self, e):
        self.hover_end.emit()

    def mouseReleaseEvent(self, e):
        if self.dragging:
            self.dragging = False
            self.seek.emit(self.value() / 1000.0)


class Overlay(QWidget):
    """Koko näytön tilassa videon päälle ilmestyvä palkki (videon lapsi-widget)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground)
        self.setObjectName("overlay")
        self.setMouseTracking(True)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(10, 6, 10, 6)
        self.at_top = True
        self.target = None
        self.effect = QGraphicsOpacityEffect(self)
        self.effect.setOpacity(1.0)
        self.setGraphicsEffect(self.effect)
        self.anim_pos = QPropertyAnimation(self, b"pos", self)
        self.anim_op = QPropertyAnimation(self.effect, b"opacity", self)
        for a in (self.anim_pos, self.anim_op):
            a.setDuration(220)
            a.setEasingCurve(QEasingCurve.OutCubic)
        self.anim_op.finished.connect(self._anim_done)
        self._hiding = False
        self.hide()

    def _offscreen(self):
        g = self.target
        return QPoint(g.x(), g.y() - g.height() // 2) if self.at_top else QPoint(g.x(), g.y() + g.height() // 2)

    def slide_in(self, animate):
        self._hiding = False
        self.anim_pos.stop()
        self.anim_op.stop()
        if not animate:
            self.setGeometry(self.target)
            self.effect.setOpacity(1.0)
            self.show()
            return
        if not self.isVisible():
            self.setGeometry(self.target)
            self.move(self._offscreen())
            self.effect.setOpacity(0.0)
            self.show()
        self.anim_pos.setStartValue(self.pos())
        self.anim_pos.setEndValue(self.target.topLeft())
        self.anim_op.setStartValue(self.effect.opacity())
        self.anim_op.setEndValue(1.0)
        self.anim_pos.start()
        self.anim_op.start()

    def slide_out(self, animate):
        if not self.isVisible():
            return
        if not animate:
            self.hide()
            return
        self._hiding = True
        self.anim_pos.stop()
        self.anim_op.stop()
        self.anim_pos.setStartValue(self.pos())
        self.anim_pos.setEndValue(self._offscreen())
        self.anim_op.setStartValue(self.effect.opacity())
        self.anim_op.setEndValue(0.0)
        self.anim_pos.start()
        self.anim_op.start()

    def _anim_done(self):
        if self._hiding:
            self._hiding = False
            self.hide()

    def shown(self):
        return self.isVisible() and not self._hiding


class PreviewPopup(QWidget):
    """Aikajanan päällä näkyvä aika ja esikatselukuva."""

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setObjectName("preview")
        self.setAttribute(Qt.WA_StyledBackground)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        self.img = QLabel()
        self.img.setAlignment(Qt.AlignCenter)
        self.time = QLabel()
        self.time.setAlignment(Qt.AlignCenter)
        self.time.setObjectName("previewTime")
        lay.addWidget(self.img)
        lay.addWidget(self.time)
        self.img.hide()

    def show_at(self, text, gpos):
        self.time.setText(text)
        self.adjustSize()
        self.move(gpos.x() - self.width() // 2, gpos.y() - self.height() - 10)
        self.show()
        self.raise_()

    def set_image(self, img):
        if img is None:
            self.img.hide()
        else:
            self.img.setPixmap(QPixmap.fromImage(img))
            self.img.show()


class NextCard(QWidget):
    """“Seuraava jakso” -kortti videon oikeassa alakulmassa."""
    play_now = Signal()
    cancel = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground)
        self.setObjectName("nextCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(6)
        self.head = QLabel("SEURAAVA JAKSO")
        self.head.setObjectName("nextHead")
        self.name = QLabel("")
        self.name.setObjectName("nextName")
        self.name.setWordWrap(True)
        self.count = QLabel("")
        self.count.setObjectName("nextCount")
        btns = QHBoxLayout()
        self.now_btn = QToolButton(text="▶  Toista nyt")
        self.now_btn.setObjectName("nextNow")
        self.cancel_btn = QToolButton(text="Peruuta")
        self.cancel_btn.setObjectName("nextCancel")
        for b in (self.now_btn, self.cancel_btn):
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
        self.now_btn.clicked.connect(self.play_now)
        self.cancel_btn.clicked.connect(self.cancel)
        btns.addWidget(self.now_btn)
        btns.addWidget(self.cancel_btn)
        btns.addStretch()
        for w in (self.head, self.name, self.count):
            lay.addWidget(w)
        lay.addLayout(btns)
        self.setFixedWidth(340)
        self.hide()


class MainWindow(QMainWindow):
    def __init__(self, files=None):
        super().__init__()
        self.cfg = Config()
        self.settings = self.cfg.qs          # ikkunan koko, paneelit ym.
        self.accent = self.cfg.get("accent")
        self.state = {}                      # mpv:n viimeisimmät ominaisuusarvot
        self.playlist = []
        self.pending_chapter = None
        self.fullscreen = False
        self._drive_sig = None
        self._click_time = 0.0
        self._auto_fs_done = False
        self._last_cursor = None

        self.setWindowTitle("Mediasoitin")
        self.resize(1280, 760)
        self.setAcceptDrops(True)

        volume = self.settings.value("volume", 100, type=int) if self.cfg.get("remember_volume") else 100
        self.video = MpvWidget(options=self._mpv_options(volume))
        self.video.accent = QColor(self.accent)
        dev = self.settings.value("audio_device", "", type=str)
        if dev:
            self.video.set("audio-device", dev)
        quality = self.cfg.get("quality")
        if quality in ("high-quality", "fast"):
            self.video.cmd("apply-profile", quality)
        shots = Path(QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or Path.home()) / "Mediasoitin"
        self.screenshot_dir = shots
        self.video.set("screenshot-directory", str(shots))
        self.video.set("screenshot-format", "png")
        self.video.set("screenshot-template", "%F %wH.%wM.%wS")
        videoadjust.apply_saved(self.video, self.settings)
        subtitles.apply(self.video, self.settings)
        self.sub_dialog = None
        self._shaders = []
        self.video.set("deinterlace", "auto")   # vanhemmissa mpv-versioissa jää oletukseen
        self.adjust_dialog = None
        self.tag_cache = {}             # polku -> tagit (albuminäkymä)
        self.cover_cache = {}           # polku/kansio -> QPixmap
        self.library_tracks = library.load_cache()
        self.scanner = None
        self.dvd_worker = None
        self._ready = False
        QTimer.singleShot(1500, lambda: setattr(self, "_ready", True))
        self.preview = PreviewPopup()
        self.thumbs = ThumbnailWorker(self)
        self.thumbs.ready.connect(self._thumb_ready)
        self.thumbs.start()
        self._hover = None
        self.thumb_timer = QTimer(self, singleShot=True, interval=90, timeout=self._request_thumb)
        self.radio_names = {}           # striimin osoite -> aseman nimi
        self._next_state = "idle"       # idle / counting / dismissed
        self._next_left = 0
        self.next_timer = QTimer(self, interval=1000, timeout=self._next_tick)
        self.remote = RemoteServer(self)
        self.remote.command.connect(self.on_remote_command)
        self.remote.pair_requested.connect(self._show_pair_code)
        self.remote.pair_finished.connect(self._pair_done)
        self.pair_dialog = None
        self.remote_dialog = None
        self._cover_bytes = None
        self.remote_timer = QTimer(self, interval=700, timeout=self.update_remote_state)
        self.update_checker = None
        self.update_dl = None

        self._build_ui()
        self._build_actions()
        self._build_menus()
        self._build_fullscreen()
        self.refresh_icons()
        self.nav_filter = NavKeyFilter(self)
        QApplication.instance().installEventFilter(self.nav_filter)

        sig = self.video.signals
        sig.prop.connect(self.on_prop)
        sig.end_file.connect(self.on_end_file)
        sig.file_loaded.connect(self.on_file_loaded)
        self.video.clicked.connect(self.on_video_click)
        self.video.double_clicked.connect(self.on_video_double_click)
        self.video.right_clicked.connect(self.show_main_menu)
        self.video.wheel.connect(self.on_video_wheel)
        self.video.mouse_moved.connect(self.on_mouse_activity)

        self.refresh_drives()
        self.drive_timer = QTimer(self, interval=3000, timeout=self.refresh_drives)
        self.drive_timer.start()
        QTimer.singleShot(100, self.show_idle)

        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        self.left_tabs.setCurrentIndex(self.settings.value("left_tab", 0, type=int))
        if self.left_tabs.currentIndex() == 2:
            QTimer.singleShot(500, self.radio.ensure_loaded)
        self._build_next_card()
        if self.cfg.get("remote_enabled") and self.remote.start(self.cfg.get("remote_port")):
            self.remote_timer.start()
        if self.cfg.get("check_updates"):
            QTimer.singleShot(4000, lambda: self.check_updates(silent=True))
        self.rebuild_library()
        for name, sp in (("split_main", self.split_main), ("split_left", self.split_left)):
            st = self.settings.value(name)
            if st is not None:
                sp.restoreState(st)
        self.library_panel.setVisible(self.settings.value("show_library", True, type=bool))
        self.playlist_panel.setVisible(self.settings.value("show_playlist", True, type=bool))
        self.statusBar().setVisible(self.settings.value("show_status", True, type=bool))

        start = self.settings.value("last_dir", "", type=str)
        if start and Path(start).is_dir():
            self.browse(start)

        if files:
            QTimer.singleShot(300, lambda: self.add_paths(files, play=True))

    def _mpv_options(self, volume):
        c = self.cfg
        opts = dict(
            volume=volume,
            hwdec="auto-safe" if c.get("hwdec") else "no",
            alang=c.get("alang"), slang=c.get("slang"),
            sub_auto="fuzzy" if c.get("sub_auto") else "no",
            sub_scale=c.get("sub_scale"),
            resume_playback="yes" if c.get("resume") else "no",
        )
        if IS_WIN:
            opts["audio_exclusive"] = "yes" if c.get("exclusive") else "no"
        return opts

    def apply_settings(self):
        """Ota asetusikkunan muutokset käyttöön heti."""
        c = self.cfg
        v = self.video
        v.set("hwdec", "auto-safe" if c.get("hwdec") else "no")
        v.set("alang", c.get("alang"))
        v.set("slang", c.get("slang"))
        v.set("sub-auto", "fuzzy" if c.get("sub_auto") else "no")
        v.set("sub-scale", c.get("sub_scale"))
        v.set("resume-playback", "yes" if c.get("resume") else "no")
        if IS_WIN and (self.state.get("audio-exclusive") in (True, "yes")) != c.get("exclusive"):
            v.set_exclusive(c.get("exclusive"))
        self.excl_action.blockSignals(True)
        self.excl_action.setChecked(c.get("exclusive"))
        self.excl_action.blockSignals(False)
        self.hide_timer.setInterval(int(c.get("hide_delay") * 1000))
        for aid, act in self.act.items():
            act.setShortcut(QKeySequence(c.key(aid)))
        self.update_seek_labels()
        if c.get("accent") != self.accent:
            self.set_accent(c.get("accent"))
        if self.state.get("idle-active", True):
            self.show_idle()
        self.update_audio_info()

    def open_settings(self):
        old_quality = self.cfg.get("quality")
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec():
            self.apply_settings()
            if self.cfg.get("quality") != old_quality:
                QMessageBox.information(self, "Asetukset",
                                        "Kuvanlaadun muutos tulee voimaan, kun soitin käynnistetään uudelleen.")

    # ================================================================ UI
    def _panel_title(self, text):
        lbl = QLabel(text.upper())
        lbl.setObjectName("panelTitle")
        return lbl

    def _button(self, tip, slot, name=None):
        b = QToolButton(toolTip=tip)
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)   # välilyönti ja nuolet eivät jää painikkeisiin
        b.clicked.connect(slot)
        if name:
            b.setObjectName(name)
        return b

    def _build_ui(self):
        # --- Vasen paneeli: lähteet + tiedostot
        self.drive_tree = QTreeWidget()
        self.drive_tree.setHeaderHidden(True)
        self.drive_tree.setIndentation(14)
        self.drive_tree.itemClicked.connect(self.on_drive_clicked)
        self.drive_tree.itemDoubleClicked.connect(self.on_drive_double)
        self.drive_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.drive_tree.customContextMenuRequested.connect(self.drive_menu)

        self.fs_model = QFileSystemModel(self)
        self.fs_model.setRootPath("")
        self.fs_model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot | QDir.Drives)
        self.fs_model.setNameFilters(NAME_FILTERS)
        self.fs_model.setNameFilterDisables(False)

        self.file_view = QTreeView()
        self.file_view.setModel(self.fs_model)
        self.file_view.setSortingEnabled(True)
        self.file_view.sortByColumn(0, Qt.AscendingOrder)
        self.file_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_view.setHeaderHidden(True)
        self.file_view.setRootIsDecorated(False)
        self.file_view.setDragEnabled(True)
        for c in (1, 2, 3):
            self.file_view.hideColumn(c)
        self.file_view.doubleClicked.connect(self.on_file_double)
        self.file_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_view.customContextMenuRequested.connect(self.file_menu)

        self.up_btn = self._button("Ylös", self.browse_up)
        self.path_label = QLabel("Valitse asema tai kansio")
        self.path_label.setObjectName("pathLabel")
        path_row = QHBoxLayout()
        path_row.setContentsMargins(2, 0, 2, 0)
        path_row.addWidget(self.up_btn)
        path_row.addWidget(self.path_label, 1)

        top_box = QWidget()
        tl = QVBoxLayout(top_box)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        tl.addWidget(self._panel_title("Lähteet"))
        tl.addWidget(self.drive_tree)
        file_box = QWidget()
        fl = QVBoxLayout(file_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)
        fl.addWidget(self._panel_title("Tiedostot"))
        fl.addLayout(path_row)
        fl.addWidget(self.file_view)

        self.split_left = QSplitter(Qt.Vertical)
        self.split_left.setHandleWidth(3)
        self.split_left.addWidget(top_box)
        self.split_left.addWidget(file_box)
        self.split_left.setSizes([220, 480])

        self.left_tabs = QTabWidget()
        self.left_tabs.setObjectName("leftTabs")
        self.left_tabs.setDocumentMode(True)
        self.left_tabs.addTab(self.split_left, "Selaa")
        self.left_tabs.addTab(self._build_library_panel(), "Kirjasto")
        self.radio = RadioPanel(self.accent)
        self.radio.play.connect(self.play_radio)
        self.left_tabs.addTab(self.radio, "Radio")
        self.left_tabs.currentChanged.connect(lambda i: i == 2 and self.radio.ensure_loaded())
        self.left_tabs.currentChanged.connect(lambda i: self.settings.setValue("left_tab", i))
        self.library_panel = self.left_tabs
        self.current_dir = ""

        # --- Keskellä: video (pidetään aina näkyvissä, mpv piirtää siihen)
        self.video.setContextMenuPolicy(Qt.NoContextMenu)

        # --- Oikea paneeli: soittolista
        self.pl_view = QListWidget()
        self.pl_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.pl_view.itemDoubleClicked.connect(
            lambda it: self.video.cmd("playlist-play-index", self.pl_view.row(it)))
        self.pl_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pl_view.customContextMenuRequested.connect(self.playlist_menu)
        self.pl_title = self._panel_title("Soittolista")
        pl_box = QWidget()
        pll = QVBoxLayout(pl_box)
        pll.setContentsMargins(0, 0, 0, 0)
        pll.setSpacing(0)
        pll.addWidget(self.pl_title)
        pll.addWidget(self.pl_view)
        self.playlist_panel = pl_box

        self.split_main = QSplitter(Qt.Horizontal)
        self.split_main.setHandleWidth(3)
        self.split_main.addWidget(self.left_tabs)
        self.split_main.addWidget(self.video)
        self.split_main.addWidget(pl_box)
        self.split_main.setStretchFactor(1, 1)
        self.split_main.setSizes([280, 720, 280])

        # --- Ohjainpalkki: vain olennainen
        self.prev_btn = self._button("Edellinen (Ctrl+←)", self.prev)
        self.play_btn = self._button("Toista / tauko (välilyönti)", self.toggle_pause, "playButton")
        self.next_btn = self._button("Seuraava (Ctrl+→)", self.next)
        self.play_btn.setIconSize(QSize(22, 22))
        for b in (self.prev_btn, self.next_btn):
            b.setIconSize(QSize(20, 20))
        self.pos_label = QLabel("0:00")
        self.pos_label.setObjectName("timeLabel")
        self.dur_label = QLabel("0:00")
        self.dur_label.setObjectName("timeLabel")
        self.seek_slider = SeekSlider()
        self.seek_slider.setFocusPolicy(Qt.NoFocus)
        self.seek_slider.seek.connect(lambda s: self.video.cmd("seek", s, "absolute+exact"))
        self.seek_slider.hover.connect(self._seek_hover)
        self.seek_slider.hover_end.connect(self._seek_hover_end)
        self.seek_slider.valueChanged.connect(
            lambda v: self.seek_slider.dragging and self.pos_label.setText(fmt_time(v / 1000)))
        self.mute_btn = self._button("Mykistä (M)", lambda: self.video.cmd("cycle", "mute"))
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setFixedWidth(100)
        self.vol_slider.setFocusPolicy(Qt.NoFocus)
        self.vol_slider.setCursor(Qt.PointingHandCursor)
        self.vol_slider.setValue(self.settings.value("volume", 100, type=int))
        self.vol_slider.valueChanged.connect(lambda v: self.video.set("volume", float(v)))
        self.fs_btn = self._button("Koko näyttö (tuplaklikkaus / F)", self.toggle_fullscreen)
        for b in (self.mute_btn, self.fs_btn):
            b.setIconSize(QSize(20, 20))

        controls = QWidget()
        controls.setObjectName("controls")
        controls.setAttribute(Qt.WA_StyledBackground)
        cl = QHBoxLayout(controls)
        cl.setContentsMargins(10, 6, 10, 6)
        cl.setSpacing(4)
        for w in (self.prev_btn, self.play_btn, self.next_btn):
            cl.addWidget(w)
        cl.addSpacing(8)
        cl.addWidget(self.pos_label)
        cl.addWidget(self.seek_slider, 1)
        cl.addWidget(self.dur_label)
        cl.addSpacing(8)
        for w in (self.mute_btn, self.vol_slider, self.fs_btn):
            cl.addWidget(w)
        self.controls = controls

        central = QWidget()
        self.central_layout = QVBoxLayout(central)
        self.central_layout.setContentsMargins(0, 0, 0, 0)
        self.central_layout.setSpacing(0)
        self.central_layout.addWidget(self.split_main, 1)
        self.central_layout.addWidget(controls)
        self.setCentralWidget(central)

        # --- Tilarivi: tiedoston muoto ja bit-perfect-tila
        self.format_label = QLabel("")
        self.bp_label = QLabel("")
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addWidget(self.format_label, 1)
        self.statusBar().addPermanentWidget(self.bp_label)

    def _build_actions(self):
        """Kaikki toiminnot, joille voi asettaa pikanäppäimen (Asetukset → Pikanäppäimet)."""
        v = self.video
        slots = {
            "play_pause": self.toggle_pause, "stop": self.stop, "next": self.next, "prev": self.prev,
            "seek_fwd": lambda: self.seek_by(self.cfg.get("seek_short")),
            "seek_back": lambda: self.seek_by(-self.cfg.get("seek_short")),
            "seek_fwd_long": lambda: self.seek_by(self.cfg.get("seek_long")),
            "seek_back_long": lambda: self.seek_by(-self.cfg.get("seek_long")),
            "next_chapter": lambda: v.cmd("add", "chapter", 1),
            "prev_chapter": lambda: v.cmd("add", "chapter", -1),
            "frame_step": lambda: v.cmd("frame-step"),
            "frame_back": lambda: v.cmd("frame-back-step"),
            "speed_up": lambda: v.cmd("multiply", "speed", 1.1),
            "speed_down": lambda: v.cmd("multiply", "speed", 1 / 1.1),
            "speed_reset": lambda: v.set("speed", 1.0),
            "vol_up": lambda: v.cmd("add", "volume", self.cfg.get("volume_step")),
            "vol_down": lambda: v.cmd("add", "volume", -self.cfg.get("volume_step")),
            "mute": lambda: v.cmd("cycle", "mute"),
            "audio_cycle": lambda: (v.cmd("cycle", "audio"), self._toast_track("audio")),
            "sub_cycle": lambda: (v.cmd("cycle", "sub"), self._toast_track("sub")),
            "sub_toggle": lambda: v.cmd("cycle", "sub-visibility"),
            "screenshot": self.take_screenshot, "video_adjust": self.open_video_adjust,
            "aspect_cycle": self.cycle_aspect, "fill_toggle": self.toggle_fill,
            "deinterlace_toggle": self.toggle_deinterlace, "rotate": self.rotate_video,
            "library_search": self.focus_library_search,
            "remote": self.open_remote, "next_episode_now": self.next_episode_now,
            "fullscreen": self.toggle_fullscreen, "fullscreen_alt": self.toggle_fullscreen,
            "exit_fullscreen": lambda: self.fullscreen and self.toggle_fullscreen(),
            "toggle_library": lambda: self.lib_action.toggle(),
            "toggle_playlist": lambda: self.pl_action.toggle(),
            "video_only": self.video_only, "file_info": self.show_file_info,
            "open_files": self.open_files_dialog, "open_folder": self.open_folder_dialog,
            "remove_selected": self.remove_selected, "settings": self.open_settings,
            "quit": self.close,
        }
        self.act = {}
        for aid, label, _default, _group in ACTIONS:
            a = QAction(label, self)
            a.setShortcut(QKeySequence(self.cfg.key(aid)))
            a.setShortcutContext(Qt.WindowShortcut)
            a.triggered.connect(slots[aid])
            self.addAction(a)       # toimii myös kun valikkorivi on piilossa
            self.act[aid] = a
        self.update_seek_labels()

    def seek_by(self, sec):
        if self.state.get("idle-active", True):
            return
        self.video.cmd("seek", sec, "relative+exact")
        self.video.toast(f"{'+' if sec > 0 else '−'}{abs(sec)} s")

    def _toast_track(self, kind):
        def show():
            for t in self.state.get("track-list") or []:
                if t.get("type") == kind and t.get("selected"):
                    name = " ".join(x for x in (t.get("title") or "", f"[{t['lang']}]" if t.get("lang") else "") if x)
                    self.video.toast(f"{'Ääniraita' if kind == 'audio' else 'Tekstitys'}: {name or t.get('id')}")
                    return
            if kind == "sub":
                self.video.toast("Tekstitys: pois")
        QTimer.singleShot(250, show)

    def update_seek_labels(self):
        s, l = self.cfg.get("seek_short"), self.cfg.get("seek_long")
        self.act["seek_fwd"].setText(f"Kelaa eteen {s} s")
        self.act["seek_back"].setText(f"Kelaa taakse {s} s")
        self.act["seek_fwd_long"].setText(f"Kelaa eteen {l} s")
        self.act["seek_back_long"].setText(f"Kelaa taakse {l} s")

    def _build_menus(self):
        mb = self.menuBar()
        A = self.act

        # Tiedosto
        m = mb.addMenu("&Tiedosto")
        m.addAction(A["open_files"])
        m.addAction(A["open_folder"])
        self.disc_menu = m.addMenu("Toista levy (CD / DVD)")
        self.disc_menu.aboutToShow.connect(self.fill_disc_menu)
        m.addAction("Toista nykyinen kansio", lambda: self.play_folder(self.current_dir, True))
        m.addAction("Kopioi DVD kansioon…", self.copy_dvd)
        m.addSeparator()
        m.addAction(A["settings"])
        m.addSeparator()
        m.addAction(A["quit"])

        # Toisto
        m = mb.addMenu("T&oisto")
        for k in ("play_pause", "stop", "prev", "next"):
            m.addAction(A[k])
        m.addSeparator()
        for k in ("seek_fwd", "seek_back", "seek_fwd_long", "seek_back_long"):
            m.addAction(A[k])
        m.addSeparator()
        self.chapter_menu = m.addMenu("Kappale / luku")
        self.chapter_menu.setEnabled(False)
        speed = m.addMenu("Nopeus")
        for k in ("speed_up", "speed_down", "speed_reset"):
            speed.addAction(A[k])
        frame = m.addMenu("Ruutu kerrallaan")
        frame.addAction(A["frame_step"])
        frame.addAction(A["frame_back"])

        # Kuva
        m = mb.addMenu("&Kuva")
        m.addAction(A["video_adjust"])
        m.addAction("Tarkennus vanhoille videoille…", lambda: self.open_video_adjust(1))
        m.addAction("HDR-säädöt…", lambda: self.open_video_adjust(2))
        asp = m.addMenu("Kuvasuhde")
        self.aspect_group = QActionGroup(self)
        for value, label in ASPECTS:
            a = asp.addAction(label)
            a.setCheckable(True)
            a.setData(value)
            a.setChecked(value == "-1")
            a.triggered.connect(lambda _=False, v=value, l=label: self.set_aspect(v, l))
            self.aspect_group.addAction(a)
        asp.addSeparator()
        asp.addAction(A["aspect_cycle"])
        self.fill_action = A["fill_toggle"]
        self.fill_action.setCheckable(True)
        self.fill_action.triggered.disconnect()
        self.fill_action.toggled.connect(self.toggle_fill)
        m.addAction(self.fill_action)
        m.addAction(A["rotate"])
        deint = m.addMenu("Lomituksen poisto")
        self.deint_group = QActionGroup(self)
        for value, label in (("auto", "Automaattinen (suositus)"), ("yes", "Aina päällä"), ("no", "Pois")):
            a = deint.addAction(label)
            a.setCheckable(True)
            a.setData(value)
            a.setChecked(value == "auto")
            a.triggered.connect(lambda _=False, v=value: self.set_deinterlace(v))
            self.deint_group.addAction(a)
        deint.addSeparator()
        deint.addAction(A["deinterlace_toggle"])
        m.addSeparator()
        m.addAction(A["screenshot"])
        m.addAction("Avaa kuvakaappauskansio", self.open_screenshot_folder)

        # Soittolista
        m = mb.addMenu("&Soittolista")
        m.addAction("Lisää tiedostoja…", self.open_files_dialog)
        m.addAction("Lisää kansio…", self.open_folder_dialog)
        m.addSeparator()
        m.addAction("Siirrä valitut ylös", QKeySequence("Alt+Up"), lambda: self.move_selected(-1))
        m.addAction("Siirrä valitut alas", QKeySequence("Alt+Down"), lambda: self.move_selected(1))
        m.addAction(A["remove_selected"])
        m.addSeparator()
        m.addAction("Sekoita", lambda: self.video.cmd("playlist-shuffle"))
        m.addAction("Järjestä aakkosjärjestykseen", self.sort_playlist)
        rep = m.addMenu("Toisto")
        self.repeat_group = QActionGroup(self)
        self.repeat_actions = {}
        for key, text in (("off", "Ei toistoa"), ("all", "Toista koko lista"), ("one", "Toista kappale")):
            a = rep.addAction(text)
            a.setCheckable(True)
            a.triggered.connect(lambda _=False, k=key: self.set_repeat(k))
            self.repeat_group.addAction(a)
            self.repeat_actions[key] = a
        self.repeat_actions["off"].setChecked(True)
        m.addSeparator()
        m.addAction("Tyhjennä", self.clear_playlist)

        # Ääni
        m = mb.addMenu("Ää&ni")
        self.excl_action = QAction("Bit-perfect (WASAPI exclusive)", self, checkable=True)
        self.excl_action.setChecked(self.cfg.get("exclusive"))
        self.excl_action.toggled.connect(self.set_exclusive)
        self.excl_action.setEnabled(IS_WIN)
        m.addAction(self.excl_action)
        self.device_menu = m.addMenu("Äänilaite")
        self.device_menu.aboutToShow.connect(self.fill_device_menu)
        self.audio_menu = m.addMenu("Ääniraita")
        m.addSeparator()
        for k in ("mute", "vol_up", "vol_down"):
            m.addAction(A[k])

        # Tekstitys
        m = mb.addMenu("Te&kstitys")
        self.sub_menu = m.addMenu("Valitse tekstitys")
        m.addAction(A["sub_toggle"])
        m.addAction(A["sub_cycle"])
        m.addAction("Lataa tekstitystiedosto…", self.load_subtitle)
        m.addAction("Tekstitysten ulkoasu…", self.open_sub_style)
        m.addSeparator()
        m.addAction("Suurempi teksti", lambda: self.video.cmd("add", "sub-scale", 0.1))
        m.addAction("Pienempi teksti", lambda: self.video.cmd("add", "sub-scale", -0.1))

        # Näytä
        m = mb.addMenu("&Näytä")
        self.lib_action = m.addAction("Lähteet ja tiedostot")
        self.lib_action.setCheckable(True)
        self.lib_action.setChecked(self.settings.value("show_library", True, type=bool))
        self.lib_action.toggled.connect(lambda on: self._toggle_panel(self.library_panel, "show_library", on))
        self.pl_action = m.addAction("Soittolista")
        self.pl_action.setCheckable(True)
        self.pl_action.setChecked(self.settings.value("show_playlist", True, type=bool))
        self.pl_action.toggled.connect(lambda on: self._toggle_panel(self.playlist_panel, "show_playlist", on))
        self.status_action = m.addAction("Tilarivi (muoto ja bit-perfect)")
        self.status_action.setCheckable(True)
        self.status_action.setChecked(self.settings.value("show_status", True, type=bool))
        self.status_action.toggled.connect(lambda on: self._toggle_panel(self.statusBar(), "show_status", on))
        m.addAction(A["video_only"])
        m.addAction(A["library_search"])
        m.addAction(A["remote"])
        m.addSeparator()
        m.addAction(A["fullscreen"])
        self.show_all_action = QAction("Näytä kaikki tiedostot (myös tuntemattomat)", self, checkable=True)
        self.show_all_action.setChecked(self.settings.value("show_all", False, type=bool))
        self.show_all_action.toggled.connect(self.set_show_all)
        m.addAction(self.show_all_action)
        self.set_show_all(self.show_all_action.isChecked())
        m.addAction(A["file_info"])

        # Ohje
        m = mb.addMenu("&Ohje")
        m.addAction("Pikanäppäimet…", self.show_help)
        m.addAction("Tarkista päivitykset…", lambda: self.check_updates(silent=False))
        m.addAction("Avaa virheloki", self.open_error_log)
        m.addAction("Tietoja", self.about)

    def _build_fullscreen(self):
        # Yläpalkki: valikko + nimi + poistu. Palkit ovat videon päällä (lapsi-widgetit).
        self.top_ov = Overlay(self.video)
        self.ov_title = QLabel("")
        self.ov_title.setObjectName("ovTitle")
        self.ov_menu_btn = self._button("Valikko", self.show_main_menu)
        self.ov_exit_btn = self._button("Poistu koko näytöstä (Esc)", self.toggle_fullscreen)
        for b in (self.ov_menu_btn, self.ov_exit_btn):
            b.setIconSize(QSize(22, 22))
        self.top_ov.lay.addWidget(self.ov_menu_btn)
        self.top_ov.lay.addWidget(self.ov_title, 1)
        self.top_ov.lay.addWidget(self.ov_exit_btn)
        # Alapalkki: ohjaimet siirretään tähän koko näytön ajaksi
        self.bottom_ov = Overlay(self.video)
        self.bottom_ov.lay.setContentsMargins(0, 0, 0, 0)
        self.video.installEventFilter(self)

        self.hide_timer = QTimer(self, singleShot=True, interval=int(self.cfg.get("hide_delay") * 1000),
                                 timeout=self._maybe_hide_overlays)
        self.mouse_timer = QTimer(self, interval=150, timeout=self._poll_mouse)

    def eventFilter(self, obj, e):
        if obj is self.video and e.type() == QEvent.Resize:
            if self.fullscreen:
                self._place_overlays()
            self._place_next_card()
        return super().eventFilter(obj, e)

    # ============================================================ Teema
    # ========================================================= Kirjasto
    def _build_library_panel(self):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        self.lib_search = QLineEdit()
        self.lib_search.setPlaceholderText("Hae artistia, albumia tai kappaletta…")
        self.lib_search.setClearButtonEnabled(True)
        self.lib_search.textChanged.connect(lambda _: self.lib_filter_timer.start())
        self.lib_genre = QComboBox()
        self.lib_genre.addItem("Kaikki tyylilajit", "")
        self.lib_genre.currentIndexChanged.connect(lambda _: self.rebuild_library())
        self.lib_filter_timer = QTimer(self, singleShot=True, interval=200, timeout=self.rebuild_library)
        self.lib_tree = QTreeWidget()
        self.lib_tree.setHeaderHidden(True)
        self.lib_tree.setIndentation(14)
        self.lib_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.lib_tree.itemDoubleClicked.connect(self._lib_double)
        self.lib_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lib_tree.customContextMenuRequested.connect(self._lib_menu)
        self.lib_status = QLabel("")
        self.lib_status.setObjectName("pathLabel")
        self.lib_status.setWordWrap(True)
        add = self._button("Lisää kansio kirjastoon", self.library_add_folder)
        add.setText("+ Kansio")
        add.setToolButtonStyle(Qt.ToolButtonTextOnly)
        upd = self._button("Päivitä kirjasto (etsi uudet ja muuttuneet tiedostot)", self.library_scan)
        upd.setText("Päivitä")
        upd.setToolButtonStyle(Qt.ToolButtonTextOnly)
        folders = self._button("Kirjaston kansiot", lambda: None)
        folders.setText("Kansiot ▾")
        folders.setToolButtonStyle(Qt.ToolButtonTextOnly)
        folders.setPopupMode(QToolButton.InstantPopup)
        self.lib_folder_menu = QMenu(folders)
        self.lib_folder_menu.aboutToShow.connect(self._fill_lib_folders)
        folders.setMenu(self.lib_folder_menu)
        row = QHBoxLayout()
        row.setContentsMargins(4, 0, 4, 0)
        for w in (add, upd, folders):
            row.addWidget(w)
        row.addStretch()
        for w in (self.lib_search, self.lib_genre):
            lay.addWidget(w)
        lay.addWidget(self.lib_tree, 1)
        lay.addWidget(self.lib_status)
        lay.addLayout(row)
        return box

    def library_folders(self):
        return [f for f in (self.settings.value("library/folders", [], type=list) or []) if f]

    def library_add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Lisää kansio kirjastoon",
                                             QStandardPaths.writableLocation(QStandardPaths.MusicLocation))
        if d:
            folders = self.library_folders()
            if d not in folders:
                folders.append(d)
                self.settings.setValue("library/folders", folders)
            self.library_scan()

    def _fill_lib_folders(self):
        m = self.lib_folder_menu
        m.clear()
        folders = self.library_folders()
        if not folders:
            m.addAction("Ei kansioita – lisää kansio + Kansio -painikkeella").setEnabled(False)
        for f in folders:
            sub = m.addMenu(f)
            sub.addAction("Poista kirjastosta", lambda f=f: self._remove_lib_folder(f))
        m.addSeparator()
        m.addAction("Lisää kansio…", self.library_add_folder)

    def _remove_lib_folder(self, folder):
        folders = [f for f in self.library_folders() if f != folder]
        self.settings.setValue("library/folders", folders)
        self.library_scan()

    def library_scan(self):
        folders = self.library_folders()
        if self.scanner and self.scanner.isRunning():
            return
        if not folders:
            self.library_tracks = {}
            library.save_cache({})
            self.rebuild_library()
            return
        self.lib_status.setText("Päivitetään kirjastoa…")
        self.scanner = library.LibraryScanner(folders, self)
        self.scanner.progress.connect(lambda n, d: self.lib_status.setText(f"Luetaan… {n} kappaletta"))
        self.scanner.finished_scan.connect(self._scan_done)
        self.scanner.start()

    def _scan_done(self, tracks):
        self.library_tracks = tracks
        self.rebuild_library()

    def rebuild_library(self):
        tracks = self.library_tracks or {}
        genres = sorted({t.get("genre") for t in tracks.values() if t.get("genre")}, key=str.lower)
        cur_genre = self.lib_genre.currentData()
        self.lib_genre.blockSignals(True)
        self.lib_genre.clear()
        self.lib_genre.addItem("Kaikki tyylilajit", "")
        for g in genres:
            self.lib_genre.addItem(g, g)
        idx = self.lib_genre.findData(cur_genre)
        self.lib_genre.setCurrentIndex(max(0, idx))
        self.lib_genre.blockSignals(False)
        genre = self.lib_genre.currentData() or ""
        q = self.lib_search.text().strip().lower()
        sel = {t["path"]: t for t in tracks.values()
               if (not genre or t.get("genre") == genre)
               and (not q or q in " ".join(str(t.get(k, "")) for k in
                                           ("title", "artist", "album", "albumartist")).lower())}
        tree = library.group_library(sel)
        self.lib_tree.clear()
        bold = self.lib_tree.font()
        bold.setBold(True)
        for artist in sorted(tree, key=str.lower):
            a_item = QTreeWidgetItem(self.lib_tree, [artist])
            a_item.setFont(0, bold)
            albums = tree[artist]
            paths = []
            for album in sorted(albums, key=lambda al: (albums[al][0].get("year") or "", al.lower())):
                lst = albums[album]
                year = lst[0].get("year")
                al_item = QTreeWidgetItem(a_item, [f"{album}  ({year})" if year else album])
                al_item.setForeground(0, QColor(self.accent))
                al_paths = [t["path"] for t in lst]
                al_item.setData(0, Qt.UserRole, al_paths)
                paths += al_paths
                for t in lst:
                    n = t.get("track")
                    it = QTreeWidgetItem(al_item, [f"{n:>2}. {t['title']}" if n else t["title"]])
                    it.setData(0, Qt.UserRole, [t["path"]])
                    it.setToolTip(0, t["path"])
            a_item.setData(0, Qt.UserRole, paths)
            if q:
                a_item.setExpanded(True)
        n_alb = sum(len(v) for v in tree.values())
        if not tracks:
            self.lib_status.setText("Kirjasto on tyhjä. Lisää musiikkikansio + Kansio -painikkeella.")
        else:
            self.lib_status.setText(f"{len(tree)} artistia · {n_alb} albumia · {len(sel)} kappaletta")

    def _lib_paths(self, item):
        return item.data(0, Qt.UserRole) or []

    def _lib_double(self, item, _col=0):
        paths = self._lib_paths(item)
        if not paths:
            return
        if len(paths) == 1 and item.parent() is not None:
            # kappale: toista albumi tästä kappaleesta alkaen
            album_paths = self._lib_paths(item.parent())
            self.add_paths(album_paths, replace=True)
            self.video.cmd("playlist-play-index", album_paths.index(paths[0]))
        else:
            item.setExpanded(not item.isExpanded())

    def _lib_menu(self, pos):
        items = self.lib_tree.selectedItems()
        paths = [p for it in items for p in self._lib_paths(it)]
        if not paths:
            return
        menu = QMenu(self)
        menu.addAction("Toista", lambda: self.add_paths(paths, replace=True))
        menu.addAction("Lisää soittolistaan", lambda: self.add_paths(paths))
        menu.addAction("Näytä kansiossa", lambda: self.browse(str(Path(paths[0]).parent)) or self.left_tabs.setCurrentIndex(0))
        menu.exec(self.lib_tree.viewport().mapToGlobal(pos))

    def focus_library_search(self):
        if not self.library_panel.isVisible():
            self.lib_action.setChecked(True)
        self.left_tabs.setCurrentIndex(1)
        self.lib_search.setFocus()
        self.lib_search.selectAll()

    # ========================================================= Kuva
    def open_video_adjust(self, tab=0):
        if self.adjust_dialog is None:
            self.adjust_dialog = videoadjust.VideoAdjustDialog(self.video, self.settings, self.update_shaders, self)
        self.adjust_dialog.tabs.setCurrentIndex(tab)
        self.adjust_dialog.show()
        self.adjust_dialog.raise_()

    def update_shaders(self):
        """Tarkennussävyttimet päälle vain videoille, jotka hyötyvät niistä (esim. DVD/SD)."""
        vp = self.state.get("video-params") if self.is_real_video() else None
        want = videoadjust.wanted_shaders(self.settings, vp)
        if want == self._shaders:
            return
        self._shaders = want
        self.video.cmd("change-list", "glsl-shaders", "clr", "")
        for path in want:
            self.video.cmd("change-list", "glsl-shaders", "append", path)
        self.update_audio_info()

    def open_sub_style(self):
        if self.sub_dialog is None:
            self.sub_dialog = subtitles.SubStyleDialog(self.video, self.settings, self)
        self.sub_dialog.show()
        self.sub_dialog.raise_()

    def set_aspect(self, value, label=None):
        self.video.set("video-aspect-override", value)
        for a in self.aspect_group.actions():
            a.setChecked(a.data() == value)
        self.video.toast(f"Kuvasuhde: {label or dict(ASPECTS).get(value, value)}")

    def cycle_aspect(self):
        cur = next((a.data() for a in self.aspect_group.actions() if a.isChecked()), "-1")
        keys = [k for k, _ in ASPECTS]
        nxt = keys[(keys.index(cur) + 1) % len(keys)] if cur in keys else keys[0]
        self.set_aspect(nxt)

    def toggle_fill(self, on=None):
        if on is None:
            on = not self.fill_action.isChecked()
        self.fill_action.blockSignals(True)
        self.fill_action.setChecked(on)
        self.fill_action.blockSignals(False)
        self.video.set("panscan", 1.0 if on else 0.0)
        self.video.toast("Täytä ruutu: päällä" if on else "Täytä ruutu: pois")

    def set_deinterlace(self, mode):
        self.video.set("deinterlace", mode)
        for a in self.deint_group.actions():
            a.setChecked(a.data() == mode)
        self.video.toast({"auto": "Lomituksen poisto: automaattinen", "yes": "Lomituksen poisto: päällä",
                          "no": "Lomituksen poisto: pois"}[mode])

    def toggle_deinterlace(self):
        cur = next((a.data() for a in self.deint_group.actions() if a.isChecked()), "auto")
        self.set_deinterlace("no" if cur == "yes" else "yes")

    def rotate_video(self):
        cur = int(self.video.get("video-rotate", 0) or 0)
        new = (cur + 90) % 360
        self.video.set("video-rotate", new)
        self.video.toast(f"Kierto: {new}°")

    def take_screenshot(self):
        if not self.is_real_video():
            self.video.toast("Kuvakaappaus toimii videoille")
            return
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.video.cmd("screenshot", "subtitles")
        self.video.toast(f"Kuvakaappaus tallennettu: {self.screenshot_dir.name}-kansioon")

    def open_screenshot_folder(self):
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.screenshot_dir)))

    # ========================================================= DVD-kopio
    def copy_dvd(self, drive=None):
        if drive is None:
            dvds = [d for d in list_drives() if d.disc == "dvd"]
            if not dvds:
                QMessageBox.information(self, "Kopioi DVD", "Asemassa ei ole DVD-levyä.")
                return
            drive = dvds[0]
        size_mb = disc_size(drive.root) // 2**20
        dest_parent = QFileDialog.getExistingDirectory(
            self, f"Minne DVD kopioidaan? ({size_mb} Mt)",
            QStandardPaths.writableLocation(QStandardPaths.MoviesLocation))
        if not dest_parent:
            return
        dest = unique_folder(dest_parent, safe_name(drive.label))
        dlg = QProgressDialog("Kopioidaan DVD:tä…", "Peruuta", 0, max(1, size_mb), self)
        dlg.setWindowTitle("Kopioi DVD")
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        w = DvdCopyWorker(drive.root, dest, self)
        self.dvd_worker = w
        w.progress.connect(lambda c, t, f: (dlg.setMaximum(max(1, t)), dlg.setValue(c),
                                            dlg.setLabelText(f"Kopioidaan {f}…  {c} / {t} Mt")))
        dlg.canceled.connect(w.abort)

        def done(path):
            dlg.close()
            box = QMessageBox(self)
            box.setWindowTitle("Kopioi DVD")
            box.setText(f"DVD kopioitu kansioon:\n{path}\n\nVoit toistaa sen tuplaklikkaamalla "
                        "kansiota tiedostoselaimessa.")
            box.addButton("OK", QMessageBox.AcceptRole)
            opn = box.addButton("Avaa kansio", QMessageBox.ActionRole)
            box.exec()
            if box.clickedButton() is opn:
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))

        def failed(msg):
            dlg.close()
            QMessageBox.warning(self, "Kopioi DVD", msg)

        w.done.connect(done)
        w.failed.connect(failed)
        w.start()

    # ========================================================= Aikajana
    def _seek_hover(self, t, gpos):
        self.preview.show_at(fmt_time(t), gpos)
        path = self.state.get("path") or ""
        if (self.cfg.get("seek_preview") and self.is_real_video() and "://" not in path
                and Path(path).suffix.lower() != ".iso"):
            self._hover = (path, t)
            self.thumb_timer.start()
        else:
            self.preview.set_image(None)

    def _seek_hover_end(self):
        self._hover = None
        self.thumb_timer.stop()
        self.preview.hide()

    def _request_thumb(self):
        if self._hover:
            self.thumbs.request(*self._hover)

    def _thumb_ready(self, t, img):
        if self._hover and self.preview.isVisible():
            self.preview.set_image(img)
            self.preview.adjustSize()

    # ========================================================= Seuraava jakso
    def _build_next_card(self):
        self.next_card = NextCard(self.video)
        self.next_card.play_now.connect(self.next_episode_now)
        self.next_card.cancel.connect(self._cancel_next)

    def _place_next_card(self):
        c = self.next_card
        c.adjustSize()
        bottom = 24
        if self.fullscreen and self.bottom_ov.shown():
            bottom += self.bottom_ov.height()
        c.move(self.video.width() - c.width() - 24, self.video.height() - c.height() - bottom)

    def _next_entry(self):
        pos = self.state.get("playlist-pos")
        if pos is None or pos < 0 or pos + 1 >= len(self.playlist):
            return None
        if self.state.get("loop-file") not in (False, None, "no"):
            return None
        return self.playlist[pos + 1]

    def _check_next_card(self, t):
        if (not self.cfg.get("auto_next") or self._next_state != "idle" or t is None
                or not self.is_real_video()):
            return
        dur = self.state.get("duration") or 0
        if dur < 120:      # lyhyet videot ohitetaan
            return
        nxt = self._next_entry()
        if nxt is None:
            return
        if dur - t <= self.cfg.get("next_offer"):
            self._next_state = "counting"
            self._next_left = self.cfg.get("next_countdown")
            self.next_card.name.setText(self.entry_name(nxt))
            self._update_next_label()
            self._place_next_card()
            self.next_card.show()
            self.next_card.raise_()
            self.next_timer.start()

    def _update_next_label(self):
        self.next_card.count.setText(f"Alkaa {self._next_left} sekunnin kuluttua"
                                     if not self.state.get("pause") else "Tauolla")

    def _next_tick(self):
        if self._next_state != "counting":
            self.next_timer.stop()
            return
        if self.state.get("pause"):
            self._update_next_label()
            return
        self._next_left -= 1
        if self._next_left <= 0:
            self.next_episode_now()
        else:
            self._update_next_label()

    def next_episode_now(self):
        if self._next_entry() is None:
            return
        self._hide_next_card("idle")
        self.video.cmd("playlist-next")

    def _cancel_next(self):
        self._hide_next_card("dismissed")
        self.video.set("keep-open", "yes")    # jäädään jakson loppuun
        self.video.toast("Seuraava jakso peruttu")

    def _hide_next_card(self, state):
        self._next_state = state
        self.next_timer.stop()
        self.next_card.hide()

    # ========================================================= Netradio
    def play_radio(self, url, name):
        self.radio_names[url] = name
        self.save_position()
        self.video.cmd("loadfile", url, "replace")
        self.video.set("pause", False)
        self.video.toast(f"Netradio: {name}")

    # ========================================================= Kaukosäädin
    def open_remote(self):
        if self.remote_dialog is None:
            self.remote_dialog = RemoteDialog(self.remote, self.cfg, self)
            self.remote_dialog.enable.toggled.connect(
                lambda on: self.remote_timer.start() if self.remote.running else self.remote_timer.stop())
        self.remote_dialog._refresh()
        self.remote_dialog.show()
        self.remote_dialog.raise_()

    def update_remote_state(self):
        idle = self.state.get("idle-active", True)
        title = self.windowTitle().replace(" – Mediasoitin", "") if not idle else ""
        artist = ""
        if not idle and self.video.album:
            title = self.video.album.get("title") or title
            artist = self.video.album.get("artist") or ""
        cover_id = ""
        key = self._cover_bytes
        if not idle and key and not self.is_real_video():
            if not self.remote.cover or self.remote.cover[2] != key:
                data = library.find_cover(key)
                self.remote.cover = ("image/jpeg" if data and data[:3] == b"\xff\xd8\xff" else "image/png",
                                     data, key) if data else None
            cover_id = str(abs(hash(key)) % 10**8) if self.remote.cover else ""
        names = [self.entry_name(e, i) for i, e in enumerate(self.playlist[:300])]
        self.remote.state = {
            "title": title or ("Ei toistoa" if idle else ""), "artist": artist,
            "pos": self.state.get("time-pos") or 0, "dur": self.state.get("duration") or 0,
            "paused": bool(self.state.get("pause")) or idle,
            "volume": self.state.get("volume") if self.state.get("volume") is not None else self.vol_slider.value(),
            "mute": bool(self.state.get("mute")), "playlist": names,
            "current": self.state.get("playlist-pos") if self.state.get("playlist-pos") is not None else -1,
            "cover_id": cover_id, "video": self.is_real_video(), "accent": self.accent,
            "radio": [f["name"] for f in self.radio.favorites()],
            "has_next_episode": self.is_real_video() and self._next_entry() is not None,
        }

    def on_remote_command(self, cmd, value):
        v = self.video
        try:
            if cmd == "toggle":
                self.toggle_pause()
            elif cmd == "play":
                if self.state.get("pause") or self.state.get("idle-active", True):
                    self.toggle_pause()
            elif cmd == "pause":
                v.set("pause", True)
            elif cmd == "volume_rel":
                v.cmd("add", "volume", float(value or 0))
            elif cmd == "next":
                self.next()
            elif cmd == "prev":
                self.prev()
            elif cmd == "stop":
                self.stop()
            elif cmd == "seek":
                self.seek_by(int(value or 0))
            elif cmd == "seek_abs":
                v.cmd("seek", float(value or 0), "absolute+exact")
            elif cmd == "volume":
                v.set("volume", max(0, min(100, float(value or 0))))
            elif cmd == "mute":
                v.cmd("cycle", "mute")
            elif cmd == "fullscreen":
                self.toggle_fullscreen()
            elif cmd == "play_index":
                v.cmd("playlist-play-index", int(value))
                v.set("pause", False)
            elif cmd == "play_radio":
                fav = self.radio.favorites()[int(value)]
                self.play_radio(fav["url"], fav["name"])
            elif cmd == "next_episode":
                self.next_episode_now()
            elif cmd == "mouse_move":
                inputsim.move(int(value[0]), int(value[1]))
                return
            elif cmd == "mouse_click":
                inputsim.click("right" if value == "right" else "left")
            elif cmd == "mouse_scroll":
                inputsim.scroll(int(value))
                return
            elif cmd == "key":
                inputsim.key(str(value))
            elif cmd == "type":
                inputsim.type_text(str(value))
        except (TypeError, ValueError, IndexError, KeyError):
            pass
        QTimer.singleShot(100, self.update_remote_state)

    def _show_pair_code(self, code, device):
        if self.pair_dialog:
            self.pair_dialog.close()
        self.pair_dialog = PairCodeDialog(code, device, self)
        self.pair_dialog.show()
        self.pair_dialog.raise_()
        self.pair_dialog.activateWindow()

    def _pair_done(self, ok, device):
        if self.pair_dialog:
            self.pair_dialog.close()
            self.pair_dialog = None
        if ok:
            self.video.toast(f"Laitepari muodostettu: {device}", 3000)

    # ========================================================= Päivitykset
    def check_updates(self, silent=True):
        if self.update_checker and self.update_checker.isRunning():
            return
        self.update_checker = updater.UpdateChecker(self)
        self.update_checker.result.connect(lambda r: self._update_result(r, silent))
        self.update_checker.start()

    def _update_result(self, r, silent):
        if r.get("error"):
            if not silent:
                QMessageBox.information(self, "Päivitykset", "Päivitysten tarkistus ei onnistunut.\n"
                                        "Tarkista nettiyhteys.\n\n" + r["error"][:200])
            return
        ver = r.get("version", "")
        if not updater.is_newer(ver):
            if not silent:
                QMessageBox.information(self, "Päivitykset", f"Käytössä on uusin versio ({__version__}).")
            return
        if silent and self.settings.value("update/skip", "", type=str) == ver:
            return
        notes = (r.get("notes") or "").strip()
        box = QMessageBox(self)
        box.setWindowTitle("Päivitys saatavilla")
        box.setText(f"<b>Mediasoitin {ver.lstrip('v')} on saatavilla</b> (käytössä {__version__}).")
        if notes:
            box.setInformativeText(notes[:600])
        upd = box.addButton("Päivitä nyt", QMessageBox.AcceptRole)
        box.addButton("Myöhemmin", QMessageBox.RejectRole)
        skip = box.addButton("Ohita tämä versio", QMessageBox.DestructiveRole)
        box.setDefaultButton(upd)
        box.exec()
        if box.clickedButton() is skip:
            self.settings.setValue("update/skip", ver)
            return
        if box.clickedButton() is not upd:
            return
        if not updater.can_self_update() or not r.get("url"):
            QDesktopServices.openUrl(QUrl(r.get("page")))
            return
        if not updater.dir_writable():
            QMessageBox.warning(self, "Päivitys", "Soittimen kansioon ei voi kirjoittaa "
                                f"({updater.app_dir()}).\nSiirrä soitin esimerkiksi kansioon C:\\Ohjelmat\\Mediasoitin "
                                "tai lataa päivitys käsin.")
            QDesktopServices.openUrl(QUrl(r.get("page")))
            return
        self._download_update(r)

    def _download_update(self, r):
        size = max(1, (r.get("size") or 0) // 2**20)
        dlg = QProgressDialog("Ladataan päivitystä…", "Peruuta", 0, size, self)
        dlg.setWindowTitle("Päivitys")
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        d = updater.UpdateDownloader(r["url"], self)
        self.update_dl = d
        d.progress.connect(lambda c, t: (dlg.setMaximum(t), dlg.setValue(c),
                                         dlg.setLabelText(f"Ladataan päivitystä…  {c} / {t} Mt")))
        dlg.canceled.connect(d.abort)

        def ready(path):
            dlg.setLabelText("Asennetaan… soitin käynnistyy hetken kuluttua uudelleen.")
            QApplication.processEvents()
            if updater.install_and_restart(path):
                QTimer.singleShot(300, self.close)

        def failed(msg):
            dlg.close()
            QMessageBox.warning(self, "Päivitys", msg)

        d.ready.connect(ready)
        d.failed.connect(failed)
        d.start()

    def refresh_icons(self):
        a, t = self.accent, theme.TEXT
        ico = ASSETS / "icon.png"
        self.setWindowIcon(QIcon(str(ico)) if ico.exists() else icon("app", a, 64))
        self.prev_btn.setIcon(icon("prev", t))
        self.next_btn.setIcon(icon("next", t))
        paused = self.state.get("pause") or self.state.get("idle-active", True)
        self.play_btn.setIcon(icon("play" if paused else "pause", "#FFFFFF"))
        self.mute_btn.setIcon(icon("mute" if self.state.get("mute") else "volume", t))
        self.fs_btn.setIcon(icon("exit_fullscreen" if self.fullscreen else "fullscreen", t))
        self.up_btn.setIcon(icon("up", theme.MUTED))
        self.ov_menu_btn.setIcon(icon("menu", t))
        self.ov_exit_btn.setIcon(icon("close", t))

    def set_accent(self, color):
        self.accent = QColor(color).name()
        self.cfg.set("accent", self.accent)
        self.video.accent = QColor(self.accent)
        theme.apply(QApplication.instance(), self.accent)
        self.refresh_icons()
        self.rebuild_playlist()
        self.radio.accent = self.accent
        self.radio.rebuild()
        self._drive_sig = None
        self.refresh_drives()
        if self.state.get("idle-active", True):
            self.show_idle()
        else:
            self.update_now_playing()

    def _toggle_panel(self, widget, key, on):
        widget.setVisible(on)
        self.settings.setValue(key, on)

    def video_only(self):
        self.lib_action.setChecked(False)
        self.pl_action.setChecked(False)

    # ============================================================ Asemat
    def refresh_drives(self):
        drives = list_drives()
        sig = tuple((d.root, d.label, d.ready, d.disc) for d in drives)
        if sig == self._drive_sig:
            return
        self._drive_sig = sig
        self.drive_tree.clear()
        st = self.style()
        for d in drives:
            ic = {OPTICAL: QStyle.SP_DriveCDIcon, REMOVABLE: QStyle.SP_DriveFDIcon,
                  NETWORK: QStyle.SP_DriveNetIcon}.get(d.kind, QStyle.SP_DriveHDIcon)
            it = QTreeWidgetItem(self.drive_tree, [d.title])
            it.setIcon(0, st.standardIcon(ic))
            it.setData(0, Qt.UserRole, d)
            if d.disc:
                it.setToolTip(0, "Tuplaklikkaa toistaaksesi levyn")
                it.setForeground(0, QColor(self.accent))
        for name, path in quick_locations():
            it = QTreeWidgetItem(self.drive_tree, [name])
            it.setIcon(0, st.standardIcon(QStyle.SP_DirIcon))
            it.setData(0, Qt.UserRole, path)

    def on_drive_clicked(self, item, _col=0):
        d = item.data(0, Qt.UserRole)
        if isinstance(d, str):
            self.browse(d)
        elif d is not None and d.ready:
            self.browse(d.root)

    def on_drive_double(self, item, _col=0):
        d = item.data(0, Qt.UserRole)
        if d is not None and not isinstance(d, str) and d.disc:
            self.play_disc(d)

    def drive_menu(self, pos):
        item = self.drive_tree.itemAt(pos)
        d = item.data(0, Qt.UserRole) if item else None
        if d is None:
            return
        menu = QMenu(self)
        if not isinstance(d, str) and d.disc:
            menu.addAction("Toista levy", lambda: self.play_disc(d))
            if d.disc == "dvd":
                menu.addAction("Kopioi DVD kansioon…", lambda: self.copy_dvd(d))
        path = d if isinstance(d, str) else d.root
        menu.addAction("Toista kaikki (myös alikansiot)", lambda: self.play_folder(path, True))
        menu.addAction("Lisää kaikki soittolistaan", lambda: self.add_folder(path, True))
        menu.exec(self.drive_tree.viewport().mapToGlobal(pos))

    def fill_disc_menu(self):
        self.disc_menu.clear()
        discs = [d for d in list_drives() if d.disc]
        if not discs:
            self.disc_menu.addAction("Ei levyä asemassa").setEnabled(False)
        for d in discs:
            self.disc_menu.addAction(d.title, lambda d=d: self.play_disc(d))

    def play_disc(self, d):
        if d.disc == "audio-cd":
            self.play_cd(d.device)
        elif d.disc == "dvd":
            self.video.set("dvd-device", d.root)
            self.video.cmd("loadfile", "dvd://", "replace")
        elif d.disc == "bluray":
            self.video.set("bluray-device", d.root)
            self.video.cmd("loadfile", "bd://", "replace")

    # ==================================================== Tiedostoselain
    def browse(self, path):
        path = str(path)
        self.current_dir = path
        self.file_view.setRootIndex(self.fs_model.index(path))
        self.path_label.setText(path)
        self.path_label.setToolTip(path)
        self.settings.setValue("last_dir", path)

    def browse_up(self):
        if self.current_dir:
            parent = Path(self.current_dir).parent
            if str(parent) != self.current_dir:
                self.browse(parent)

    def set_show_all(self, on):
        self.fs_model.setNameFilters([] if on else NAME_FILTERS)
        self.settings.setValue("show_all", on)

    def selected_paths(self):
        return [self.fs_model.filePath(i) for i in self.file_view.selectionModel().selectedRows(0)]

    def on_file_double(self, index):
        path = self.fs_model.filePath(index)
        if self.fs_model.isDir(index):
            p = Path(path)
            if (p / "VIDEO_TS").is_dir() or p.name.upper() == "VIDEO_TS":
                root = str(p.parent) if p.name.upper() == "VIDEO_TS" else path
                self.video.set("dvd-device", root)
                self.video.cmd("loadfile", "dvd://", "replace")
            else:
                self.browse(path)
        else:
            self.play_file_in_context(path)

    def file_menu(self, pos):
        idx = self.file_view.indexAt(pos)
        paths = self.selected_paths()
        menu = QMenu(self)
        if paths:
            menu.addAction("Toista", lambda: self.add_paths(paths, play=True, replace=True))
            menu.addAction("Lisää soittolistaan", lambda: self.add_paths(paths))
            menu.addSeparator()
        folder = self.fs_model.filePath(idx) if idx.isValid() and self.fs_model.isDir(idx) else self.current_dir
        if folder:
            menu.addAction("Toista kansio (myös alikansiot)", lambda: self.play_folder(folder, True))
            menu.addAction("Lisää kansio soittolistaan", lambda: self.add_folder(folder, True))
        menu.exec(self.file_view.viewport().mapToGlobal(pos))

    # ============================================================ Toisto
    def special(self, path):
        """CD-raita (.cda) ja levykuva (.iso). Palauttaa True jos käsitelty."""
        p = Path(path)
        ext = p.suffix.lower()
        if ext == ".cda":
            self.play_cd(p.anchor.rstrip("\\/") or str(p.parent), cda_track_number(p))
            return True
        if ext == ".iso":
            self.video.set("dvd-device", str(p))
            self.video.cmd("loadfile", "dvd://", "replace")
            return True
        return False

    def play_cd(self, device, start_track=1):
        """Musiikki-CD: jokainen raita omaksi rivikseen soittolistaan (saumaton toisto)."""
        try:
            tracks = cdaudio.read_toc(device)
        except ValueError as e:
            if IS_WIN:
                self.statusBar().showMessage(f"CD:tä ei voitu lukea: {e}", 10000)
                return
            self.video.set("cdrom-device", device)  # muut järjestelmät: mpv:n oma CD-tuki
            self.pending_chapter = start_track - 1
            self.video.cmd("loadfile", "cdda://", "replace")
            return
        self.video.cmd("stop")
        start = 0
        for i, t in enumerate(tracks):
            self.video.cmd("loadfile", cdaudio.track_url(device, t.number), "append")
            if t.number == start_track:
                start = i
        self.video.cmd("playlist-play-index", start)
        self.video.set("pause", False)
        total = sum(t.seconds for t in tracks)
        self.statusBar().showMessage(f"Musiikki-CD: {len(tracks)} kappaletta, {fmt_time(total)}", 6000)

    def play_file_in_context(self, path):
        """Toista tiedosto ja laita saman kansion muut tiedostot jonoon (albumit)."""
        if self.special(path):
            return
        p = Path(path)
        files = media_in_folder(p.parent) if self.cfg.get("queue_folder") else [p]
        if p not in files:
            files = [p]
        self.save_position()
        self.video.cmd("stop")  # tyhjentää soittolistan
        for f in files:
            self.video.cmd("loadfile", str(f), "append")
        self.video.cmd("playlist-play-index", files.index(p))
        self.video.set("pause", False)

    def save_position(self):
        """Jatka siitä mihin jäit: tallenna nykyisen tiedoston kohta ennen vaihtoa."""
        if self.cfg.get("resume") and not self.state.get("idle-active", True):
            self.video.cmd("write-watch-later-config")

    def add_paths(self, paths, play=False, replace=False):
        # Yksi tiedosto avattuna (Resurssienhallinta, raahaus, Avaa-ikkuna):
        # saman kansion muut tiedostot jonoon, jotta seuraava jakso / kappale jatkuu.
        if (play and len(paths) == 1 and self.cfg.get("queue_folder")
                and Path(paths[0]).is_file() and Path(paths[0]).suffix.lower() not in (".cda", ".iso")
                and Path(paths[0]).suffix.lower().lstrip(".") not in ("m3u", "m3u8", "pls", "cue")):
            self.play_file_in_context(str(paths[0]))
            return
        files = []
        for path in paths:
            p = Path(path)
            if p.is_dir():
                files += media_in_folder(p, recursive=True)
            elif p.suffix.lower() in (".cda", ".iso"):
                self.special(p)
                return
            elif p.exists() or "://" in str(path):
                files.append(p if p.exists() else path)
        if not files:
            return
        idle = self.state.get("idle-active", True)
        if replace or (play and not idle):
            self.save_position()
        for i, f in enumerate(files):
            if i == 0 and replace:
                mode = "replace"
            elif i == 0 and play and idle:
                mode = "append-play"
            else:
                mode = "append"
            self.video.cmd("loadfile", str(f), mode)
        if play and not idle and not replace:
            self.video.cmd("playlist-play-index", len(self.playlist))
        if play or replace:
            self.video.set("pause", False)

    def play_folder(self, folder, recursive=False):
        if folder:
            files = media_in_folder(folder, recursive)
            if files:
                self.add_paths([str(f) for f in files], replace=True)

    def add_folder(self, folder, recursive=False):
        if folder:
            self.add_paths([str(f) for f in media_in_folder(folder, recursive)])

    def open_files_dialog(self):
        exts = " ".join(NAME_FILTERS[: len(NAME_FILTERS) // 2])
        files, _ = QFileDialog.getOpenFileNames(
            self, "Avaa tiedostoja", self.current_dir,
            f"Mediatiedostot ({exts});;Kaikki tiedostot (*)")
        if files:
            self.add_paths(files, play=True)

    def open_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Avaa kansio", self.current_dir)
        if d:
            self.browse(d)
            self.add_paths([d], play=True)

    def toggle_pause(self):
        if self.state.get("idle-active", True):
            if self.playlist:
                self.video.cmd("playlist-play-index", max(0, self.state.get("playlist-pos") or 0))
                self.video.set("pause", False)
            return
        self.video.cmd("cycle", "pause")

    def stop(self):
        self.video.cmd("playlist-play-index", "none")  # pysäyttää, soittolista säilyy

    def has_chapters(self):
        return len(self.state.get("chapter-list") or []) > 1

    def next(self):
        if self.has_chapters():
            self.video.cmd("add", "chapter", 1)
        else:
            self.video.cmd("playlist-next")

    def prev(self):
        if self.has_chapters():
            self.video.cmd("add", "chapter", -1)
        elif (self.state.get("time-pos") or 0) > 3:
            self.video.cmd("seek", 0, "absolute")
        else:
            self.video.cmd("playlist-prev")

    def set_repeat(self, mode):
        self.video.set("loop-file", "inf" if mode == "one" else "no")
        self.video.set("loop-playlist", "inf" if mode == "all" else "no")

    def update_repeat_state(self):
        lp, lf = self.state.get("loop-playlist"), self.state.get("loop-file")
        if lf not in (False, None, "no"):
            self.repeat_actions["one"].setChecked(True)
        elif lp not in (False, None, "no"):
            self.repeat_actions["all"].setChecked(True)
        else:
            self.repeat_actions["off"].setChecked(True)

    def set_exclusive(self, on):
        self.cfg.set("exclusive", on)
        self.video.set_exclusive(on)
        self.update_audio_info()

    def load_subtitle(self):
        f, _ = QFileDialog.getOpenFileName(self, "Lataa tekstitys", self.current_dir,
                                           "Tekstitykset (*.srt *.ass *.ssa *.sub *.vtt *.sup *.idx);;Kaikki (*)")
        if f:
            self.video.cmd("sub-add", f, "select")

    # ======================================================= Soittolista
    def rebuild_playlist(self):
        selected = {self.pl_view.row(i) for i in self.pl_view.selectedItems()}
        self.pl_view.clear()
        bold = self.pl_view.font()
        bold.setBold(True)
        for i, e in enumerate(self.playlist):
            name = self.entry_name(e, i)
            it = QListWidgetItem(f"{i + 1}.  {name}")
            it.setToolTip(e.get("filename", ""))
            if e.get("current"):
                it.setFont(bold)
                it.setForeground(QColor(self.accent))
                it.setIcon(icon("play", self.accent, 32))
            self.pl_view.addItem(it)
            if i in selected:
                it.setSelected(True)
        n = len(self.playlist)
        self.pl_title.setText(f"SOITTOLISTA  ·  {n}" if n else "SOITTOLISTA")

    def entry_name(self, e, i=0):
        """Soittolistarivin nimi: tagien kappaleen nimi ja artisti, radioasema tai tiedostonimi."""
        fn = e.get("filename", "")
        if fn in self.radio_names:
            return self.radio_names[fn]
        name = display_name(e)
        if not e.get("title") and i < 500 and "://" not in fn and Path(fn).suffix.lower().lstrip(".") in library.LIB_AUDIO:
            tg = self._tags(fn)
            if tg.get("title") and tg["title"] != Path(fn).stem:
                name = f"{tg['artist']} – {tg['title']}" if tg.get("artist") else tg["title"]
        return name

    def remove_selected(self):
        for r in sorted((self.pl_view.row(i) for i in self.pl_view.selectedItems()), reverse=True):
            self.video.cmd("playlist-remove", r)

    def move_selected(self, delta):
        rows = sorted(self.pl_view.row(i) for i in self.pl_view.selectedItems())
        n = len(self.playlist)
        if not rows or (delta < 0 and rows[0] == 0) or (delta > 0 and rows[-1] == n - 1):
            return
        for r in (rows if delta < 0 else list(reversed(rows))):
            # playlist-move a b: siirtää kohdan a paikan b eteen
            self.video.cmd("playlist-move", r, r - 1 if delta < 0 else r + 2)
        QTimer.singleShot(60, lambda: [self.pl_view.item(r + delta).setSelected(True)
                                       for r in rows if self.pl_view.item(r + delta)])

    def clear_playlist(self):
        self.video.cmd("stop")
        self.video.cmd("playlist-clear")

    def playlist_menu(self, pos):
        menu = QMenu(self)
        it = self.pl_view.itemAt(pos)
        if it:
            menu.addAction("Toista", lambda: self.video.cmd("playlist-play-index", self.pl_view.row(it)))
            menu.addAction("Siirrä ylös", lambda: self.move_selected(-1))
            menu.addAction("Siirrä alas", lambda: self.move_selected(1))
            menu.addAction("Poista", self.remove_selected)
            menu.addSeparator()
        menu.addAction("Lisää tiedostoja…", self.open_files_dialog)
        menu.addAction("Sekoita", lambda: self.video.cmd("playlist-shuffle"))
        menu.addAction("Järjestä aakkosjärjestykseen", self.sort_playlist)
        menu.addAction("Tyhjennä", self.clear_playlist)
        menu.exec(self.pl_view.viewport().mapToGlobal(pos))

    def sort_playlist(self):
        files = sorted((e["filename"] for e in self.playlist), key=natural_key)
        for target, fn in enumerate(files):
            now = [e["filename"] for e in self.playlist]
            src = now.index(fn, target)
            if src != target:
                self.video.cmd("playlist-move", src, target)
                self.playlist.insert(target, self.playlist.pop(src))

    # ==================================================== mpv-tapahtumat
    def on_prop(self, name, value):
        self.state[name] = value
        if name == "time-pos":
            if not self.seek_slider.dragging:
                self.seek_slider.blockSignals(True)
                self.seek_slider.setValue(int((value or 0) * 1000))
                self.seek_slider.blockSignals(False)
                self.pos_label.setText(fmt_time(value) if value is not None else "0:00")
            self._check_next_card(value)
        elif name == "duration":
            self.seek_slider.setRange(0, int((value or 0) * 1000))
            self.dur_label.setText(fmt_time(value) if value else "0:00")
        elif name in ("pause", "mute"):
            self.refresh_icons()
            if name == "mute" and self._ready:
                self.video.toast("Mykistetty" if value else "Ääni päällä")
        elif name == "speed":
            if self._ready and value:
                self.video.toast(f"Nopeus {value:.2f}×")
            if name == "mute":
                self.update_audio_info()
        elif name == "idle-active":
            self.refresh_icons()
            if value:
                self.show_idle()
                self.seek_slider.setRange(0, 0)
                self.pos_label.setText("0:00")
                self.dur_label.setText("0:00")
                self.format_label.setText("")
                self.bp_label.setText("")
        elif name == "playlist":
            self.playlist = value or []
            self.rebuild_playlist()
            self.update_now_playing()
        elif name in ("media-title", "metadata"):
            self.update_now_playing()
        elif name == "chapter-list":
            self.rebuild_chapter_menu(value or [])
        elif name == "chapter":
            self.rebuild_chapter_menu(self.state.get("chapter-list") or [])
            self.update_now_playing()
        elif name == "track-list":
            self.rebuild_track_menus(value or [])
            self.update_shaders()
            self.update_now_playing()
        elif name == "volume":
            v = int(round(value or 0))
            self.vol_slider.blockSignals(True)
            self.vol_slider.setValue(v)
            self.vol_slider.blockSignals(False)
            self.vol_slider.setToolTip(f"Äänenvoimakkuus {v} %")
            if self._ready:
                self.video.toast(f"Äänenvoimakkuus {v} %")
            self.update_audio_info()
        elif name == "video-params":
            self.update_shaders()
            if self.adjust_dialog is not None and self.adjust_dialog.isVisible():
                self.adjust_dialog.refresh_info()
            self.update_now_playing()
            self.update_audio_info()
            if self.is_real_video() and not self.cfg.get("auto_next"):
                self.video.set("keep-open", "yes")   # sarjan jakso jää loppuun eikä seuraava ala
            if (self.cfg.get("auto_fullscreen") and not self._auto_fs_done and not self.fullscreen
                    and self.is_real_video()):
                self._auto_fs_done = True
                self.toggle_fullscreen()
        elif name == "audio-params":
            self.update_audio_info()
            self.update_now_playing()
        elif name in ("audio-params", "audio-out-params", "audio-codec-name", "current-ao",
                      "af", "audio-exclusive", "video-codec", "hwdec-current"):
            self.update_audio_info()
        elif name in ("loop-playlist", "loop-file"):
            self.update_repeat_state()

    def on_file_loaded(self):
        self._auto_fs_done = False
        self._hide_next_card("idle")
        self.video.set("keep-open", "no")
        if self.pending_chapter is not None:
            ch, self.pending_chapter = self.pending_chapter, None
            QTimer.singleShot(100, lambda: self.video.set("chapter", ch))
        self.update_now_playing()

    def on_end_file(self, reason, error, entry_id):
        if reason == "error":
            name = next((display_name(e) for e in self.playlist if str(e.get("id")) == entry_id), "")
            msg = f"Toisto epäonnistui: {name}" + (f" ({error})" if error else "")
            if "cd" in name.lower():
                msg += " – onko CD asemassa?"
            self.statusBar().showMessage(msg, 10000)

    # ---- Hiiri ja näppäimet videon päällä
    def on_video_click(self):
        if self.cfg.get("click_action") != "pause":
            return
        if self.state.get("idle-active", True) and not self.playlist:
            return
        self._click_time = time.monotonic()
        self.toggle_pause()

    def on_video_double_click(self):
        # Tuplaklikkauksen ensimmäinen klikkaus vaihtoi jo tauon -> palautetaan ennalleen
        if self.cfg.get("click_action") == "pause" and time.monotonic() - self._click_time < 1.0:
            self.toggle_pause()
        if self.cfg.get("dblclick_action") == "fullscreen":
            self.toggle_fullscreen()

    def on_video_wheel(self, direction):
        if self.cfg.get("wheel_action") == "seek":
            self.video.cmd("seek", direction * self.cfg.get("seek_short"), "relative+exact")
        else:
            self.video.cmd("add", "volume", direction * max(1, self.cfg.get("volume_step") // 2))

    def show_main_menu(self):
        """Koko valikko yhtenä ponnahdusvalikkona (oikea klikkaus videolla / ☰)."""
        menu = QMenu(self)
        for a in self.menuBar().actions():
            if a.menu():
                menu.addMenu(a.menu())
        menu.addSeparator()
        menu.addAction("Poistu koko näytöstä" if self.fullscreen else "Koko näyttö", self.toggle_fullscreen)
        menu.addAction("Asetukset…", self.open_settings)
        menu.exec(QCursor.pos())

    # ============================================================ Näkymät
    def show_idle(self):
        self.video.set_show_frame(False)
        self.video.set_album(None)
        if self.cfg.get("show_hint"):
            self.video.set_info([
                ("Mediasoitin", 30, self.accent, False),
                ("Valitse tiedosto vasemmalta, raahaa tiedostoja tähän", 12, theme.MUTED, False),
                ("tai tuplaklikkaa CD/DVD-levyä.", 12, theme.MUTED, False),
            ])
        else:
            self.video.set_info(None)
        self.setWindowTitle("Mediasoitin")
        self.ov_title.setText("")

    def is_real_video(self):
        """Onko käynnissä oikea video (ei pelkkä kansikuva)."""
        for t in self.state.get("track-list") or []:
            if t.get("type") == "video" and t.get("selected"):
                return not (t.get("albumart") or t.get("image"))
        return False

    def update_now_playing(self):
        if self.state.get("idle-active", True):
            return
        title = self.state.get("media-title") or ""
        path = self.state.get("path") or ""
        is_cd = path.startswith("cdtrack://")
        if is_cd:
            title = f"Kappale {path.rsplit('/', 1)[-1]}"
        station = self.radio_names.get(path) or (self.radio.name_for(path) if path.startswith("http") else None)
        md = self.state.get("metadata") or {}
        low = {str(k).lower(): v for k, v in md.items()}
        artist = low.get("artist") or low.get("album_artist") or ""
        album = low.get("album") or ("Musiikki-CD" if is_cd else "")
        if station:
            icy = low.get("icy-title") or ""
            title = icy or (title if title and title != path and "://" not in title else station)
            artist, album = station, "Netradio"
        chs = self.state.get("chapter-list") or []
        ch = self.state.get("chapter")
        if len(chs) > 1 and ch is not None and 0 <= ch < len(chs):
            title = f"{title} – {chs[ch].get('title') or f'Kappale {ch + 1}'}"
        self.setWindowTitle(f"{title} – Mediasoitin" if title else "Mediasoitin")
        self.ov_title.setText(f"{artist} – {title}" if artist else title)

        real = self.is_real_video()
        self.video.set_show_frame(real)
        self.video.set_info(None)
        if real:
            self.video.set_album(None)
            return
        self.video.set_album(self._album_info(path, title, artist, album, is_cd))

    def _tags(self, path):
        if path not in self.tag_cache:
            self.tag_cache[path] = self.library_tracks.get(path) or library.read_tags(path)
        return self.tag_cache[path]

    def _cover(self, path):
        key = path
        if key not in self.cover_cache:
            pm = None
            try:
                data = library.find_cover(path)
                if data:
                    pm = QPixmap()
                    pm.loadFromData(data)
                    if pm.isNull():
                        pm = None
                    else:
                        pm = pm.scaled(800, 800, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            except Exception:
                pm = None
            self.cover_cache[key] = pm
            if len(self.cover_cache) > 200:
                self.cover_cache.pop(next(iter(self.cover_cache)))
        return self.cover_cache[key]

    def _album_info(self, path, title, artist, album, is_cd):
        """Albuminäkymän tiedot: kansikuva, nimet ja saman albumin kappaleet."""
        info = {"title": title, "artist": artist, "album": album, "cover": None, "tracks": [], "current": -1}
        if path.startswith("http"):
            info["cover"] = self.radio.logo_for(path)
            self._cover_bytes = None
        local = bool(path) and "://" not in path and Path(path).exists()
        if local:
            t = self._tags(path)
            info["title"] = t.get("title") or title
            info["artist"] = t.get("artist") or artist
            al = t.get("album") or album
            info["album"] = f"{al}  ·  {t['year']}" if al and t.get("year") else al
            info["cover"] = self._cover(path)
            self._cover_bytes = path
        ap = self.state.get("audio-params") or {}
        if ap:
            codec = (self.state.get("audio-codec-name") or "").upper()
            info["meta"] = f"{codec}  ·  {ap.get('samplerate', 0) / 1000:g} kHz  ·  {describe_format(ap.get('format'))}"
        # Kappalelista: soittolistan kappaleet samasta kansiosta (tai koko CD)
        folder = str(Path(path).parent) if local else None
        rows, cur = [], -1
        for e in self.playlist:
            fn = e.get("filename", "")
            if is_cd and fn.startswith("cdtrack://"):
                rows.append((int(fn.rsplit("/", 1)[-1]), f"Kappale {fn.rsplit('/', 1)[-1]}", ""))
            elif local and "://" not in fn and str(Path(fn).parent) == folder:
                if len(rows) >= 150:
                    continue
                tg = self._tags(fn)
                rows.append((tg.get("track") or "", tg.get("title") or Path(fn).stem,
                             fmt_time(tg.get("duration")) if tg.get("duration") else ""))
            else:
                continue
            if e.get("current"):
                cur = len(rows) - 1
        info["tracks"], info["current"] = rows, cur
        return info

    def update_audio_info(self):
        ap = self.state.get("audio-params")
        vp = self.state.get("video-params")
        parts = []
        if ap:
            codec = (self.state.get("audio-codec-name") or "").upper()
            sr = ap.get("samplerate") or 0
            parts.append(f"{codec}  {sr / 1000:g} kHz  {describe_format(ap.get('format'))}"
                         f"  {ap.get('channel-count')} kan.")
        if vp and vp.get("w") and self.is_real_video():
            vc = (self.state.get("video-codec") or "").split(" ")[0]
            s = f"{vc}  {vp.get('w')}×{vp.get('h')}"
            if vp.get("gamma") in ("pq", "hlg"):
                s += "  HDR → SDR"
            if self._shaders:
                s += "  ·  AI-tarkennus" if any("ravu" in x or "nnedi" in x for x in self._shaders) else "  ·  terävöitys"
            parts.append(s)
        self.format_label.setText("     │     ".join(parts))

        if not ap or not IS_WIN:
            self.bp_label.setText("")
            return
        op = self.state.get("audio-out-params") or {}
        excl = self.state.get("audio-exclusive") in (True, "yes")
        reasons = []
        if not excl:
            reasons.append("Jaettu tila: Windows miksaa äänen ja voi muuntaa näytteenottotaajuuden.\n"
                           "Ota käyttöön: Ääni → Bit-perfect.")
        if op.get("samplerate") and op.get("samplerate") != ap.get("samplerate"):
            reasons.append(f"Näytteenottotaajuus muunnetaan: {ap.get('samplerate')} → {op.get('samplerate')} Hz.")
        if op.get("channel-count") and op.get("channel-count") != ap.get("channel-count"):
            reasons.append("Kanavamäärä muunnetaan äänikortille sopivaksi.")
        if (self.state.get("volume") or 100) < 100 or self.state.get("mute"):
            reasons.append("Äänenvoimakkuus alle 100 % muuttaa signaalia.")
        if self.state.get("af"):
            reasons.append("Äänisuodattimia käytössä.")
        if reasons:
            self.bp_label.setText("<span style='color:#777;'>●</span> Ei bit-perfect")
            self.bp_label.setToolTip("\n".join(reasons))
        else:
            out_sr = op.get("samplerate") or ap.get("samplerate")
            self.bp_label.setText(f"<span style='color:{self.accent};'>●</span> Bit-perfect {out_sr / 1000:g} kHz")
            self.bp_label.setToolTip("Ääni menee äänikortille muuttamattomana (WASAPI exclusive).")

    def rebuild_chapter_menu(self, chs):
        self.chapter_menu.clear()
        cur = self.state.get("chapter")
        group = QActionGroup(self.chapter_menu)
        for i, c in enumerate(chs):
            title = c.get("title") or f"Kappale {i + 1}"
            a = self.chapter_menu.addAction(f"{i + 1}. {title}   ({fmt_time(c.get('time'))})")
            a.setCheckable(True)
            a.setChecked(i == cur)
            a.triggered.connect(lambda _=False, n=i: self.video.set("chapter", n))
            group.addAction(a)
        self.chapter_menu.setEnabled(len(chs) > 1)

    def rebuild_track_menus(self, tracks):
        for menu, ttype, prop in ((self.audio_menu, "audio", "aid"), (self.sub_menu, "sub", "sid")):
            menu.clear()
            group = QActionGroup(menu)
            if ttype == "sub":
                a = menu.addAction("Ei tekstitystä")
                a.setCheckable(True)
                a.setChecked(not any(t.get("selected") for t in tracks if t.get("type") == "sub"))
                a.triggered.connect(lambda: self.video.set("sid", "no"))
                group.addAction(a)
            items = [t for t in tracks if t.get("type") == ttype]
            for t in items:
                label = f"{t.get('id')}. " + " ".join(x for x in (
                    t.get("title") or "", f"[{t['lang']}]" if t.get("lang") else "",
                    f"({t.get('codec')})" if t.get("codec") else "",
                    "– ulkoinen" if t.get("external") else "") if x)
                a = menu.addAction(label)
                a.setCheckable(True)
                a.setChecked(bool(t.get("selected")))
                a.triggered.connect(lambda _=False, tid=t.get("id"), p=prop: self.video.set(p, tid))
                group.addAction(a)
            menu.setEnabled(bool(items) or ttype == "sub")

    def fill_device_menu(self):
        self.device_menu.clear()
        group = QActionGroup(self.device_menu)
        current = self.video.get("audio-device", "auto")
        for dev in self.video.get("audio-device-list", []) or []:
            name = dev.get("name")
            desc = "Oletuslaite (Windows)" if name == "auto" else (dev.get("description") or name)
            a = self.device_menu.addAction(desc)
            a.setCheckable(True)
            a.setChecked(name == current)
            a.triggered.connect(lambda _=False, n=name: self.set_audio_device(n))
            group.addAction(a)

    def set_audio_device(self, name):
        self.video.set("audio-device", name)
        self.settings.setValue("audio_device", name)

    def show_file_info(self):
        if self.state.get("idle-active", True):
            return
        rows = []
        for label, prop in [("Tiedosto", "path"), ("Säiliö", "file-format"), ("Koko", "file-size"),
                            ("Äänikoodekki", "audio-codec"), ("Videokoodekki", "video-codec"),
                            ("Äänen bittinopeus", "audio-bitrate"), ("Videon bittinopeus", "video-bitrate"),
                            ("Laitteistopurku", "hwdec-current"),
                            ("Äänilähtö", "current-ao"), ("Videolähtö", "current-vo")]:
            v = self.video.get(prop)
            if v in (None, ""):
                continue
            if prop == "file-size":
                v = f"{int(v) / 1_048_576:.1f} Mt"
            if prop.endswith("bitrate"):
                v = f"{int(v) / 1000:.0f} kbit/s"
            rows.append(f"<tr><td><b>{label}</b></td><td>{_esc(str(v))}</td></tr>")
        ap, op = self.state.get("audio-params"), self.state.get("audio-out-params")
        if ap:
            rows.append(f"<tr><td><b>Ääni (purettu)</b></td><td>{ap.get('samplerate')} Hz, "
                        f"{describe_format(ap.get('format'))}, {ap.get('channels')}</td></tr>")
        if op:
            rows.append(f"<tr><td><b>Ääni (äänikortille)</b></td><td>{op.get('samplerate')} Hz, "
                        f"{describe_format(op.get('format'))}, {op.get('channels')}</td></tr>")
        QMessageBox.information(self, "Tiedoston tiedot", "<table cellspacing=6>" + "".join(rows) + "</table>")

    def show_help(self):
        rows = ["<tr><td><b>Klikkaus videoon</b></td><td>Tauko / jatka</td></tr>",
                "<tr><td><b>Tuplaklikkaus videoon</b></td><td>Koko näyttö</td></tr>",
                "<tr><td><b>Oikea klikkaus videoon</b></td><td>Valikko</td></tr>",
                "<tr><td><b>Rulla videon päällä</b></td><td>"
                + ("Kelaus" if self.cfg.get("wheel_action") == "seek" else "Äänenvoimakkuus") + "</td></tr>"]
        for aid, label, _d, _g in ACTIONS:
            k = self.act[aid].shortcut().toString(QKeySequence.NativeText)
            if k:
                rows.append(f"<tr><td><b>{_esc(k)}</b></td><td>{_esc(self.act[aid].text())}</td></tr>")
        box = QMessageBox(self)
        box.setWindowTitle("Pikanäppäimet")
        box.setText("<table cellspacing=4>" + "".join(rows) + "</table>"
                    "<p style='color:#8C8C8C'>Pikanäppäimiä voi muuttaa: Tiedosto → Asetukset → Pikanäppäimet.</p>")
        box.exec()

    def open_error_log(self):
        path = error_log_path()
        if not path.exists():
            QMessageBox.information(self, "Virheloki", "Virhelokissa ei ole merkintöjä – virheitä ei ole tapahtunut.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def about(self):
        QMessageBox.about(self, "Tietoja", f"<b>Mediasoitin {__version__}</b><br><br>"
                          "Toistomoottori: mpv / libmpv (FFmpeg).<br>"
                          "Toistaa tiedostot, musiikki-CD:t, DVD:t ja ulkoiset levyt.")

    # ======================================================== Koko näyttö
    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self._fs_confirmed = False
        if self.fullscreen:
            self._was_max = self.isMaximized()
            self.library_panel.hide()
            self.playlist_panel.hide()
            self.menuBar().hide()
            self.statusBar().hide()
            self.bottom_ov.lay.addWidget(self.controls)   # ohjaimet videon päälle
            self.controls.show()
            self.showFullScreen()
            self._last_cursor = QCursor.pos()
            QTimer.singleShot(100, self._show_overlays)
            self.mouse_timer.start()
        else:
            self.mouse_timer.stop()
            self.hide_timer.stop()
            self.top_ov.hide()
            self.bottom_ov.hide()
            self.video.unsetCursor()
            self.video.toast_top = 24
            self.central_layout.addWidget(self.controls)  # takaisin ikkunan alareunaan
            self.controls.show()
            self.library_panel.setVisible(self.lib_action.isChecked())
            self.playlist_panel.setVisible(self.pl_action.isChecked())
            self.menuBar().show()
            self.statusBar().setVisible(self.status_action.isChecked())
            self.showMaximized() if getattr(self, "_was_max", False) else self.showNormal()
            self.video.setFocus()
        self.refresh_icons()

    def _place_overlays(self):
        from PySide6.QtCore import QRect
        w, h = self.video.width(), self.video.height()
        th = self.top_ov.sizeHint().height()
        bh = max(self.controls.sizeHint().height(), 52)
        self.top_ov.target = QRect(0, 0, w, th)
        self.top_ov.at_top = True
        self.bottom_ov.target = QRect(0, h - bh, w, bh)
        self.bottom_ov.at_top = False
        for o in (self.top_ov, self.bottom_ov):
            if o.shown() and o.anim_pos.state() != QPropertyAnimation.Running:
                o.setGeometry(o.target)

    def _show_overlays(self):
        if not self.fullscreen:
            return
        self._place_overlays()
        anim = self.cfg.get("animations")
        for o in (self.top_ov, self.bottom_ov):
            o.slide_in(anim)
            o.raise_()
        self.video.toast_top = self.top_ov.target.height() + 14
        self.video.unsetCursor()
        self.hide_timer.start()

    def _maybe_hide_overlays(self):
        if not self.fullscreen:
            return
        pos = QCursor.pos()
        over = any(o.isVisible() and o.rect().contains(o.mapFromGlobal(pos))
                   for o in (self.top_ov, self.bottom_ov))
        if over or QApplication.activePopupWidget() or self.seek_slider.dragging:
            self.hide_timer.start()  # hiiri palkin päällä tai valikko auki: pidetään näkyvissä
            return
        anim = self.cfg.get("animations")
        self.top_ov.slide_out(anim)
        self.bottom_ov.slide_out(anim)
        self.video.toast_top = 24
        self.preview.hide()
        self.video.setCursor(Qt.BlankCursor)  # piilota myös hiiren osoitin
        self.video.setFocus()

    def _poll_mouse(self):
        pos = QCursor.pos()
        if pos != self._last_cursor:
            self._last_cursor = pos
            self.on_mouse_activity()

    def on_mouse_activity(self):
        if not self.fullscreen:
            return
        self._last_cursor = QCursor.pos()
        if not self.bottom_ov.shown():
            self._show_overlays()
        else:
            self.hide_timer.start()

    def changeEvent(self, e):
        # Jos koko näytöstä poistutaan muuta kautta (esim. Win-näppäin), siivotaan tila.
        # Tarkistetaan viiveellä: Windows voi lähettää tilanvaihtoja välitilojen kautta.
        super().changeEvent(e)
        if e.type() == QEvent.WindowStateChange and self.fullscreen:
            if self.isFullScreen():
                self._fs_confirmed = True
            elif getattr(self, "_fs_confirmed", False):
                QTimer.singleShot(600, self._check_left_fullscreen)

    def _check_left_fullscreen(self):
        if self.fullscreen and getattr(self, "_fs_confirmed", False) and not self.isFullScreen() \
                and not (self.windowState() & Qt.WindowFullScreen):
            self.toggle_fullscreen()

    # =================================================== Raahaa ja pudota
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.add_paths(paths, play=True)

    def closeEvent(self, e):
        if self.fullscreen:
            self.toggle_fullscreen()
        self.preview.close()
        if self.adjust_dialog:
            self.adjust_dialog.close()
        if self.sub_dialog:
            self.sub_dialog.close()
        self.thumbs.stop()
        self.remote.stop()
        if self.scanner and self.scanner.isRunning():
            self.scanner.abort()
            self.scanner.wait(2000)
        if self.dvd_worker and self.dvd_worker.isRunning():
            self.dvd_worker.abort()
            self.dvd_worker.wait(3000)
        if self.cfg.get("resume"):
            self.video.cmd("write-watch-later-config")
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("split_main", self.split_main.saveState())
        self.settings.setValue("split_left", self.split_left.saveState())
        self.settings.setValue("volume", self.vol_slider.value())
        self.video.shutdown()
        super().closeEvent(e)

def _ass(s):
    return str(s).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", " ")


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def error_log_path():
    d = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation) or Path.home())
    return d / "virheloki.txt"


def install_error_log():
    """Valmiissa exessä virheet eivät näy missään, joten ne kirjoitetaan lokitiedostoon."""
    import datetime
    import traceback

    def hook(exc_type, exc, tb):
        try:
            path = error_log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > 512 * 1024:
                path.write_text("", encoding="utf-8")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n=== {datetime.datetime.now():%d.%m.%Y %H:%M:%S}  Mediasoitin {__version__} ===\n")
                f.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = hook


def main():
    import locale
    app = QApplication(sys.argv)
    install_error_log()
    locale.setlocale(locale.LC_NUMERIC, "C")  # mpv vaatii tämän
    app.setApplicationName("Mediasoitin")
    theme.apply(app, Config().get("accent"))
    files = [a for a in sys.argv[1:] if not a.startswith("-")]
    w = MainWindow(files)
    w.show()
    sys.exit(app.exec())
