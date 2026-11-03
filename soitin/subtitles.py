"""Tekstitysten ulkoasu: fontti, koko, värit, reunus, tausta, varjo ja korkeus.

Asetukset tallentuvat (QSettings, ryhmä subs/) ja näkyvät videossa heti.
"""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QDialog, QFontComboBox, QFormLayout,
                               QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget)

DEFAULTS = {
    "font": "Segoe UI",
    "size": 46,            # mpv: pikseleinä 720 rivin korkuisessa kuvassa
    "bold": True,
    "color": "#FFFFFF",
    "border_color": "#000000",
    "border": 3.0,         # reunuksen paksuus
    "shadow": 1.0,         # varjon etäisyys
    "box": False,          # tumma tausta tekstin alla
    "box_color": "#000000",
    "box_alpha": 60,       # %
    "pos": 100,            # 100 = alareuna, pienempi = ylempänä
    "force": False,        # käytä myös .ass-tekstityksiin
}

PRESETS = [
    ("Klassinen (valkoinen, musta reunus)", {"color": "#FFFFFF", "border_color": "#000000", "border": 3.0,
                                              "shadow": 1.0, "box": False}),
    ("Keltainen (DVD-tyyli)", {"color": "#FFE14D", "border_color": "#000000", "border": 3.0,
                               "shadow": 1.0, "box": False}),
    ("Tausta (TV-tyyli)", {"color": "#FFFFFF", "border": 0.0, "shadow": 0.0, "box": True,
                           "box_color": "#000000", "box_alpha": 65}),
    ("Kevyt (ohut reunus, varjo)", {"color": "#FFFFFF", "border_color": "#000000", "border": 1.5,
                                    "shadow": 2.0, "box": False}),
]


def get(settings, key):
    d = DEFAULTS[key]
    return settings.value(f"subs/{key}", d, type=type(d))


def _alpha_hex(color, percent):
    c = QColor(color)
    a = int(round(255 * percent / 100))
    return f"#{a:02X}{c.red():02X}{c.green():02X}{c.blue():02X}"


def apply(video, settings):
    g = lambda k: get(settings, k)  # noqa: E731
    video.set("sub-font", g("font"))
    video.set("sub-font-size", g("size"))
    video.set("sub-bold", "yes" if g("bold") else "no")
    video.set("sub-color", QColor(g("color")).name().upper())
    border_col = QColor(g("border_color")).name().upper()
    # mpv:n uudet ja vanhat nimet (versiosta riippuen toinen toimii)
    for name in ("sub-outline-color", "sub-border-color"):
        video.set(name, border_col)
    for name in ("sub-outline-size", "sub-border-size"):
        video.set(name, g("border") if not g("box") else max(g("border"), 0))
    video.set("sub-shadow-offset", g("shadow"))
    if g("box"):
        box = _alpha_hex(g("box_color"), g("box_alpha"))
        video.set("sub-border-style", "background-box")   # uudet mpv-versiot
        video.set("sub-back-color", box)
        if g("border") == 0:                               # vanhat versiot: laatikko reunuksena
            video.set("sub-border-style", "opaque-box")
    else:
        video.set("sub-border-style", "outline-and-shadow")
        video.set("sub-back-color", "#80000000")          # varjon väri
    video.set("sub-pos", g("pos"))
    video.set("sub-ass-override", "force" if g("force") else "scale")


