"""Kuvan säädöt: kirkkaus, kontrasti, värikylläisyys, gamma ja sävy."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout)

ADJUSTMENTS = [
    ("brightness", "Kirkkaus"),
    ("contrast", "Kontrasti"),
    ("saturation", "Värikylläisyys"),
    ("gamma", "Gamma"),
    ("hue", "Sävy"),
]


class VideoAdjustDialog(QDialog):
    """Ei-modaalinen ikkuna: muutokset näkyvät videossa heti."""

    def __init__(self, video, settings, parent=None):
        super().__init__(parent)
        self.video = video
        self.settings = settings
        self.setWindowTitle("Kuvan säädöt")
        self.setMinimumWidth(420)
        self.sliders = {}
        grid = QGridLayout()
        grid.setVerticalSpacing(12)
        for row, (prop, label) in enumerate(ADJUSTMENTS):
            s = QSlider(Qt.Horizontal)
            s.setRange(-100, 100)
            s.setValue(self.settings.value(f"video/{prop}", 0, type=int))
            val = QLabel(str(s.value()))
            val.setFixedWidth(36)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            s.valueChanged.connect(lambda v, p=prop, l=val: self._changed(p, v, l))
            s.setToolTip("Tuplaklikkaa nimeä palauttaaksesi 0")
            name = QLabel(label)
            grid.addWidget(name, row, 0)
            grid.addWidget(s, row, 1)
            grid.addWidget(val, row, 2)
            self.sliders[prop] = s
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
        lay.addLayout(grid)
        self.remember = None
        lay.addSpacing(8)
        lay.addLayout(btns)

    def _changed(self, prop, value, label):
        label.setText(str(value))
        self.video.set(prop, value)
        self.settings.setValue(f"video/{prop}", value)

    def reset(self):
        for s in self.sliders.values():
            s.setValue(0)


def apply_saved(video, settings):
    for prop, _ in ADJUSTMENTS:
        v = settings.value(f"video/{prop}", 0, type=int)
        if v:
            video.set(prop, v)


def any_active(settings):
    return any(settings.value(f"video/{p}", 0, type=int) for p, _ in ADJUSTMENTS)
