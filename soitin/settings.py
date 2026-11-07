"""Asetukset: oletusarvot, pikanäppäimet ja asetusikkuna."""
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QHeaderView, QKeySequenceEdit, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTabWidget, QVBoxLayout, QWidget,
)

from . import theme

# ------------------------------------------------------------------ Oletukset
DEFAULTS = {
    # Toisto
    "seek_short": 5,             # s, nuolinäppäimet
    "seek_long": 30,             # s, Shift + nuoli
    "volume_step": 5,            # %
    "wheel_action": "volume",    # volume / seek
    "click_action": "pause",     # pause / none
    "dblclick_action": "fullscreen",  # fullscreen / none
    "queue_folder": True,        # tuplaklikkaus laittaa kansion muut tiedostot jonoon
    "resume": False,             # jatka siitä mihin jäit
    "auto_fullscreen": False,    # koko näyttö kun video alkaa
    "hide_delay": 2.5,           # s, koko näytön palkit piiloon
    "hold_speed": 2.0,           # kelausnäppäin pohjassa -> nopeutettu toisto (0 = pois)
    "auto_next": True,           # seuraava jakso automaattisesti
    "next_offer": 20,            # s ennen loppua: "Seuraava jakso" -kortti (lopputekstien ohitus)
    "next_countdown": 10,        # s laskuri kortissa
    "intro_mode": "button",      # off / button / auto  (alkutunnarin ohitus)
    # Muut
    "check_updates": True,
    "remote_enabled": False,
    "remote_port": 8765,
    "close_to_tray": True,       # ikkunan sulkeminen jättää soittimen ilmaisinalueelle
    "autostart": False,          # käynnistyy Windowsin mukana taustalle (todellinen tila rekisterissä)
    # Ääni
    "exclusive": False,
    "alang": "fin,fi,eng,en",
    "remember_volume": True,
    # Kuva
    "quality": "high-quality",   # high-quality / default / fast
    "hwdec": True,
    # Tekstitys
    "slang": "fin,fi,eng,en",
    "sub_auto": True,
    "sub_smart": True,           # suomi-tekstitys vain, jos puhe ei ole suomea
    "sub_scale": 1.0,
    # Ulkoasu
    "accent": theme.DEFAULT_ACCENT,
    "show_hint": True,
    "animations": True,
    "seek_preview": True,
}

# Toiminnot, joille voi asettaa pikanäppäimen: (tunnus, nimi, oletusnäppäin, ryhmä)
ACTIONS = [
    ("play_pause", "Toista / tauko", "Space", "Toisto"),
    ("stop", "Pysäytä", "", "Toisto"),
    ("next", "Seuraava", "Ctrl+Right", "Toisto"),
    ("prev", "Edellinen", "Ctrl+Left", "Toisto"),
    ("seek_fwd", "Kelaa eteen (lyhyt)", "Right", "Toisto"),
    ("seek_back", "Kelaa taakse (lyhyt)", "Left", "Toisto"),
    ("seek_fwd_long", "Kelaa eteen (pitkä)", "Shift+Right", "Toisto"),
    ("seek_back_long", "Kelaa taakse (pitkä)", "Shift+Left", "Toisto"),
    ("next_chapter", "Seuraava luku / CD-kappale", "PgUp", "Toisto"),
    ("prev_chapter", "Edellinen luku / CD-kappale", "PgDown", "Toisto"),
    ("frame_step", "Seuraava ruutu", ".", "Toisto"),
    ("frame_back", "Edellinen ruutu", ",", "Toisto"),
    ("speed_up", "Nopeammin", "]", "Toisto"),
    ("speed_down", "Hitaammin", "[", "Toisto"),
    ("speed_reset", "Normaali nopeus", "Backspace", "Toisto"),
    ("vol_up", "Voimakkaammin", "Up", "Ääni"),
    ("vol_down", "Hiljemmin", "Down", "Ääni"),
    ("mute", "Mykistä", "M", "Ääni"),
    ("audio_cycle", "Vaihda ääniraitaa", "A", "Ääni"),
    ("sub_cycle", "Vaihda tekstitystä", "S", "Tekstitys"),
    ("sub_toggle", "Tekstitys päälle / pois", "V", "Tekstitys"),
    ("screenshot", "Kuvakaappaus", "Ctrl+S", "Kuva"),
    ("video_adjust", "Kuvan säädöt", "Ctrl+E", "Kuva"),
    ("aspect_cycle", "Vaihda kuvasuhdetta", "Ctrl+A", "Kuva"),
    ("fill_toggle", "Täytä ruutu (rajaa reunat)", "Z", "Kuva"),
    ("deinterlace_toggle", "Lomituksen poisto päälle / pois", "D", "Kuva"),
    ("rotate", "Kierrä kuvaa 90°", "Ctrl+R", "Kuva"),
    ("fullscreen", "Koko näyttö", "F", "Näkymä"),
    ("fullscreen_alt", "Koko näyttö (toinen näppäin)", "F11", "Näkymä"),
    ("exit_fullscreen", "Poistu koko näytöstä", "Esc", "Näkymä"),
    ("toggle_library", "Näytä / piilota lähteet", "Ctrl+1", "Näkymä"),
    ("toggle_playlist", "Näytä / piilota soittolista", "Ctrl+2", "Näkymä"),
    ("video_only", "Vain video", "Ctrl+0", "Näkymä"),
    ("file_info", "Tiedoston tekniset tiedot", "Ctrl+I", "Näkymä"),
    ("library_search", "Hae kirjastosta", "Ctrl+F", "Näkymä"),
    ("remote", "Kaukosäädin puhelimesta", "Ctrl+K", "Näkymä"),
    ("next_episode_now", "Seuraava jakso heti (ohita lopputekstit)", "N", "Toisto"),
    ("skip_intro", "Ohita alkutunnari", "I", "Toisto"),
    ("open_files", "Avaa tiedostoja", "Ctrl+O", "Tiedosto"),
    ("open_folder", "Avaa kansio", "Ctrl+Shift+O", "Tiedosto"),
    ("remove_selected", "Poista valitut soittolistasta", "Delete", "Tiedosto"),
    ("settings", "Asetukset", "Ctrl+,", "Tiedosto"),
    ("quit", "Lopeta", "Ctrl+Q", "Tiedosto"),
]


