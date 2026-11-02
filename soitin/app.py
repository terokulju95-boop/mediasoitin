"""Mediasoittimen pääikkuna."""
import sys
import time
from pathlib import Path

from PySide6.QtCore import QDir, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QColorDialog, QFileDialog, QFileSystemModel,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QSlider, QSplitter, QStyle, QToolButton, QTreeView, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from . import __version__, cdaudio, theme
from .drives import NETWORK, OPTICAL, REMOVABLE, list_drives, quick_locations
from .icons import icon
from .media import (NAME_FILTERS, cda_track_number, describe_format, display_name,
                    fmt_time, media_in_folder, natural_key)
from .player import MpvWidget

IS_WIN = sys.platform == "win32"
HIDE_DELAY_MS = 2500      # koko näytön palkit piiloon, kun hiiri on paikallaan
CLICK_DELAY_MS = 230      # odotetaan hetki, ettei tuplaklikkaus laukaise taukoa


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
    """Koko näytön tilassa videon päälle ilmestyvä palkki."""

    def __init__(self, parent):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_StyledBackground)
        self.setObjectName("overlay")
        self.setWindowOpacity(0.92)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(8, 4, 8, 4)


class MainWindow(QMainWindow):
    def __init__(self, files=None):
        super().__init__()
        self.settings = QSettings("Mediasoitin", "Mediasoitin")
        self.accent = self.settings.value("accent", theme.DEFAULT_ACCENT, type=str)
        self.state = {}             # mpv:n viimeisimmät ominaisuusarvot
        self.playlist = []
        self.pending_chapter = None
        self.fullscreen = False
        self._drive_sig = None
        self._last_click_pause = 0.0
        self._press_time = 0.0
        self._last_dbl = 0.0
        self._last_cursor = None

        self.setWindowTitle("Mediasoitin")
        self.resize(1280, 760)
        self.setAcceptDrops(True)

        exclusive = self.settings.value("exclusive", False, type=bool)
        volume = self.settings.value("volume", 100, type=int)
        self.video = MpvWidget(exclusive=exclusive, volume=volume)
        dev = self.settings.value("audio_device", "", type=str)
        if dev:
            self.video.set("audio-device", dev)

        self._build_ui()
        self._build_menus()
        self._build_shortcuts()
        self._build_fullscreen()
        self.refresh_icons()

        sig = self.video.signals
        sig.prop.connect(self.on_prop)
        sig.end_file.connect(self.on_end_file)
        sig.file_loaded.connect(self.on_file_loaded)
        sig.key.connect(self.on_video_key)

        self.click_timer = QTimer(self, singleShot=True, interval=CLICK_DELAY_MS,
                                  timeout=self._single_click)

        self.refresh_drives()
        self.drive_timer = QTimer(self, interval=3000, timeout=self.refresh_drives)
        self.drive_timer.start()
        QTimer.singleShot(300, self.show_idle)

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
            QTimer.singleShot(200, lambda: self.add_paths(files, play=True))

    # ================================================================ UI
    def _panel_title(self, text):
        lbl = QLabel(text.upper())
        lbl.setObjectName("panelTitle")
        return lbl

    def _button(self, tip, slot, name=None):
        b = QToolButton(toolTip=tip)
        b.setCursor(Qt.PointingHandCursor)
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
        self.seek_slider.seek.connect(lambda s: self.video.cmd("seek", s, "absolute+exact"))
        self.seek_slider.valueChanged.connect(
            lambda v: self.seek_slider.dragging and self.pos_label.setText(fmt_time(v / 1000)))
        self.mute_btn = self._button("Mykistä (M)", lambda: self.video.cmd("cycle", "mute"))
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setFixedWidth(100)
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

    def _build_menus(self):
        mb = self.menuBar()

        # Tiedosto
        m = mb.addMenu("&Tiedosto")
        m.addAction("Avaa tiedostoja…", QKeySequence.Open, self.open_files_dialog)
        m.addAction("Avaa kansio…", QKeySequence("Ctrl+Shift+O"), self.open_folder_dialog)
        self.disc_menu = m.addMenu("Toista levy (CD / DVD)")
        self.disc_menu.aboutToShow.connect(self.fill_disc_menu)
        m.addAction("Toista nykyinen kansio", lambda: self.play_folder(self.current_dir, True))
        m.addSeparator()
        m.addAction("Lopeta", QKeySequence.Quit, self.close)

        # Toisto
        m = mb.addMenu("T&oisto")
        m.addAction("Toista / tauko", self.toggle_pause)
        m.addAction("Pysäytä", self.stop)
        m.addAction("Edellinen", QKeySequence("Ctrl+Left"), self.prev)
        m.addAction("Seuraava", QKeySequence("Ctrl+Right"), self.next)
        m.addSeparator()
        m.addAction("Kelaa eteen 10 s", QKeySequence("Shift+Right"), lambda: self.video.cmd("seek", 10))
        m.addAction("Kelaa taakse 10 s", QKeySequence("Shift+Left"), lambda: self.video.cmd("seek", -10))
        m.addSeparator()
        self.chapter_menu = m.addMenu("Kappale / luku")
        self.chapter_menu.setEnabled(False)
        self.audio_menu = m.addMenu("Ääniraita")
        self.sub_menu = m.addMenu("Tekstitys")
        m.addAction("Lataa tekstitystiedosto…", self.load_subtitle)

        # Soittolista
        m = mb.addMenu("&Soittolista")
        m.addAction("Lisää tiedostoja…", self.open_files_dialog)
        m.addAction("Lisää kansio…", self.open_folder_dialog)
        m.addSeparator()
        m.addAction("Siirrä valitut ylös", QKeySequence("Alt+Up"), lambda: self.move_selected(-1))
        m.addAction("Siirrä valitut alas", QKeySequence("Alt+Down"), lambda: self.move_selected(1))
        m.addAction("Poista valitut", self.remove_selected)
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
        self.excl_action.setChecked(self.settings.value("exclusive", False, type=bool))
        self.excl_action.toggled.connect(self.set_exclusive)
        self.excl_action.setEnabled(IS_WIN)
        self.excl_action.setToolTip("Ääni äänikortille muuttamattomana. Windowsin äänenvoimakkuus ei "
                                    "vaikuta – pidä soittimen voimakkuus 100 %:ssa ja säädä vahvistimesta.")
        m.addAction(self.excl_action)
        m.setToolTipsVisible(True)
        self.device_menu = m.addMenu("Äänilaite")
        self.device_menu.aboutToShow.connect(self.fill_device_menu)
        m.addSeparator()
        m.addAction("Mykistä", QKeySequence("M"), lambda: self.video.cmd("cycle", "mute"))
        m.addAction("Voimakkaammin", QKeySequence("Ctrl+Up"), lambda: self.video.cmd("add", "volume", 5))
        m.addAction("Hiljemmin", QKeySequence("Ctrl+Down"), lambda: self.video.cmd("add", "volume", -5))

        # Näytä
        m = mb.addMenu("&Näytä")
        self.lib_action = m.addAction("Lähteet ja tiedostot", QKeySequence("Ctrl+1"))
        self.lib_action.setCheckable(True)
        self.lib_action.setChecked(self.settings.value("show_library", True, type=bool))
        self.lib_action.toggled.connect(lambda on: self._toggle_panel(self.library_panel, "show_library", on))
        self.pl_action = m.addAction("Soittolista", QKeySequence("Ctrl+2"))
        self.pl_action.setCheckable(True)
        self.pl_action.setChecked(self.settings.value("show_playlist", True, type=bool))
        self.pl_action.toggled.connect(lambda on: self._toggle_panel(self.playlist_panel, "show_playlist", on))
        self.status_action = m.addAction("Tilarivi (muoto ja bit-perfect)")
        self.status_action.setCheckable(True)
        self.status_action.setChecked(self.settings.value("show_status", True, type=bool))
        self.status_action.toggled.connect(lambda on: self._toggle_panel(self.statusBar(), "show_status", on))
        m.addAction("Vain video (piilota paneelit)", QKeySequence("Ctrl+0"), self.video_only)
        m.addSeparator()
        color_menu = m.addMenu("Korostusväri")
        self.color_group = QActionGroup(self)
        for name, col in theme.ACCENTS:
            a = color_menu.addAction(icon("app", col, 32), name)
            a.setCheckable(True)
            a.setChecked(col.lower() == self.accent.lower())
            a.triggered.connect(lambda _=False, c=col: self.set_accent(c))
            self.color_group.addAction(a)
        color_menu.addSeparator()
        color_menu.addAction("Oma väri…", self.pick_accent)
        m.addSeparator()
        m.addAction("Koko näyttö", QKeySequence("F11"), self.toggle_fullscreen)
        self.show_all_action = QAction("Näytä kaikki tiedostot (myös tuntemattomat)", self, checkable=True)
        self.show_all_action.setChecked(self.settings.value("show_all", False, type=bool))
        self.show_all_action.toggled.connect(self.set_show_all)
        m.addAction(self.show_all_action)
        self.set_show_all(self.show_all_action.isChecked())
        m.addAction("Tiedoston tekniset tiedot", QKeySequence("Ctrl+I"), self.show_file_info)

        # Ohje
        m = mb.addMenu("&Ohje")
        m.addAction("Pikanäppäimet", self.show_help)
        m.addAction("Tietoja", self.about)

    def _build_shortcuts(self):
        def sc(key, slot):
            s = QShortcut(QKeySequence(key), self, slot)
            s.setContext(Qt.ApplicationShortcut)  # toimii myös koko näytön palkeissa
        sc(Qt.Key_Space, self.toggle_pause)
        sc("F", self.toggle_fullscreen)
        sc(Qt.Key_Escape, lambda: self.fullscreen and self.toggle_fullscreen())
        sc(Qt.Key_Delete, self.remove_selected)
        sc(Qt.Key_MediaTogglePlayPause, self.toggle_pause)
        sc(Qt.Key_MediaPlay, self.toggle_pause)
        sc(Qt.Key_MediaPause, self.toggle_pause)
        sc(Qt.Key_MediaStop, self.stop)
        sc(Qt.Key_MediaNext, self.next)
        sc(Qt.Key_MediaPrevious, self.prev)

    def _build_fullscreen(self):
        # Yläpalkki: nimi + valikko + poistu
        self.top_ov = Overlay(self)
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
        self.bottom_ov = Overlay(self)
        self.bottom_ov.lay.setContentsMargins(0, 0, 0, 0)

        self.hide_timer = QTimer(self, singleShot=True, interval=HIDE_DELAY_MS,
                                 timeout=self._maybe_hide_overlays)
        self.mouse_timer = QTimer(self, interval=120, timeout=self._poll_mouse)

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
        self.settings.setValue("accent", self.accent)
        theme.apply(QApplication.instance(), self.accent)
        for a in self.color_group.actions():
            a.setChecked(False)
        for a, (_, col) in zip(self.color_group.actions(), theme.ACCENTS):
            a.setChecked(col.lower() == self.accent.lower())
        self.refresh_icons()
        self.rebuild_playlist()
        self.update_now_playing()
        if self.state.get("idle-active", True):
            self.show_idle()

    def pick_accent(self):
        c = QColorDialog.getColor(QColor(self.accent), self, "Valitse korostusväri")
        if c.isValid():
            self.set_accent(c.name())

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
        files = media_in_folder(p.parent)
        if p not in files:
            files = [p]
        self.video.cmd("stop")  # tyhjentää soittolistan
        for f in files:
            self.video.cmd("loadfile", str(f), "append")
        self.video.cmd("playlist-play-index", files.index(p))
        self.video.set("pause", False)

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
        self.settings.setValue("exclusive", on)
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
        elif name in ("audio-params", "audio-out-params", "audio-codec-name", "current-ao",
                      "af", "audio-exclusive", "video-codec", "hwdec-current"):
            self.update_audio_info()
        elif name in ("loop-playlist", "loop-file"):
            self.update_repeat_state()

    def on_file_loaded(self):
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
    def on_video_key(self, key):
        if key == "MBTN_LEFT":
            if time.monotonic() - self._last_dbl > 0.15:
                self._press_time = time.monotonic()
                self.click_timer.start()
            return
        if key == "MBTN_LEFT_DBL":
            self._last_dbl = time.monotonic()
            self.click_timer.stop()
            # jos tuplaklikkauksen ensimmäinen klikkaus ehti jo pysäyttää, perutaan se
            if time.monotonic() - self._last_click_pause < QApplication.doubleClickInterval() / 1000:
                self.toggle_pause()
                self._last_click_pause = 0.0
            self.toggle_fullscreen()
            return
        actions = {
            "f": self.toggle_fullscreen, "F": self.toggle_fullscreen,
            "SPACE": self.toggle_pause, "MBTN_RIGHT": self.show_main_menu,
            "ESC": lambda: self.fullscreen and self.toggle_fullscreen(),
            "RIGHT": lambda: self.video.cmd("seek", 5), "LEFT": lambda: self.video.cmd("seek", -5),
            "UP": lambda: self.video.cmd("add", "volume", 5),
            "DOWN": lambda: self.video.cmd("add", "volume", -5),
            "WHEEL_UP": lambda: self.video.cmd("add", "volume", 2),
            "WHEEL_DOWN": lambda: self.video.cmd("add", "volume", -2),
            "m": lambda: self.video.cmd("cycle", "mute"),
            "n": self.next, "p": self.prev,
            "PGUP": lambda: self.video.cmd("add", "chapter", 1),
            "PGDWN": lambda: self.video.cmd("add", "chapter", -1),
        }
        fn = actions.get(key)
        if fn:
            fn()

    def _single_click(self):
        if self.state.get("idle-active", True) and not self.playlist:
            return
        self._last_click_pause = self._press_time  # klikkauksen hetki, ei ajastimen
        self.toggle_pause()

    def show_main_menu(self):
        """Koko valikko yhtenä ponnahdusvalikkona (oikea klikkaus videolla / ☰)."""
        menu = QMenu(self)
        for a in self.menuBar().actions():
            if a.menu():
                menu.addMenu(a.menu())
        menu.addSeparator()
        menu.addAction("Poistu koko näytöstä" if self.fullscreen else "Koko näyttö", self.toggle_fullscreen)
        menu.exec(QCursor.pos())

    # ============================================================ Näkymät
    def _ass_color(self, hexcol):
        c = QColor(hexcol)
        return f"&H{c.blue():02X}{c.green():02X}{c.red():02X}&"

    def show_idle(self):
        a = self._ass_color(self.accent)
        self.video.osd(
            f"{{\\an5\\fs58\\bord0\\1c{a}}}Mediasoitin\\N"
            "{\\fs24\\1c&H8C8C8C&}Valitse tiedosto vasemmalta, raahaa tiedostoja tähän\\N"
            "tai tuplaklikkaa CD/DVD-levyä.")
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
        path = self.video.get("path") or ""
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

        if self.is_real_video():
            self.video.osd("")
            return
        has_cover = bool((self.state.get("video-params") or {}).get("w"))
        pos = "{\\an2\\bord3\\3c&H000000&}" if has_cover else "{\\an5\\bord0}"
        text = pos + "{\\fs46\\1c&HFFFFFF&}" + _ass(title)
        if artist:
            text += f"\\N{{\\fs30\\1c{self._ass_color(self.accent)}}}" + _ass(artist)
        if album:
            text += "\\N{\\fs24\\1c&H8C8C8C&}" + _ass(album)
        self.video.osd(text)

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
        QMessageBox.information(self, "Pikanäppäimet", """<table cellspacing=5>
<tr><td><b>Klikkaus videoon</b></td><td>Tauko / jatka</td></tr>
<tr><td><b>Tuplaklikkaus</b></td><td>Koko näyttö</td></tr>
<tr><td><b>Oikea klikkaus videoon</b></td><td>Valikko</td></tr>
<tr><td><b>Välilyönti</b></td><td>Tauko / jatka</td></tr>
<tr><td><b>F / F11, Esc</b></td><td>Koko näyttö, poistu</td></tr>
<tr><td><b>← →</b> (videolla)</td><td>Kelaa 5 s</td></tr>
<tr><td><b>Shift + ← →</b></td><td>Kelaa 10 s</td></tr>
<tr><td><b>Ctrl + ← →</b></td><td>Edellinen / seuraava</td></tr>
<tr><td><b>↑ ↓ / rulla</b> (videolla)</td><td>Äänenvoimakkuus</td></tr>
<tr><td><b>Ctrl + ↑ ↓</b></td><td>Äänenvoimakkuus</td></tr>
<tr><td><b>M</b></td><td>Mykistä</td></tr>
<tr><td><b>Ctrl + 1 / 2 / 0</b></td><td>Lähteet / soittolista / vain video</td></tr>
<tr><td><b>Ctrl + I</b></td><td>Tiedoston tekniset tiedot</td></tr>
</table>""")

    def about(self):
        QMessageBox.about(self, "Tietoja", f"<b>Mediasoitin {__version__}</b><br><br>"
                          "Toistomoottori: mpv / libmpv (FFmpeg).<br>"
                          "Toistaa tiedostot, musiikki-CD:t, DVD:t ja ulkoiset levyt.")

    # ======================================================== Koko näyttö
    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self._was_max = self.isMaximized()
            self.split_left.hide()
            self.playlist_panel.hide()
            self.menuBar().hide()
            self.statusBar().hide()
            self.bottom_ov.lay.addWidget(self.controls)   # ohjaimet kelluvaan palkkiin
            self.controls.show()
            self.showFullScreen()
            self._last_cursor = QCursor.pos()
            QTimer.singleShot(150, self._show_overlays)
            self.mouse_timer.start()
        else:
            self.mouse_timer.stop()
            self.hide_timer.stop()
            self.top_ov.hide()
            self.bottom_ov.hide()
            self.central_layout.addWidget(self.controls)  # takaisin ikkunan alareunaan
            self.controls.show()
            self.split_left.setVisible(self.lib_action.isChecked())
            self.playlist_panel.setVisible(self.pl_action.isChecked())
            self.menuBar().show()
            self.statusBar().setVisible(self.status_action.isChecked())
            self.showMaximized() if getattr(self, "_was_max", False) else self.showNormal()
            self.video.set("cursor-autohide", 1500)
        self.refresh_icons()

    def _place_overlays(self):
        g = self.geometry()
        th = self.top_ov.sizeHint().height()
        bh = max(self.controls.sizeHint().height(), 52)
        self.top_ov.setGeometry(g.x(), g.y(), g.width(), th)
        self.bottom_ov.setGeometry(g.x(), g.y() + g.height() - bh, g.width(), bh)

    def _show_overlays(self):
        if not self.fullscreen:
            return
        self._place_overlays()
        self.top_ov.show()
        self.bottom_ov.show()
        self.top_ov.raise_()
        self.bottom_ov.raise_()
        self.video.set("cursor-autohide", "no")
        self.hide_timer.start()

    def _maybe_hide_overlays(self):
        if not self.fullscreen:
            return
        pos = QCursor.pos()
        over = self.top_ov.geometry().contains(pos) or self.bottom_ov.geometry().contains(pos)
        if over or QApplication.activePopupWidget() or self.seek_slider.dragging:
            self.hide_timer.start()  # hiiri palkin päällä tai valikko auki: pidetään näkyvissä
            return
        self.top_ov.hide()
        self.bottom_ov.hide()
        self.video.set("cursor-autohide", "always")  # piilota myös hiiren osoitin

    def _poll_mouse(self):
        pos = QCursor.pos()
        if pos != self._last_cursor:
            self._last_cursor = pos
            if not self.bottom_ov.isVisible():
                self._show_overlays()
            else:
                self.hide_timer.start()

    def changeEvent(self, e):
        # Jos koko näytöstä poistutaan muuta kautta (esim. Win-näppäin), siivotaan tila
        super().changeEvent(e)
        if e.type() == e.Type.WindowStateChange and self.fullscreen and not self.isFullScreen():
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
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("split_main", self.split_main.saveState())
        self.settings.setValue("split_left", self.split_left.saveState())
        self.settings.setValue("volume", self.vol_slider.value())
        self.top_ov.close()
        self.bottom_ov.close()
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
    settings = QSettings("Mediasoitin", "Mediasoitin")
    theme.apply(app, settings.value("accent", theme.DEFAULT_ACCENT, type=str))
    files = [a for a in sys.argv[1:] if not a.startswith("-")]
    w = MainWindow(files)
    w.show()
    sys.exit(app.exec())
