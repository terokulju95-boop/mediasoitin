"""Kuvan säädöt: värit, tarkennus vanhoille videoille ja HDR-sävykartoitus.

Muutokset näkyvät videossa heti ja tallentuvat (QSettings, ryhmä video/).
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QSlider, QTabWidget,
                               QVBoxLayout, QWidget)

SHADERS = Path(__file__).resolve().parent / "shaders"

ADJUSTMENTS = [
    ("brightness", "Kirkkaus"),
    ("contrast", "Kontrasti"),
    ("saturation", "Värikylläisyys"),
    ("gamma", "Gamma"),
    ("hue", "Sävy"),
]

UPSCALERS = [
    ("none", "Tavallinen skaalaus", None),
    ("ravu", "AI-skaalaus: RAVU (nopea, suositus)", "ravu-lite-ar-r4.hook"),
    ("nnedi3", "AI-skaalaus: NNEDI3 (tarkin, raskas)", "nnedi3-nns32-win8x4.hook"),
]
SHARPEN = [
    ("none", "Pois", None),
    ("light", "Kevyt", "terava-kevyt.glsl"),
    ("strong", "Voimakas", "terava-voimakas.glsl"),
]
APPLY_TO = [
    ("sd", "Vain vanhoille videoille (DVD/SD, enintään 576p)"),
    ("upscaled", "Kaikille videoille, joita suurennetaan (enintään 1080p)"),
]
TONEMAP = [
    ("auto", "Automaattinen"),
    ("bt.2390", "Elokuvamainen (BT.2390, suositus)"),
    ("hable", "Pehmeä (Hable)"),
    ("mobius", "Kirkas (Mobius)"),
    ("reinhard", "Luonnollinen (Reinhard)"),
    ("clip", "Ei sävykartoitusta (leikkaa)"),
]

DEFAULTS = {"upscaler": "ravu", "sharpen": "light", "apply_to": "sd",
            "tonemap": "bt.2390", "hdr_auto": True, "hdr_bright": 79, "hdr_dynamic": True}


def get(settings, key):
    d = DEFAULTS[key]
    return settings.value(f"video/{key}", d, type=type(d))


def hdr_peak(bright):
    """Kirkkaus-liukusäädin 0–100 -> mpv:n target-peak (nit). 100 = kirkkain."""
    return int(round(600 - 5 * bright))


def wanted_shaders(settings, video_params):
    """Mitkä sävyttimet kuuluu käyttää tälle videolle."""
    vp = video_params or {}
    h, w = vp.get("h") or 0, vp.get("w") or 0
    if not h:
        return []
    limit = 576 if get(settings, "apply_to") == "sd" else 1080
    if h > limit or w > 1920:
        return []
    out = []
    for key, table in (("upscaler", UPSCALERS), ("sharpen", SHARPEN)):
        f = next((f for k, _, f in table if k == get(settings, key)), None)
        if f and (SHADERS / f).exists():
            out.append(str(SHADERS / f))
    # terävöitys ennen skaalausta (lähderesoluutiossa) toimii parhaiten
    out.sort(key=lambda p: 0 if "terava" in p else 1)
    return out


def apply_hdr(video, settings):
    video.set("tone-mapping", get(settings, "tonemap"))
    video.set("target-peak", "auto" if get(settings, "hdr_auto") else str(hdr_peak(get(settings, "hdr_bright"))))
    video.set("hdr-compute-peak", "yes" if get(settings, "hdr_dynamic") else "no")


def apply_saved(video, settings):
    for prop, _ in ADJUSTMENTS:
        v = settings.value(f"video/{prop}", 0, type=int)
        if v:
            video.set(prop, v)
    apply_hdr(video, settings)


def describe_hdr(vp):
    vp = vp or {}
    gamma = vp.get("gamma")
    if gamma not in ("pq", "hlg"):
        return "Nykyinen video ei ole HDR-video. Säädöt tulevat käyttöön, kun toistat HDR-videon."
    kind = "HDR10 / Dolby Vision (PQ)" if gamma == "pq" else "HLG"
    peak = vp.get("max-luma") or (vp.get("sig-peak") or 0) * 203
    txt = f"Nykyinen video: {kind}, {vp.get('primaries', '')}"
    if peak:
        txt += f", huippukirkkaus noin {int(peak)} nit"
    return txt + "."


class VideoAdjustDialog(QDialog):
    """Ei-modaalinen ikkuna: muutokset näkyvät videossa heti."""

    def __init__(self, video, settings, on_shaders_changed=None, parent=None):
        super().__init__(parent)
        self.video = video
        self.settings = settings
        self.on_shaders_changed = on_shaders_changed or (lambda: None)
        self.setWindowTitle("Kuvan säädöt")
        self.setMinimumWidth(520)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_colors(), "Värit")
        self.tabs.addTab(self._tab_sharp(), "Tarkennus")
        self.tabs.addTab(self._tab_hdr(), "HDR")
        close = QPushButton("Sulje")
        close.setDefault(True)
        close.clicked.connect(self.close)
        reset = QPushButton("Palauta tämän välilehden oletukset")
        reset.clicked.connect(self.reset_tab)
        btns = QHBoxLayout()
        btns.addWidget(reset)
        btns.addStretch()
        btns.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addLayout(btns)

    # ---- apurit
    @staticmethod
    def _note(text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setObjectName("pathLabel")
        return lbl

    def _combo(self, key, options):
        cb = QComboBox()
        for k, text, *_ in options:
            cb.addItem(text, k)
        cb.setCurrentIndex(max(0, cb.findData(get(self.settings, key))))
        cb.currentIndexChanged.connect(lambda _: self._set(key, cb.currentData()))
        return cb

    def _set(self, key, value):
        self.settings.setValue(f"video/{key}", value)
        if key in ("upscaler", "sharpen", "apply_to"):
            self.on_shaders_changed()
            self.refresh_info()
        else:
            apply_hdr(self.video, self.settings)
            self._update_hdr_enabled()

    # ---- Värit
    def _tab_colors(self):
        page = QWidget()
        grid = QGridLayout(page)
        grid.setVerticalSpacing(12)
        self.sliders = {}
        for row, (prop, label) in enumerate(ADJUSTMENTS):
            s = QSlider(Qt.Horizontal)
            s.setRange(-100, 100)
            s.setValue(self.settings.value(f"video/{prop}", 0, type=int))
            val = QLabel(str(s.value()))
            val.setFixedWidth(36)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            s.valueChanged.connect(lambda v, p=prop, l=val: self._color_changed(p, v, l))
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(s, row, 1)
            grid.addWidget(val, row, 2)
            self.sliders[prop] = s
        grid.setRowStretch(len(ADJUSTMENTS), 1)
        return page

    def _color_changed(self, prop, value, label):
        label.setText(str(value))
        self.video.set(prop, value)
        self.settings.setValue(f"video/{prop}", value)

    # ---- Tarkennus
    def _tab_sharp(self):
        page = QWidget()
        f = QFormLayout(page)
        f.setVerticalSpacing(10)
        f.addRow(self._note(
            "Tekee DVD- ja SD-tasoisesta videosta tarkemman isolla näytöllä. AI-skaalaimet on "
            "opetettu suurentamaan kuvaa niin, että reunat pysyvät terävinä ilman sahalaitaa. "
            "Terävöitys korostaa yksityiskohtia lisää."))
        self.cb_up = self._combo("upscaler", UPSCALERS)
        self.cb_sh = self._combo("sharpen", SHARPEN)
        self.cb_apply = self._combo("apply_to", APPLY_TO)
        f.addRow("Skaalaus:", self.cb_up)
        f.addRow("Terävöitys:", self.cb_sh)
        f.addRow("Käytä:", self.cb_apply)
        self.sharp_info = self._note("")
        f.addRow(self.sharp_info)
        f.addRow(self._note("Jos video nykii, valitse RAVU tai Tavallinen skaalaus. NNEDI3 vaatii "
                            "tehokkaan näytönohjaimen. HD- ja 4K-videoita ei käsitellä, koska ne eivät hyödy tästä."))
        return page

    # ---- HDR
    def _tab_hdr(self):
        page = QWidget()
        f = QFormLayout(page)
        f.setVerticalSpacing(10)
        f.addRow(self._note(
            "Kun näyttö ei tue HDR:ää, HDR-video muunnetaan tavalliseksi kuvaksi (sävykartoitus). "
            "Säädä kirkkautta, jos kuva näyttää haalealta tai liian tummalta."))
        self.hdr_info = QLabel("")
        self.hdr_info.setWordWrap(True)
        f.addRow(self.hdr_info)
        f.addRow("Sävykartoitus:", self._combo("tonemap", TONEMAP))
        self.hdr_auto = QCheckBox("Automaattinen kirkkaus")
        self.hdr_auto.setChecked(get(self.settings, "hdr_auto"))
        self.hdr_auto.toggled.connect(lambda on: self._set("hdr_auto", on))
        f.addRow("", self.hdr_auto)
        self.hdr_slider = QSlider(Qt.Horizontal)
        self.hdr_slider.setRange(0, 100)
        self.hdr_slider.setValue(get(self.settings, "hdr_bright"))
        self.hdr_slider.valueChanged.connect(lambda v: self._set("hdr_bright", v))
        row = QHBoxLayout()
        row.addWidget(QLabel("Tummempi"))
        row.addWidget(self.hdr_slider, 1)
        row.addWidget(QLabel("Kirkkaampi"))
        f.addRow("Kirkkaus:", row)
        f.addRow("", self._note("Tummempi säilyttää enemmän yksityiskohtia kirkkaissa kohdissa (taivas, valot), "
                                "kirkkaampi tuo tummat kohtaukset paremmin esiin."))
        self.hdr_dyn = QCheckBox("Dynaaminen kirkkaus (säätyy kohtaus kerrallaan)")
        self.hdr_dyn.setChecked(get(self.settings, "hdr_dynamic"))
        self.hdr_dyn.toggled.connect(lambda on: self._set("hdr_dynamic", on))
        f.addRow("", self.hdr_dyn)
        self._update_hdr_enabled()
        return page

    def _update_hdr_enabled(self):
        self.hdr_slider.setEnabled(not self.hdr_auto.isChecked())

    # ---- tila
    def refresh_info(self):
        vp = self.video.get("video-params") or {}
        self.hdr_info.setText(describe_hdr(vp))
        active = wanted_shaders(self.settings, vp)
        if not vp.get("h"):
            txt = "Toista video, niin näet, käytetäänkö tarkennusta."
        elif active:
            names = [p.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for p in active]
            nice = ", ".join("RAVU" if "ravu" in n else "NNEDI3" if "nnedi" in n else "terävöitys" for n in names)
            txt = f"Nykyinen video {vp['w']}×{vp['h']}: tarkennus käytössä ({nice})."
        else:
            txt = f"Nykyinen video {vp['w']}×{vp['h']}: tarkennusta ei käytetä."
        self.sharp_info.setText(txt)

    def showEvent(self, e):
        self.refresh_info()
        super().showEvent(e)

    def reset_tab(self):
        i = self.tabs.currentIndex()
        if i == 0:
            for s in self.sliders.values():
                s.setValue(0)
        elif i == 1:
            for cb, key in ((self.cb_up, "upscaler"), (self.cb_sh, "sharpen"), (self.cb_apply, "apply_to")):
                cb.setCurrentIndex(cb.findData(DEFAULTS[key]))
        else:
            for key in ("tonemap", "hdr_auto", "hdr_bright", "hdr_dynamic"):
                self.settings.remove(f"video/{key}")
            self.hdr_auto.setChecked(DEFAULTS["hdr_auto"])
            self.hdr_slider.setValue(DEFAULTS["hdr_bright"])
            self.hdr_dyn.setChecked(DEFAULTS["hdr_dynamic"])
            cb = self.tabs.widget(2).findChild(QComboBox)
            cb.setCurrentIndex(cb.findData(DEFAULTS["tonemap"]))
            apply_hdr(self.video, self.settings)


def any_active(settings):
    return any(settings.value(f"video/{p}", 0, type=int) for p, _ in ADJUSTMENTS)