class Config:
    """Asetusten luku ja tallennus (Windowsissa rekisteriin)."""

    def __init__(self):
        self.qs = QSettings("Mediasoitin", "Mediasoitin")

    def get(self, key):
        default = DEFAULTS[key]
        return self.qs.value(f"opt/{key}", default, type=type(default))

    def set(self, key, value):
        self.qs.setValue(f"opt/{key}", value)

    def key(self, action_id):
        default = next(a[2] for a in ACTIONS if a[0] == action_id)
        return self.qs.value(f"keys/{action_id}", default, type=str)

    def set_key(self, action_id, seq):
        self.qs.setValue(f"keys/{action_id}", seq)

    def reset(self):
        self.qs.remove("opt")
        self.qs.remove("keys")


# ------------------------------------------------------------------ Ikkuna
class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Asetukset")
        self.resize(640, 560)
        self.w = {}
        self.accent = cfg.get("accent")

        tabs = QTabWidget()
        tabs.addTab(self._tab_playback(), "Toisto")
        tabs.addTab(self._tab_audio(), "Ääni")
        tabs.addTab(self._tab_video(), "Kuva")
        tabs.addTab(self._tab_subs(), "Tekstitys")
        tabs.addTab(self._tab_keys(), "Pikanäppäimet")
        tabs.addTab(self._tab_look(), "Ulkoasu")
        tabs.addTab(self._tab_other(), "Muut")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        from PySide6.QtGui import QIcon
        for b, text in ((QDialogButtonBox.Ok, "Tallenna"), (QDialogButtonBox.Cancel, "Peruuta")):
            buttons.button(b).setText(text)
            buttons.button(b).setIcon(QIcon())
        reset = buttons.addButton("Palauta kaikki oletukset", QDialogButtonBox.ResetRole)
        reset.clicked.connect(self._reset_all)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)

    # ---- apurit
    def _form(self):
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignRight)
        form.setVerticalSpacing(10)
        return page, form

    def _spin(self, key, lo, hi, suffix, decimals=0, step=1):
        sb = QDoubleSpinBox() if decimals else QSpinBox()
        if decimals:
            sb.setDecimals(decimals)
        sb.setRange(lo, hi)
        sb.setSingleStep(step)
        sb.setSuffix(suffix)
        sb.setValue(self.cfg.get(key))
        self.w[key] = sb
        return sb

    def _check(self, key, text):
        cb = QCheckBox(text)
        cb.setChecked(self.cfg.get(key))
        self.w[key] = cb
        return cb

    def _combo(self, key, options):
        cb = QComboBox()
        for value, text in options:
            cb.addItem(text, value)
        idx = cb.findData(self.cfg.get(key))
        cb.setCurrentIndex(max(0, idx))
        self.w[key] = cb
        return cb

    def _line(self, key, tip):
        le = QLineEdit(self.cfg.get(key))
        le.setToolTip(tip)
        le.setPlaceholderText(tip)
        self.w[key] = le
        return le

    @staticmethod
    def _note(text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{theme.MUTED}; font-size:9pt;")
        return lbl

    # ---- välilehdet
    def _tab_playback(self):
        page, f = self._form()
        f.addRow("Lyhyt kelaus (←  →):", self._spin("seek_short", 1, 600, " s"))
        f.addRow("Pitkä kelaus (Shift + ←  →):", self._spin("seek_long", 1, 3600, " s"))
        f.addRow("Äänenvoimakkuuden askel:", self._spin("volume_step", 1, 25, " %"))
        f.addRow("Hiiren rulla videon päällä:", self._combo(
            "wheel_action", [("volume", "Säätää äänenvoimakkuutta"), ("seek", "Kelaa (lyhyt kelaus)")]))
        f.addRow("Klikkaus videoon:", self._combo(
            "click_action", [("pause", "Tauko / jatka"), ("none", "Ei mitään")]))
        f.addRow("Tuplaklikkaus videoon:", self._combo(
            "dblclick_action", [("fullscreen", "Koko näyttö"), ("none", "Ei mitään")]))
        f.addRow("Palkit piiloon koko näytöllä:", self._spin("hide_delay", 1, 10, " s", 1, 0.5))
        f.addRow("Kelausnäppäin pohjassa:", self._combo("hold_speed", [
            (2.0, "Toista 2× nopeudella niin kauan kuin näppäin on alhaalla"),
            (1.5, "Toista 1,5× nopeudella"), (3.0, "Toista 3× nopeudella"), (0.0, "Pois (kelaa toistuvasti)")]))
        f.addRow("", self._check("queue_folder", "Tiedoston tuplaklikkaus laittaa saman kansion muut tiedostot jonoon"))
        f.addRow("", self._check("resume", "Jatka siitä mihin jäit (muistaa toistokohdan)"))
        f.addRow("", self._check("auto_fullscreen", "Siirry koko näytölle, kun video alkaa"))
        f.addRow(self._note("<b>Sarjat</b>"))
        f.addRow("", self._check("auto_next", "Toista seuraava jakso automaattisesti"))
        f.addRow("Näytä “Seuraava jakso” -kortti:", self._spin("next_offer", 5, 600, " s ennen loppua"))
        f.addRow("Laskuri ennen seuraavaa jaksoa:", self._spin("next_countdown", 3, 60, " s"))
        f.addRow("", self._note("Kortin avulla lopputekstit voi ohittaa. Jos lopputekstit ovat pitkät, "
                                "kasvata ensimmäistä aikaa (esim. 60–90 s)."))
        f.addRow("Alkutunnari:", self._combo("intro_mode", [
            ("button", "Näytä “Ohita alkutunnari” -painike"),
            ("auto", "Ohita automaattisesti"),
            ("off", "Pois (ei tunnistusta)")]))
        f.addRow("", self._note("Tunnari tunnistetaan jakson luvuista tai vertaamalla saman kansion jaksojen ääntä. "
                                "Jos ohitus osuu väärään kohtaan, valitse Pois."))
        return page

    def _tab_audio(self):
        page, f = self._form()
        f.addRow("", self._check("exclusive", "Bit-perfect (WASAPI exclusive)"))
        f.addRow("", self._note(
            "Ääni menee äänikortille muuttamattomana. Windowsin äänenvoimakkuus ei vaikuta "
            "ja muiden ohjelmien äänet eivät kuulu. Pidä soittimen voimakkuus 100 %:ssa ja "
            "säädä vahvistimesta. Laske vahvistimen voimakkuus ennen käyttöönottoa."))
        f.addRow("Ääniraidan kielet:", self._line("alang", "esim. fin,fi,eng,en"))
        f.addRow("", self._note("Valitaan automaattisesti tässä järjestyksessä, jos tiedostossa on useita ääniraitoja."))
        f.addRow("", self._check("remember_volume", "Muista äänenvoimakkuus"))
        return page

    def _tab_video(self):
        page, f = self._form()
        f.addRow("Kuvanlaatu:", self._combo("quality", [
            ("high-quality", "Paras laatu (suositus)"),
            ("default", "Normaali"),
            ("fast", "Nopea (heikot koneet)")]))
        f.addRow("", self._note("Paras laatu käyttää tarkinta skaalausta ja poistaa raidoittumista. "
                                "Jos video nykii vanhalla koneella, valitse Normaali tai Nopea."))
        f.addRow("", self._check("hwdec", "Laitteistopurku (näytönohjain purkaa videon, kuvanlaatu sama)"))
        f.addRow("", self._note("Värit, tarkennus vanhoille videoille ja HDR-säädöt: Kuva → Kuvan säädöt (Ctrl + E)."))
        return page

    def _tab_subs(self):
        page, f = self._form()
        f.addRow("Tekstityksen kielet:", self._line("slang", "esim. fin,fi,eng,en"))
        f.addRow("Tekstin koko:", self._spin("sub_scale", 0.5, 3.0, " ×", 2, 0.1))
        f.addRow("", self._check("sub_auto", "Lataa samannimiset tekstitystiedostot automaattisesti (.srt, .ass…)"))
        f.addRow("", self._check("sub_smart", "Älykäs valinta: tekstitys vain, jos puhe ei ole suomea"))
        f.addRow("", self._note("Suomenkielisessä ohjelmassa tekstitys jätetään pois, muissa valitaan suomenkielinen "
                                "tekstitys. Jos ääniraidan kieltä ei ole merkitty, käytetään yllä olevaa kielijärjestystä."))
        f.addRow("", self._note("Fontti, värit, reunus, tausta ja korkeus: Tekstitys → Tekstitysten ulkoasu…"))
        return page

    def _tab_keys(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(self._note("Klikkaa näppäinkenttää ja paina uutta näppäinyhdistelmää. "
                                 "Tyhjennä kenttä poistaaksesi pikanäppäimen."))
        self.key_table = QTableWidget(len(ACTIONS), 3)
        self.key_table.setHorizontalHeaderLabels(["Toiminto", "Näppäin", ""])
        self.key_table.verticalHeader().hide()
        self.key_table.verticalHeader().setDefaultSectionSize(38)
        self.key_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.key_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.key_table.setColumnWidth(1, 190)
        self.key_table.setColumnWidth(2, 80)
        self.key_table.setSelectionMode(QTableWidget.NoSelection)
        self.key_edits = {}
        from PySide6.QtWidgets import QTableWidgetItem
        for row, (aid, label, default, group) in enumerate(ACTIONS):
            item = QTableWidgetItem(f"{label}")
            item.setToolTip(f"Ryhmä: {group}   ·   Oletus: {default or '–'}")
            item.setFlags(Qt.ItemIsEnabled)
            self.key_table.setItem(row, 0, item)
            ed = QKeySequenceEdit(QKeySequence(self.cfg.key(aid)))
            if hasattr(ed, "setMaximumSequenceLength"):
                ed.setMaximumSequenceLength(1)
            if hasattr(ed, "setClearButtonEnabled"):
                ed.setClearButtonEnabled(True)
            self.key_table.setCellWidget(row, 1, ed)
            undo = QPushButton("Oletus")
            undo.setStyleSheet("padding: 2px 8px;")
            undo.setToolTip(f"Palauta oletus ({default or 'ei näppäintä'})")
            undo.clicked.connect(lambda _=False, e=ed, d=default: e.setKeySequence(QKeySequence(d)))
            self.key_table.setCellWidget(row, 2, undo)
            self.key_edits[aid] = ed
        lay.addWidget(self.key_table)
        btn = QPushButton("Palauta kaikki pikanäppäimet")
        btn.clicked.connect(lambda: [self.key_edits[a].setKeySequence(QKeySequence(d))
                                     for a, _, d, _ in ACTIONS])
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(btn)
        lay.addLayout(row)
        return page

    def _tab_look(self):
        page, f = self._form()
        self.accent_combo = QComboBox()
        for name, col in theme.ACCENTS:
            self.accent_combo.addItem(name, col)
        self.accent_combo.addItem("Oma väri…", "custom")
        idx = self.accent_combo.findData(self.accent)
        if idx < 0:
            self.accent_combo.setItemText(self.accent_combo.count() - 1, f"Oma väri ({self.accent})")
            idx = self.accent_combo.count() - 1
        self.accent_combo.setCurrentIndex(idx)
        self.accent_combo.activated.connect(self._accent_chosen)
        self.accent_swatch = QLabel()
        self.accent_swatch.setFixedSize(28, 28)
        self._update_swatch()
        row = QHBoxLayout()
        row.addWidget(self.accent_combo, 1)
        row.addWidget(self.accent_swatch)
        f.addRow("Korostusväri:", row)
        f.addRow("", self._check("show_hint", "Näytä ohjeteksti, kun mitään ei toisteta"))
        f.addRow("", self._check("animations", "Animaatiot (palkit liukuvat esiin ja piiloon)"))
        f.addRow("", self._check("seek_preview", "Esikatselukuva aikajanan päällä (videot)"))
        f.addRow("", self._note("Paneelien näkyvyyttä voi muuttaa Näytä-valikosta (Ctrl + 1 / 2 / 0) "
                                "ja kokoa vetämällä paneelien reunoja."))
        return page

    def _tab_other(self):
        page, f = self._form()
        f.addRow("", self._check("check_updates", "Tarkista päivitykset, kun soitin käynnistyy"))
        f.addRow("", self._note("Kun uusi versio on saatavilla, soitin kysyy luvan, lataa sen ja "
                                "käynnistyy uudelleen. Vanhaa versiota ei tarvitse poistaa itse."))
        f.addRow("Kaukosäätimen portti:", self._spin("remote_port", 1024, 65535, ""))
        f.addRow("", self._note("Kaukosäädin otetaan käyttöön kohdasta Näytä → Kaukosäädin puhelimesta."))
        f.addRow("", self._check("close_to_tray", "Ikkunan sulkeminen jättää soittimen taustalle (ilmaisinalueelle)"))
        auto = self._check("autostart", "Käynnistä Windowsin mukana taustalle")
        import sys
        auto.setEnabled(sys.platform == "win32")
        f.addRow("", auto)
        f.addRow("", self._note("Taustalla soitin ei näy, mutta puhelimen kaukosäädin toimii: voit ohjata "
                                "myös Netflixiä, YouTubea, Disney+:aa ja muita selaimessa Suoratoisto-välilehdeltä. "
                                "Automaattinen käynnistys ottaa kaukosäätimen käyttöön. Soittimen saa auki "
                                "ilmaisinalueen kuvakkeesta ja kokonaan kiinni kuvakkeen valikosta (Lopeta)."))
        return page

    def _accent_chosen(self, idx):
        data = self.accent_combo.itemData(idx)
        if data == "custom":
            c = QColorDialog.getColor(QColor(self.accent), self, "Valitse korostusväri")
            if c.isValid():
                self.accent = c.name()
                self.accent_combo.setItemText(idx, f"Oma väri ({self.accent})")
        else:
            self.accent = data
        self._update_swatch()

    def _update_swatch(self):
        self.accent_swatch.setStyleSheet(f"background:{self.accent}; border-radius:6px;")

    # ---- tallennus
    def _save(self):
        seqs = {aid: ed.keySequence().toString(QKeySequence.PortableText) for aid, ed in self.key_edits.items()}
        used = {}
        for aid, seq in seqs.items():
            if seq and seq in used:
                a = next(x[1] for x in ACTIONS if x[0] == aid)
                b = next(x[1] for x in ACTIONS if x[0] == used[seq])
                QMessageBox.warning(self, "Päällekkäinen pikanäppäin",
                                    f"Näppäin {seq} on sekä toiminnolla\n“{b}” että “{a}”.\n\nVaihda toinen niistä.")
                return
            used[seq] = aid
        for key, wdg in self.w.items():
            if isinstance(wdg, QCheckBox):
                self.cfg.set(key, wdg.isChecked())
            elif isinstance(wdg, QComboBox):
                self.cfg.set(key, wdg.currentData())
            elif isinstance(wdg, QLineEdit):
                self.cfg.set(key, wdg.text().strip())
            else:
                self.cfg.set(key, wdg.value())
        self.cfg.set("accent", self.accent)
        for aid, seq in seqs.items():
            self.cfg.set_key(aid, seq)
        self.accept()

    def _reset_all(self):
        if QMessageBox.question(self, "Palauta oletukset",
                                "Palautetaanko kaikki asetukset ja pikanäppäimet oletuksiin?") == QMessageBox.Yes:
            self.cfg.reset()
            self.accept()