class Preview(QWidget):
    """Esikatselu: näyttää tekstityksen suunnilleen niin kuin se näkyy videossa."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setMinimumHeight(200)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        # "video": hämärä maisema
        sky = QLinearGradient(0, 0, 0, r.height())
        sky.setColorAt(0, QColor("#2b4c7e"))
        sky.setColorAt(0.55, QColor("#c98a5a"))
        sky.setColorAt(0.56, QColor("#3d4a2f"))
        sky.setColorAt(1, QColor("#1a2214"))
        p.fillRect(r, sky)
        p.setBrush(QColor(255, 230, 170, 200))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(r.width() * 0.75, r.height() * 0.45), 28, 28)

        g = lambda k: get(self.settings, k)  # noqa: E731
        scale = r.height() / 720.0 * 1.6   # esikatselu on pieni: suurennetaan hieman
        f = QFont(g("font"))
        f.setPixelSize(max(6, int(g("size") * scale)))
        f.setBold(g("bold"))
        lines = ["Tämä on esimerkki tekstityksestä.", "Toinen rivi näyttää tältä."]
        fm_h = f.pixelSize() * 1.25
        total = fm_h * len(lines)
        margin = 22 * scale
        bottom = r.height() - margin - (100 - g("pos")) / 100 * r.height()
        y0 = bottom - total
        for i, line in enumerate(lines):
            path = QPainterPath()
            path.addText(0, 0, f, line)
            br = path.boundingRect()
            x = (r.width() - br.width()) / 2 - br.x()
            y = y0 + i * fm_h + fm_h * 0.8
            path.translate(x, y)
            if g("box"):
                c = QColor(g("box_color"))
                c.setAlpha(int(255 * g("box_alpha") / 100))
                pb = path.boundingRect().adjusted(-8 * scale, -4 * scale, 8 * scale, 4 * scale)
                p.fillRect(pb, c)
            if g("shadow") > 0:
                sh = QPainterPath(path)
                off = g("shadow") * scale
                sh.translate(off, off)
                p.fillPath(sh, QColor(0, 0, 0, 128))
            if g("border") > 0:
                pen = QPen(QColor(g("border_color")), g("border") * 2 * scale, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
                p.strokePath(path, pen)
            p.fillPath(path, QColor(g("color")))
        p.end()


class ColorButton(QPushButton):
    def __init__(self, color, title, on_change):
        super().__init__()
        self.title = title
        self.on_change = on_change
        self.setFixedSize(54, 26)
        self.set_color(color)
        self.clicked.connect(self.pick)

    def set_color(self, color):
        self.color = QColor(color).name()
        self.setStyleSheet(f"background:{self.color}; border:1px solid #555; border-radius:5px;")

    def pick(self):
        c = QColorDialog.getColor(QColor(self.color), self, self.title)
        if c.isValid():
            self.set_color(c.name())
            self.on_change(self.color)


class SubStyleDialog(QDialog):
    def __init__(self, video, settings, parent=None):
        super().__init__(parent)
        self.video = video
        self.settings = settings
        self.setWindowTitle("Tekstitysten ulkoasu")
        self.setMinimumWidth(560)
        self.preview = Preview(settings)
        self.w = {}

        f = QFormLayout()
        f.setVerticalSpacing(8)
        presets = QHBoxLayout()
        for name, vals in PRESETS:
            b = QPushButton(name.split(" (")[0])
            b.setToolTip(name)
            b.clicked.connect(lambda _=False, v=vals: self.apply_preset(v))
            presets.addWidget(b)
        f.addRow("Valmiit tyylit:", presets)

        self.font_box = QFontComboBox()
        self.font_box.setCurrentFont(QFont(get(settings, "font")))
        self.font_box.currentFontChanged.connect(lambda fnt: self._set("font", fnt.family()))
        self.bold = QCheckBox("Lihavoitu")
        self.bold.setChecked(get(settings, "bold"))
        self.bold.toggled.connect(lambda on: self._set("bold", on))
        row = QHBoxLayout()
        row.addWidget(self.font_box, 1)
        row.addWidget(self.bold)
        f.addRow("Fontti:", row)

        self.w["size"] = self._slider(f, "Koko:", "size", 20, 100)
        self.c_text = ColorButton(get(settings, "color"), "Tekstin väri", lambda c: self._set("color", c))
        self.c_border = ColorButton(get(settings, "border_color"), "Reunuksen väri",
                                    lambda c: self._set("border_color", c))
        row = QHBoxLayout()
        row.addWidget(QLabel("Teksti"))
        row.addWidget(self.c_text)
        row.addSpacing(16)
        row.addWidget(QLabel("Reunus"))
        row.addWidget(self.c_border)
        row.addStretch()
        f.addRow("Värit:", row)
        self.w["border"] = self._slider(f, "Reunuksen paksuus:", "border", 0, 8, step=0.5)
        self.w["shadow"] = self._slider(f, "Varjo:", "shadow", 0, 6, step=0.5)

        self.box = QCheckBox("Tumma tausta tekstin alla")
        self.box.setChecked(get(settings, "box"))
        self.box.toggled.connect(lambda on: self._set("box", on))
        self.c_box = ColorButton(get(settings, "box_color"), "Taustan väri", lambda c: self._set("box_color", c))
        row = QHBoxLayout()
        row.addWidget(self.box)
        row.addWidget(self.c_box)
        row.addStretch()
        f.addRow("Tausta:", row)
        self.w["box_alpha"] = self._slider(f, "Taustan peittävyys:", "box_alpha", 10, 100, suffix=" %")
        self.w["pos"] = self._slider(f, "Korkeus:", "pos", 50, 100, suffix="", invert_label=True)

        self.force = QCheckBox("Käytä tätä tyyliä myös .ass/.ssa-tekstityksiin (ohittaa niiden oman tyylin)")
        self.force.setChecked(get(settings, "force"))
        self.force.toggled.connect(lambda on: self._set("force", on))
        f.addRow("", self.force)

        reset = QPushButton("Palauta oletukset")
        reset.clicked.connect(self.reset)
        close = QPushButton("Sulje")
        close.setDefault(True)
        close.clicked.connect(self.close)
        btns = QHBoxLayout()
        btns.addWidget(reset)
        btns.addStretch()
        btns.addWidget(close)

        lay = QVBoxLayout(self)
        lay.addWidget(self.preview)
        lay.addLayout(f)
        lay.addLayout(btns)

    def _slider(self, form, label, key, lo, hi, step=1, suffix="", invert_label=False):
        mult = int(round(1 / step)) if step < 1 else 1
        s = QSlider(Qt.Horizontal)
        s.setRange(int(lo * mult), int(hi * mult))
        s.setValue(int(round(get(self.settings, key) * mult)))
        val = QLabel()
        val.setFixedWidth(64)

        def show(v):
            x = v / mult
            if invert_label:
                val.setText("alareuna" if x >= 100 else f"{int(100 - x)} % ylempänä")
            else:
                val.setText((f"{x:g}") + suffix)

        def changed(v):
            show(v)
            x = v / mult
            self._set(key, x)
        show(s.value())
        s.valueChanged.connect(changed)
        row = QHBoxLayout()
        row.addWidget(s, 1)
        row.addWidget(val)
        form.addRow(label, row)
        s._mult = mult
        return s

    def _set(self, key, value):
        t = type(DEFAULTS[key])
        value = int(round(value)) if t is int else t(value)
        self.settings.setValue(f"subs/{key}", value)
        apply(self.video, self.settings)
        self.preview.update()

    def apply_preset(self, vals):
        for k, v in vals.items():
            self.settings.setValue(f"subs/{k}", v)
        self._sync_widgets()
        apply(self.video, self.settings)
        self.preview.update()

    def reset(self):
        self.settings.remove("subs")
        self._sync_widgets()
        apply(self.video, self.settings)
        self.preview.update()

    def _sync_widgets(self):
        g = lambda k: get(self.settings, k)  # noqa: E731
        widgets = [self.font_box, self.bold, self.box, self.force] + list(self.w.values())
        for wd in widgets:
            wd.blockSignals(True)
        self.font_box.setCurrentFont(QFont(g("font")))
        self.bold.setChecked(g("bold"))
        self.box.setChecked(g("box"))
        self.force.setChecked(g("force"))
        for key, s in self.w.items():
            s.setValue(int(round(g(key) * s._mult)))
        for wd in widgets:
            wd.blockSignals(False)
        for key, s in self.w.items():          # päivitä arvotekstit
            s.valueChanged.emit(s.value())
        self.c_text.set_color(g("color"))
        self.c_border.set_color(g("border_color"))
        self.c_box.set_color(g("box_color"))
