"""Mediasoittimen pääikkuna."""
import sys
from pathlib import Path

from PySide6.QtCore import QDir, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFileSystemModel, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QSlider, QSplitter, QStyle, QToolButton, QTreeView, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget, QAbstractItemView, QCheckBox,
)

from . import __version__, cdaudio
from .drives import OPTICAL, REMOVABLE, NETWORK, list_drives, quick_locations
from .media import (NAME_FILTERS, cda_track_number, describe_format, display_name,
                    fmt_time, media_in_folder)
from .player import MpvWidget

IS_WIN = sys.platform == "win32"


class SeekSlider(QSlider):
    """Aikajana: klikkaus hyppää suoraan kohtaan."""
    seek = Signal(float)

    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.dragging = False
        self.setRange(0, 0)

    def _value_at(self, e):
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
                                              int(e.position().x()), max(1, self.width()))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.maximum() > 0:
            self.dragging = True
            self.setValue(self._value_at(e))
            e.accept()

    def mouseMoveEvent(self, e):
        if self.dragging:
            self.setValue(self._value_at(e))

    def mouseReleaseEvent(self, e):
        if self.dragging:
            self.dragging = False
            self.seek.emit(self.value() / 1000.0)


class MainWindow(QMainWindow):
    def __init__(self, files=None):
        super().__init__()
        self.settings = QSettings("Mediasoitin", "Mediasoitin")
        self.state = {}             # mpv:n viimeisimmät ominaisuusarvot
        self.playlist = []
        self.pending_chapter = None
        self.fullscreen = False
        self._drive_sig = None

        self.setWindowTitle("Mediasoitin")
        self.setWindowIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
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

        sig = self.video.signals
        sig.prop.connect(self.on_prop)
        sig.end_file.connect(self.on_end_file)
        sig.file_loaded.connect(self.on_file_loaded)
        sig.key.connect(self.on_video_key)

        self.refresh_drives()
        QTimer.singleShot(300, self.show_idle)
        self.drive_timer = QTimer(self, interval=3000, timeout=self.refresh_drives)
        self.drive_timer.start()

        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        for name, sp in (("split_main", self.split_main), ("split_left", self.split_left)):
            st = self.settings.value(name)
            if st is not None:
                sp.restoreState(st)

        start = self.settings.value("last_dir", "", type=str)
        if start and Path(start).is_dir():
            self.browse(start)

        if files:
            QTimer.singleShot(200, lambda: self.add_paths(files, play=True))

    # ------------------------------------------------------------------ UI
    def icon(self, sp):
        return self.style().standardIcon(sp)

    def _build_ui(self):
        # --- Vasen: asemat + tiedostoselain
        self.drive_tree = QTreeWidget()
        self.drive_tree.setHeaderHidden(True)
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
        self.file_view.setDragEnabled(True)
        for c in (2, 3):
            self.file_view.hideColumn(c)
        self.file_view.setColumnWidth(0, 260)
        self.file_view.doubleClicked.connect(self.on_file_double)
        self.file_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_view.customContextMenuRequested.connect(self.file_menu)

        self.path_label = QLabel("Valitse asema tai kansio")
        self.path_label.setWordWrap(True)
        self.path_label.setStyleSheet("color:#aaa; padding:2px;")
        up = QToolButton(icon=self.icon(QStyle.SP_FileDialogToParent), toolTip="Ylös")
        up.clicked.connect(self.browse_up)
        play_dir = QToolButton(icon=self.icon(QStyle.SP_MediaPlay), toolTip="Toista tämä kansio")
        play_dir.clicked.connect(lambda: self.play_folder(self.current_dir, recursive=True))
        path_row = QHBoxLayout()
        path_row.addWidget(up)
        path_row.addWidget(self.path_label, 1)
        path_row.addWidget(play_dir)
        file_box = QWidget()
        fl = QVBoxLayout(file_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addLayout(path_row)
        fl.addWidget(self.file_view)

        self.split_left = QSplitter(Qt.Vertical)
        self.split_left.addWidget(self.drive_tree)
        self.split_left.addWidget(file_box)
        self.split_left.setSizes([200, 500])
        self.current_dir = ""

        # --- Keskellä: video. Pidetään aina näkyvissä (mpv piirtää suoraan siihen);
        # äänitiedostoille kappaleen tiedot näytetään tekstikerroksena.
        self.video.setContextMenuPolicy(Qt.NoContextMenu)

        # --- Oikea: soittolista
        self.pl_view = QListWidget()
        self.pl_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.pl_view.itemDoubleClicked.connect(
            lambda it: self.video.cmd("playlist-play-index", self.pl_view.row(it)))
        self.pl_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pl_view.customContextMenuRequested.connect(self.playlist_menu)
        self.pl_title = QLabel("<b>Soittolista</b>")

        def tb(sp_or_text, tip, slot):
            b = QToolButton(toolTip=tip)
            if isinstance(sp_or_text, str):
                b.setText(sp_or_text)
            else:
                b.setIcon(self.icon(sp_or_text))
            b.clicked.connect(slot)
            return b

        self.repeat_btn = tb("🔁", "Toisto: pois", self.cycle_repeat)
        pl_btns = QHBoxLayout()
        for w in (
            tb("+", "Lisää tiedostoja", self.open_files_dialog),
            tb(QStyle.SP_DirOpenIcon, "Lisää kansio", self.open_folder_dialog),
            tb(QStyle.SP_ArrowUp, "Siirrä ylös", lambda: self.move_selected(-1)),
            tb(QStyle.SP_ArrowDown, "Siirrä alas", lambda: self.move_selected(1)),
            tb(QStyle.SP_DialogDiscardButton, "Poista valitut (Del)", self.remove_selected),
            tb(QStyle.SP_TrashIcon, "Tyhjennä soittolista", self.clear_playlist),
            tb("🔀", "Sekoita", lambda: self.video.cmd("playlist-shuffle")),
            self.repeat_btn,
        ):
            pl_btns.addWidget(w)
        pl_btns.addStretch()
        pl_box = QWidget()
        pll = QVBoxLayout(pl_box)
        pll.setContentsMargins(0, 0, 0, 0)
        pll.addWidget(self.pl_title)
        pll.addWidget(self.pl_view)
        pll.addLayout(pl_btns)

        self.split_main = QSplitter(Qt.Horizontal)
        self.split_main.addWidget(self.split_left)
        self.split_main.addWidget(self.video)
        self.split_main.addWidget(pl_box)
        self.split_main.setStretchFactor(1, 1)
        self.split_main.setSizes([300, 700, 280])

        # --- Alhaalla: ohjaimet
        self.prev_btn = tb(QStyle.SP_MediaSkipBackward, "Edellinen", self.prev)
        self.play_btn = tb(QStyle.SP_MediaPlay, "Toista / tauko (välilyönti)", self.toggle_pause)
        self.stop_btn = tb(QStyle.SP_MediaStop, "Pysäytä", self.stop)
        self.next_btn = tb(QStyle.SP_MediaSkipForward, "Seuraava", self.next)
        for b in (self.prev_btn, self.play_btn, self.stop_btn, self.next_btn):
            b.setIconSize(b.iconSize() * 1.4)
        self.pos_label = QLabel("--:--")
        self.dur_label = QLabel("--:--")
        self.seek_slider = SeekSlider()
        self.seek_slider.seek.connect(lambda s: self.video.cmd("seek", s, "absolute+exact"))
        self.seek_slider.valueChanged.connect(
            lambda v: self.seek_slider.dragging and self.pos_label.setText(fmt_time(v / 1000)))
        self.chapter_box = QComboBox(toolTip="Kappale / luku")
        self.chapter_box.setMinimumWidth(160)
        self.chapter_box.activated.connect(lambda i: self.video.set("chapter", i))
        self.chapter_box.hide()
        self.mute_btn = tb(QStyle.SP_MediaVolume, "Mykistä (M)", lambda: self.video.cmd("cycle", "mute"))
        self.vol_slider = QSlider(Qt.Horizontal, toolTip="Äänenvoimakkuus")
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setFixedWidth(110)
        self.vol_slider.setValue(self.settings.value("volume", 100, type=int))
        self.vol_slider.valueChanged.connect(lambda v: self.video.set("volume", float(v)))
        self.vol_label = QLabel("100 %")
        self.vol_label.setFixedWidth(42)
        self.bp_check = QCheckBox("Bit-perfect")
        self.bp_check.setToolTip(
            "WASAPI exclusive -tila: ääni menee äänikortille sellaisenaan,\n"
            "ilman Windowsin miksausta tai näytteenottotaajuuden muunnosta.\n"
            "Muiden ohjelmien äänet eivät kuulu sillä aikaa.\n"
            "Pidä soittimen äänenvoimakkuus 100 %:ssa ja säädä vahvistimesta.")
        self.bp_check.setChecked(self.settings.value("exclusive", False, type=bool))
        self.bp_check.toggled.connect(self.set_exclusive)
        self.bp_check.setVisible(IS_WIN)
        self.fs_btn = tb(QStyle.SP_TitleBarMaxButton, "Koko näyttö (F / tuplaklikkaus)", self.toggle_fullscreen)

        controls = QWidget()
        cl = QHBoxLayout(controls)
        cl.setContentsMargins(6, 4, 6, 4)
        for w in (self.prev_btn, self.play_btn, self.stop_btn, self.next_btn, self.pos_label):
            cl.addWidget(w)
        cl.addWidget(self.seek_slider, 1)
        for w in (self.dur_label, self.chapter_box, self.mute_btn, self.vol_slider,
                  self.vol_label, self.bp_check, self.fs_btn):
            cl.addWidget(w)
        self.controls = controls

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(4, 4, 4, 0)
        lay.setSpacing(2)
        lay.addWidget(self.split_main, 1)
        lay.addWidget(controls)
        self.setCentralWidget(central)

        # --- Tilarivi
        self.format_label = QLabel("")
        self.bp_label = QLabel("")
        self.statusBar().addWidget(self.format_label, 1)
        self.statusBar().addPermanentWidget(self.bp_label)

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&Tiedosto")
        m.addAction("Avaa tiedostoja…", QKeySequence.Open, self.open_files_dialog)
        m.addAction("Avaa kansio…", QKeySequence("Ctrl+Shift+O"), self.open_folder_dialog)
        self.disc_menu = m.addMenu("Toista levy")
        self.disc_menu.aboutToShow.connect(self.fill_disc_menu)
        m.addSeparator()
        m.addAction("Lopeta", QKeySequence.Quit, self.close)

        m = mb.addMenu("T&oisto")
        m.addAction("Toista / tauko", self.toggle_pause)
        m.addAction("Pysäytä", self.stop)
        m.addAction("Edellinen", QKeySequence("Ctrl+Left"), self.prev)
        m.addAction("Seuraava", QKeySequence("Ctrl+Right"), self.next)
        m.addSeparator()
        self.audio_menu = m.addMenu("Ääniraita")
        self.sub_menu = m.addMenu("Tekstitys")
        m.addAction("Lataa tekstitystiedosto…", self.load_subtitle)

        m = mb.addMenu("Ää&ni")
        self.excl_action = QAction("Bit-perfect (WASAPI exclusive)", self, checkable=True)
        self.excl_action.setChecked(self.bp_check.isChecked())
        self.excl_action.toggled.connect(self.bp_check.setChecked)
        self.excl_action.setEnabled(IS_WIN)
        m.addAction(self.excl_action)
        self.device_menu = m.addMenu("Äänilaite")
        self.device_menu.aboutToShow.connect(self.fill_device_menu)

        m = mb.addMenu("&Näytä")
        m.addAction("Koko näyttö", QKeySequence("F11"), self.toggle_fullscreen)
        self.show_all_action = QAction("Näytä kaikki tiedostot (myös tuntemattomat)", self, checkable=True)
        self.show_all_action.setChecked(self.settings.value("show_all", False, type=bool))
        self.show_all_action.toggled.connect(self.set_show_all)
        m.addAction(self.show_all_action)
        self.set_show_all(self.show_all_action.isChecked())
        m.addAction("Tiedoston tiedot", QKeySequence("Ctrl+I"), self.show_file_info)

        m = mb.addMenu("&Ohje")
        m.addAction("Tietoja", self.about)

    def _build_shortcuts(self):
        def sc(key, slot, ctx=Qt.WindowShortcut):
            s = QShortcut(QKeySequence(key), self, slot)
            s.setContext(ctx)
        sc(Qt.Key_Space, self.toggle_pause)
        sc("F", self.toggle_fullscreen)
        sc(Qt.Key_Escape, lambda: self.fullscreen and self.toggle_fullscreen())
        sc("M", lambda: self.video.cmd("cycle", "mute"))
        sc(Qt.Key_Delete, self.remove_selected)
        sc("Shift+Right", lambda: self.video.cmd("seek", 10))
        sc("Shift+Left", lambda: self.video.cmd("seek", -10))
        sc("Ctrl+Up", lambda: self.video.cmd("add", "volume", 5))
        sc("Ctrl+Down", lambda: self.video.cmd("add", "volume", -5))
        sc(Qt.Key_MediaTogglePlayPause, self.toggle_pause)
        sc(Qt.Key_MediaPlay, self.toggle_pause)
        sc(Qt.Key_MediaPause, self.toggle_pause)
        sc(Qt.Key_MediaStop, self.stop)
        sc(Qt.Key_MediaNext, self.next)
        sc(Qt.Key_MediaPrevious, self.prev)

    # --------------------------------------------------------- Asemat
    def refresh_drives(self):
        drives = list_drives()
        sig = tuple((d.root, d.label, d.ready, d.disc) for d in drives)
        if sig == self._drive_sig:
            return
        self._drive_sig = sig
        self.drive_tree.clear()
        top = QTreeWidgetItem(self.drive_tree, ["Asemat"])
        top.setIcon(0, self.icon(QStyle.SP_ComputerIcon))
        for d in drives:
            ic = {OPTICAL: QStyle.SP_DriveCDIcon, REMOVABLE: QStyle.SP_DriveFDIcon,
                  NETWORK: QStyle.SP_DriveNetIcon}.get(d.kind, QStyle.SP_DriveHDIcon)
            it = QTreeWidgetItem(top, [d.title])
            it.setIcon(0, self.icon(ic))
            it.setData(0, Qt.UserRole, d)
            if d.disc:
                it.setToolTip(0, "Tuplaklikkaa toistaaksesi levyn")
        top.setExpanded(True)
        locs = quick_locations()
        if locs:
            q = QTreeWidgetItem(self.drive_tree, ["Pikasijainnit"])
            q.setIcon(0, self.icon(QStyle.SP_DirLinkIcon))
            for name, path in locs:
                it = QTreeWidgetItem(q, [name])
                it.setIcon(0, self.icon(QStyle.SP_DirIcon))
                it.setData(0, Qt.UserRole, path)
            q.setExpanded(True)

    def on_drive_clicked(self, item, _col=0):
        d = item.data(0, Qt.UserRole)
        if d is None:
            return
        if isinstance(d, str):
            self.browse(d)
        elif d.ready:
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
            a = self.disc_menu.addAction("Ei levyä asemassa")
            a.setEnabled(False)
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

    # --------------------------------------------------- Tiedostoselain
    def browse(self, path):
        path = str(path)
        self.current_dir = path
        self.file_view.setRootIndex(self.fs_model.index(path))
        self.path_label.setText(path)
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
        rows = self.file_view.selectionModel().selectedRows(0)
        return [self.fs_model.filePath(i) for i in rows]

    def on_file_double(self, index):
        path = self.fs_model.filePath(index)
        if self.fs_model.isDir(index):
            if (Path(path) / "VIDEO_TS").is_dir() or Path(path).name.upper() == "VIDEO_TS":
                root = path if Path(path).name.upper() != "VIDEO_TS" else str(Path(path).parent)
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

    # ------------------------------------------------------- Toisto
    def special(self, path):
        """Käsittele CD-raita (.cda) ja levykuva (.iso). Palauttaa True jos käsitelty."""
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
            # Muut käyttöjärjestelmät: mpv:n oma CD-tuki (libcdio)
            self.video.set("cdrom-device", device)
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
        # Pysäytä mutta säilytä soittolista
        self.video.cmd("playlist-play-index", "none")

    def has_chapters(self):
        return len(self.state.get("chapter-list") or []) > 1

    def next(self):
        if self.has_chapters():
            self.video.cmd("add", "chapter", 1)
        else:
            self.video.cmd("playlist-next")

    def prev(self):
        t = self.state.get("time-pos") or 0
        if self.has_chapters():
            self.video.cmd("add", "chapter", -1)
        elif t > 3:
            self.video.cmd("seek", 0, "absolute")
        else:
            self.video.cmd("playlist-prev")

    def cycle_repeat(self):
        lp, lf = self.state.get("loop-playlist"), self.state.get("loop-file")
        if lf not in (False, None, "no"):
            self.video.set("loop-file", "no")
            self.video.set("loop-playlist", "no")
        elif lp not in (False, None, "no"):
            self.video.set("loop-playlist", "no")
            self.video.set("loop-file", "inf")
        else:
            self.video.set("loop-playlist", "inf")

    def update_repeat_btn(self):
        lp, lf = self.state.get("loop-playlist"), self.state.get("loop-file")
        if lf not in (False, None, "no"):
            self.repeat_btn.setText("🔂")
            self.repeat_btn.setToolTip("Toisto: tämä kappale")
            self.repeat_btn.setStyleSheet("color:#4fc3f7;")
        elif lp not in (False, None, "no"):
            self.repeat_btn.setText("🔁")
            self.repeat_btn.setToolTip("Toisto: koko soittolista")
            self.repeat_btn.setStyleSheet("color:#4fc3f7;")
        else:
            self.repeat_btn.setText("🔁")
            self.repeat_btn.setToolTip("Toisto: pois")
            self.repeat_btn.setStyleSheet("")

    def set_exclusive(self, on):
        self.excl_action.setChecked(on)
        self.settings.setValue("exclusive", on)
        self.video.set_exclusive(on)
        self.update_audio_info()

    def load_subtitle(self):
        f, _ = QFileDialog.getOpenFileName(self, "Lataa tekstitys", self.current_dir,
                                           "Tekstitykset (*.srt *.ass *.ssa *.sub *.vtt *.sup *.idx);;Kaikki (*)")
        if f:
            self.video.cmd("sub-add", f, "select")

    # ----------------------------------------------------- Soittolista
    def rebuild_playlist(self):
        selected = {self.pl_view.row(i) for i in self.pl_view.selectedItems()}
        self.pl_view.clear()
        bold = self.pl_view.font()
        bold.setBold(True)
        for i, e in enumerate(self.playlist):
            name = display_name(e)
            it = QListWidgetItem(f"{i + 1}. {name}")
            it.setToolTip(e.get("filename", ""))
            if e.get("current"):
                it.setFont(bold)
                it.setText("▶ " + it.text())
                it.setForeground(QColor("#4fc3f7"))
            self.pl_view.addItem(it)
            if i in selected:
                it.setSelected(True)
        self.pl_title.setText(f"<b>Soittolista</b> ({len(self.playlist)})")

    def remove_selected(self):
        rows = sorted((self.pl_view.row(i) for i in self.pl_view.selectedItems()), reverse=True)
        for r in rows:
            self.video.cmd("playlist-remove", r)

    def move_selected(self, delta):
        rows = sorted(self.pl_view.row(i) for i in self.pl_view.selectedItems())
        if not rows:
            return
        n = len(self.playlist)
        if delta < 0 and rows[0] == 0 or delta > 0 and rows[-1] == n - 1:
            return
        order = rows if delta < 0 else list(reversed(rows))
        for r in order:
            # playlist-move a b: siirtää kohdan a paikan b eteen
            self.video.cmd("playlist-move", r, r - 1 if delta < 0 else r + 2)
        QTimer.singleShot(50, lambda: [self.pl_view.item(r + delta).setSelected(True)
                                       for r in rows if self.pl_view.item(r + delta)])

    def clear_playlist(self):
        self.video.cmd("stop")
        self.video.cmd("playlist-clear")

    def playlist_menu(self, pos):
        menu = QMenu(self)
        it = self.pl_view.itemAt(pos)
        if it:
            menu.addAction("Toista", lambda: self.video.cmd("playlist-play-index", self.pl_view.row(it)))
            menu.addAction("Poista", self.remove_selected)
            menu.addSeparator()
        menu.addAction("Sekoita", lambda: self.video.cmd("playlist-shuffle"))
        menu.addAction("Järjestä aakkosjärjestykseen", self.sort_playlist)
        menu.addAction("Tyhjennä", self.clear_playlist)
        menu.exec(self.pl_view.viewport().mapToGlobal(pos))

    def sort_playlist(self):
        from .media import natural_key
        files = sorted((e["filename"] for e in self.playlist), key=natural_key)
        # siirrä järjestykseen
        for target, fn in enumerate(files):
            now = [e["filename"] for e in self.playlist]
            src = now.index(fn, target)
            if src != target:
                self.video.cmd("playlist-move", src, target)
                moved = self.playlist.pop(src)
                self.playlist.insert(target, moved)

    # ----------------------------------------------------- mpv-tapahtumat
    def on_prop(self, name, value):
        self.state[name] = value
        if name == "time-pos":
            if not self.seek_slider.dragging:
                self.seek_slider.blockSignals(True)
                self.seek_slider.setValue(int((value or 0) * 1000))
                self.seek_slider.blockSignals(False)
                self.pos_label.setText(fmt_time(value))
        elif name == "duration":
            self.seek_slider.setRange(0, int((value or 0) * 1000))
            self.dur_label.setText(fmt_time(value))
        elif name == "pause":
            self.play_btn.setIcon(self.icon(QStyle.SP_MediaPlay if value else QStyle.SP_MediaPause))
        elif name == "idle-active":
            if not value:
                self.play_btn.setIcon(self.icon(
                    QStyle.SP_MediaPlay if self.state.get("pause") else QStyle.SP_MediaPause))
            if value:
                self.show_idle()
                self.seek_slider.setRange(0, 0)
                self.pos_label.setText("--:--")
                self.dur_label.setText("--:--")
                self.play_btn.setIcon(self.icon(QStyle.SP_MediaPlay))
                self.chapter_box.hide()
                self.format_label.setText("")
                self.bp_label.setText("")
        elif name == "playlist":
            self.playlist = value or []
            self.rebuild_playlist()
        elif name in ("media-title", "metadata"):
            self.update_now_playing()
        elif name == "chapter-list":
            self.chapter_box.clear()
            chs = value or []
            for i, c in enumerate(chs):
                title = c.get("title") or f"Kappale {i + 1}"
                if title.isdigit() or title.startswith("Track"):
                    title = f"Kappale {i + 1}"
                self.chapter_box.addItem(f"{i + 1}. {title}  ({fmt_time(c.get('time'))})")
            self.chapter_box.setVisible(len(chs) > 1)
        elif name == "chapter":
            if value is not None and 0 <= value < self.chapter_box.count():
                self.chapter_box.setCurrentIndex(value)
            self.update_now_playing()
        elif name == "track-list":
            self.rebuild_track_menus(value or [])
            self.update_now_playing()
        elif name == "volume":
            v = int(round(value or 0))
            self.vol_slider.blockSignals(True)
            self.vol_slider.setValue(v)
            self.vol_slider.blockSignals(False)
            self.vol_label.setText(f"{v} %")
            self.update_audio_info()
        elif name == "mute":
            self.mute_btn.setIcon(self.icon(QStyle.SP_MediaVolumeMuted if value else QStyle.SP_MediaVolume))
            self.update_audio_info()
        elif name == "video-params":
            self.update_now_playing()
            self.update_audio_info()
        elif name in ("audio-params", "audio-out-params", "audio-codec-name", "current-ao",
                      "af", "audio-exclusive", "video-codec", "hwdec-current"):
            self.update_audio_info()
        elif name in ("loop-playlist", "loop-file"):
            self.update_repeat_btn()

    def on_file_loaded(self):
        if self.pending_chapter is not None:
            ch = self.pending_chapter
            self.pending_chapter = None
            QTimer.singleShot(100, lambda: self.video.set("chapter", ch))
        self.update_now_playing()

    def on_end_file(self, reason, error, entry_id):
        if reason == "error":
            name = next((display_name(e) for e in self.playlist if str(e.get("id")) == entry_id), "")
            msg = f"Toisto epäonnistui: {name}" + (f" ({error})" if error else "")
            if name.lower().endswith((".cda",)) or "cdda" in name.lower():
                msg += " – onko CD asemassa?"
            self.statusBar().showMessage(msg, 10000)

    def on_video_key(self, key):
        actions = {
            "MBTN_LEFT_DBL": self.toggle_fullscreen, "f": self.toggle_fullscreen,
            "F": self.toggle_fullscreen, "SPACE": self.toggle_pause, "MBTN_RIGHT": self.toggle_pause,
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

    # ----------------------------------------------------- Näkymät
    def show_idle(self):
        self.video.osd(
            "{\\an5\\fs54\\bord0\\1c&HFFFFFF&}Mediasoitin\\N"
            "{\\fs26\\1c&HAAAAAA&}Valitse tiedosto vasemmalta, raahaa tiedostoja tähän\\N"
            "tai tuplaklikkaa CD/DVD-levyä asemaluettelossa.")
        self.setWindowTitle("Mediasoitin")

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
            title = f"{title} – " + (self.chapter_box.itemText(ch).split("  (")[0])
        self.setWindowTitle(f"{title} – Mediasoitin" if title else "Mediasoitin")

        if self.is_real_video():
            self.video.osd("")
            return
        has_cover = bool((self.state.get("video-params") or {}).get("w"))
        pos = "{\\an2\\bord3\\3c&H000000&}" if has_cover else "{\\an5\\bord0}"
        text = pos + "{\\fs48\\1c&HFFFFFF&}" + _ass(title)
        if artist:
            text += "\\N{\\fs32\\1c&HDDDDDD&}" + _ass(artist)
        if album:
            text += "\\N{\\fs26\\1c&H999999&}" + _ass(album)
        self.video.osd(text)

    def update_audio_info(self):
        ap = self.state.get("audio-params")
        vp = self.state.get("video-params")
        parts = []
        if ap:
            codec = (self.state.get("audio-codec-name") or "").upper()
            sr = ap.get("samplerate") or 0
            parts.append(f"Ääni: {codec} · {sr / 1000:g} kHz · {describe_format(ap.get('format'))}"
                         f" · {ap.get('channel-count')} kan.")
        if vp and vp.get("w"):
            vc = (self.state.get("video-codec") or "").split(" ")[0]
            s = f"Kuva: {vc} {vp.get('w')}×{vp.get('h')}"
            if vp.get("gamma") in ("pq", "hlg"):
                s += " HDR"
            hw = self.state.get("hwdec-current")
            if hw and hw != "no":
                s += f" (laitteisto: {hw})"
            parts.append(s)
        self.format_label.setText("     ".join(parts))

        if not ap or not IS_WIN:
            self.bp_label.setText("")
            return
        op = self.state.get("audio-out-params") or {}
        excl = self.state.get("audio-exclusive") in (True, "yes")
        reasons = []
        if not excl:
            reasons.append("Jaettu tila: Windows miksaa äänen ja voi muuntaa näytteenottotaajuuden.")
        if op and op.get("samplerate") and op.get("samplerate") != ap.get("samplerate"):
            reasons.append(f"Näytteenottotaajuus muunnetaan: {ap.get('samplerate')} → {op.get('samplerate')} Hz "
                           "(äänikortti ei tue alkuperäistä).")
        if op and op.get("channel-count") and op.get("channel-count") != ap.get("channel-count"):
            reasons.append("Kanavamäärä muunnetaan äänikortille sopivaksi.")
        if (self.state.get("volume") or 100) < 100 or self.state.get("mute"):
            reasons.append("Äänenvoimakkuus alle 100 % muuttaa signaalia.")
        if self.state.get("af"):
            reasons.append("Äänisuodattimia käytössä.")
        if reasons:
            self.bp_label.setText("<span style='color:#ffb74d;'>●</span> Ei bit-perfect")
            self.bp_label.setToolTip("\n".join(reasons))
        else:
            out_sr = op.get("samplerate") or ap.get("samplerate")
            self.bp_label.setText(f"<span style='color:#66bb6a;'>●</span> Bit-perfect {out_sr / 1000:g} kHz")
            self.bp_label.setToolTip("Ääni menee äänikortille muuttamattomana (WASAPI exclusive).")

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
            desc = dev.get("description") or name
            if name == "auto":
                desc = "Oletuslaite (Windows)"
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

    def about(self):
        QMessageBox.about(self, "Tietoja", f"<b>Mediasoitin {__version__}</b><br><br>"
                          "Toistomoottori: mpv / libmpv (FFmpeg).<br>"
                          "Toistaa tiedostot, musiikki-CD:t, DVD:t ja ulkoiset levyt.")

    # ----------------------------------------------------- Koko näyttö
    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        for w in (self.split_left, self.split_main.widget(2)):
            w.setVisible(not self.fullscreen)
        self.menuBar().setVisible(not self.fullscreen)
        self.statusBar().setVisible(not self.fullscreen)
        if self.fullscreen:
            self._was_max = self.isMaximized()
            self.showFullScreen()
        else:
            self.showMaximized() if getattr(self, "_was_max", False) else self.showNormal()

    # ----------------------------------------------------- Raahaa ja pudota
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.add_paths(paths, play=True)

    def closeEvent(self, e):
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


def dark_palette(app):
    app.setStyle("Fusion")
    p = QPalette()
    base, alt, text = QColor(30, 30, 32), QColor(42, 42, 46), QColor(225, 225, 225)
    p.setColor(QPalette.Window, alt)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, alt)
    p.setColor(QPalette.ToolTipBase, QColor(50, 50, 55))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, alt)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.Highlight, QColor(41, 121, 255))
    p.setColor(QPalette.HighlightedText, Qt.white)
    p.setColor(QPalette.PlaceholderText, QColor(140, 140, 140))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(120, 120, 120))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 120, 120))
    app.setPalette(p)


def main():
    import locale
    app = QApplication(sys.argv)
    locale.setlocale(locale.LC_NUMERIC, "C")  # mpv vaatii tämän
    app.setApplicationName("Mediasoitin")
    dark_palette(app)
    files = [a for a in sys.argv[1:] if not a.startswith("-")]
    w = MainWindow(files)
    w.show()
    sys.exit(app.exec())
