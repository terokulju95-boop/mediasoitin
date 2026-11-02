"""Mediasoittimen pääikkuna."""
import sys
import time
from pathlib import Path

from PySide6.QtCore import QDir, QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QFileSystemModel, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QSlider, QSplitter,
    QStyle, QToolButton, QTreeView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__, cdaudio, theme
from .drives import NETWORK, OPTICAL, REMOVABLE, list_drives, quick_locations
from .icons import icon
from .media import (NAME_FILTERS, cda_track_number, describe_format, display_name,
                    fmt_time, media_in_folder, natural_key)
from .player import MpvWidget
from .settings import ACTIONS, Config, SettingsDialog

IS_WIN = sys.platform == "win32"
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

    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.dragging = False
        self.setRange(0, 0)
        self.setCursor(Qt.PointingHandCursor)

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
        self.library_panel = self.split_left
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
        self.split_main.addWidget(self.split_left)
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
            "seek_fwd": lambda: v.cmd("seek", self.cfg.get("seek_short"), "relative+exact"),
            "seek_back": lambda: v.cmd("seek", -self.cfg.get("seek_short"), "relative+exact"),
            "seek_fwd_long": lambda: v.cmd("seek", self.cfg.get("seek_long"), "relative+exact"),
            "seek_back_long": lambda: v.cmd("seek", -self.cfg.get("seek_long"), "relative+exact"),
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
            "audio_cycle": lambda: v.cmd("cycle", "audio"),
            "sub_cycle": lambda: v.cmd("cycle", "sub"),
            "sub_toggle": lambda: v.cmd("cycle", "sub-visibility"),
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
        if obj is self.video and e.type() == QEvent.Resize and self.fullscreen:
            self._place_overlays()
        return super().eventFilter(obj, e)

    # ============================================================ Teema
    def refresh_icons(self):
        a, t = self.accent, theme.TEXT
        self.setWindowIcon(icon("app", a, 64))
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
            it = QListWidgetItem(f"{i + 1}.  {display_name(e)}")
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
        elif name == "duration":
            self.seek_slider.setRange(0, int((value or 0) * 1000))
            self.dur_label.setText(fmt_time(value) if value else "0:00")
        elif name in ("pause", "mute"):
            self.refresh_icons()
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
        elif name in ("media-title", "metadata"):
            self.update_now_playing()
        elif name == "chapter-list":
            self.rebuild_chapter_menu(value or [])
        elif name == "chapter":
            self.rebuild_chapter_menu(self.state.get("chapter-list") or [])
            self.update_now_playing()
        elif name == "track-list":
            self.rebuild_track_menus(value or [])
            self.update_now_playing()
        elif name == "volume":
            v = int(round(value or 0))
            self.vol_slider.blockSignals(True)
            self.vol_slider.setValue(v)
            self.vol_slider.blockSignals(False)
            self.vol_slider.setToolTip(f"Äänenvoimakkuus {v} %")
            self.update_audio_info()
        elif name == "video-params":
            self.update_now_playing()
            self.update_audio_info()
            if (self.cfg.get("auto_fullscreen") and not self._auto_fs_done and not self.fullscreen
                    and self.is_real_video()):
                self._auto_fs_done = True
                self.toggle_fullscreen()
        elif name in ("audio-params", "audio-out-params", "audio-codec-name", "current-ao",
                      "af", "audio-exclusive", "video-codec", "hwdec-current"):
            self.update_audio_info()
        elif name in ("loop-playlist", "loop-file"):
            self.update_repeat_state()

    def on_file_loaded(self):
        self._auto_fs_done = False
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
        if path.startswith("cdtrack://"):
            title = f"Musiikki-CD – kappale {path.rsplit('/', 1)[-1]}"
        md = self.state.get("metadata") or {}
        low = {str(k).lower(): v for k, v in md.items()}
        artist = low.get("artist") or low.get("album_artist") or ""
        album = low.get("album") or ""
        chs = self.state.get("chapter-list") or []
        ch = self.state.get("chapter")
        if len(chs) > 1 and ch is not None and 0 <= ch < len(chs):
            title = f"{title} – {chs[ch].get('title') or f'Kappale {ch + 1}'}"
        self.setWindowTitle(f"{title} – Mediasoitin" if title else "Mediasoitin")
        self.ov_title.setText(f"{artist} – {title}" if artist else title)

        has_frame = bool((self.state.get("video-params") or {}).get("w"))
        self.video.set_show_frame(has_frame)
        if self.is_real_video():
            self.video.set_info(None)
            return
        lines = [(title, 22, "#FFFFFF", False)]
        if artist:
            lines.append((artist, 15, self.accent, False))
        if album:
            lines.append((album, 12, theme.MUTED, False))
        self.video.set_info(lines, bottom=has_frame)   # kansikuvan kanssa teksti alareunaan

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
                s += "  HDR"
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
            self.split_left.hide()
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
            self.central_layout.addWidget(self.controls)  # takaisin ikkunan alareunaan
            self.controls.show()
            self.split_left.setVisible(self.lib_action.isChecked())
            self.playlist_panel.setVisible(self.pl_action.isChecked())
            self.menuBar().show()
            self.statusBar().setVisible(self.status_action.isChecked())
            self.showMaximized() if getattr(self, "_was_max", False) else self.showNormal()
            self.video.setFocus()
        self.refresh_icons()

    def _place_overlays(self):
        w, h = self.video.width(), self.video.height()
        th = self.top_ov.sizeHint().height()
        bh = max(self.controls.sizeHint().height(), 52)
        self.top_ov.setGeometry(0, 0, w, th)
        self.bottom_ov.setGeometry(0, h - bh, w, bh)

    def _show_overlays(self):
        if not self.fullscreen:
            return
        self._place_overlays()
        self.top_ov.show()
        self.bottom_ov.show()
        self.top_ov.raise_()
        self.bottom_ov.raise_()
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
        self.top_ov.hide()
        self.bottom_ov.hide()
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
        if not self.bottom_ov.isVisible():
            self._show_overlays()
        else:
            self.hide_timer.start()

    def changeEvent(self, e):
        # Jos koko näytöstä poistutaan muuta kautta (esim. Win-näppäin), siivotaan tila.
        # Reagoidaan vasta kun koko näyttö on ensin varmasti ollut päällä.
        super().changeEvent(e)
        if e.type() == QEvent.WindowStateChange and self.fullscreen:
            if self.isFullScreen():
                self._fs_confirmed = True
            elif getattr(self, "_fs_confirmed", False):
                QTimer.singleShot(0, lambda: self.fullscreen and not self.isFullScreen()
                                  and self.toggle_fullscreen())

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


def main():
    import locale
    app = QApplication(sys.argv)
    locale.setlocale(locale.LC_NUMERIC, "C")  # mpv vaatii tämän
    app.setApplicationName("Mediasoitin")
    theme.apply(app, Config().get("accent"))
    files = [a for a in sys.argv[1:] if not a.startswith("-")]
    w = MainWindow(files)
    w.show()
    sys.exit(app.exec())
