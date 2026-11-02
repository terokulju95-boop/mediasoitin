"""Ulkoasu: OLED-musta pohja ja korostusväri (oletus tumma oranssi).

Värejä voi muuttaa sovelluksessa (Näytä → Korostusväri) tai tässä tiedostossa.
"""
from PySide6.QtGui import QColor, QPalette

DEFAULT_ACCENT = "#D35400"   # tumma oranssi

ACCENTS = [
    ("Tumma oranssi", "#D35400"),
    ("Oranssi", "#F57C00"),
    ("Meripihka", "#FFA000"),
    ("Punainen", "#C62828"),
    ("Sininen", "#1E88E5"),
    ("Vihreä", "#2E7D32"),
    ("Violetti", "#7B1FA2"),
]

BG = "#000000"        # OLED-musta
SURFACE = "#0B0B0B"   # paneelit
SURFACE2 = "#161616"  # hover, valikot
BORDER = "#222222"
TEXT = "#E6E6E6"
MUTED = "#8C8C8C"


def accent_shades(accent: str):
    c = QColor(accent)
    return {
        "accent": c.name(),
        "accent_hover": c.lighter(125).name(),
        "accent_dim": c.darker(160).name(),
        "accent_sel": f"rgba({c.red()},{c.green()},{c.blue()},0.30)",
    }


def apply(app, accent: str = DEFAULT_ACCENT):
    a = accent_shades(accent)
    app.setStyle("Fusion")
    p = QPalette()
    for role, col in [
        (QPalette.Window, BG), (QPalette.Base, BG), (QPalette.AlternateBase, SURFACE),
        (QPalette.Button, SURFACE), (QPalette.WindowText, TEXT), (QPalette.Text, TEXT),
        (QPalette.ButtonText, TEXT), (QPalette.ToolTipBase, SURFACE2), (QPalette.ToolTipText, TEXT),
        (QPalette.Highlight, a["accent"]), (QPalette.HighlightedText, "#FFFFFF"),
        (QPalette.PlaceholderText, MUTED), (QPalette.Link, a["accent"]),
    ]:
        p.setColor(role, QColor(col))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#555555"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#555555"))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#555555"))
    app.setPalette(p)
    app.setStyleSheet(QSS.format(BG=BG, SURFACE=SURFACE, SURFACE2=SURFACE2, BORDER=BORDER,
                                 TEXT=TEXT, MUTED=MUTED, **a))


QSS = """
QWidget {{ background: {BG}; color: {TEXT}; font-size: 10pt; }}
QToolTip {{ background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}

QMenuBar {{ background: {BG}; border-bottom: 1px solid {BORDER}; padding: 2px; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {SURFACE2}; color: {accent}; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 28px 6px 24px; border-radius: 4px; }}
QMenu::item:selected {{ background: {accent_sel}; color: #FFFFFF; }}
QMenu::item:disabled {{ color: #555555; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; left: 6px; }}
QMenu::indicator:checked {{ background: {accent}; border-radius: 3px; }}

QTreeView, QTreeWidget, QListWidget {{
    background: {BG}; border: none; outline: 0; padding: 2px;
}}
QTreeView::item, QListWidget::item {{ padding: 4px 2px; border-radius: 4px; }}
QTreeView::item:hover, QListWidget::item:hover {{ background: {SURFACE2}; }}
QTreeView::item:selected, QListWidget::item:selected {{ background: {accent_sel}; color: #FFFFFF; }}
QHeaderView::section {{ background: {BG}; color: {MUTED}; border: none;
    border-bottom: 1px solid {BORDER}; padding: 4px; }}

QLabel#panelTitle {{ color: {MUTED}; font-size: 9pt; font-weight: bold;
    padding: 8px 6px 4px 6px; letter-spacing: 1px; }}
QLabel#pathLabel {{ color: {MUTED}; padding: 2px; }}
QLabel#timeLabel {{ color: {MUTED}; font-family: Consolas, monospace; padding: 0 6px; }}
QLabel#ovTitle {{ color: {TEXT}; font-size: 12pt; padding-left: 12px; background: transparent; }}

QSplitter::handle {{ background: {BG}; }}
QSplitter::handle:hover {{ background: {accent_dim}; }}

QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 5px; }}
QToolButton:hover {{ background: {SURFACE2}; }}
QToolButton:pressed {{ background: {accent_sel}; }}
QToolButton::menu-indicator {{ image: none; }}
QToolButton#playButton {{ background: {accent}; border-radius: 20px; padding: 8px; }}
QToolButton#playButton:hover {{ background: {accent_hover}; }}

QWidget#controls, QWidget#overlay {{ background: {BG}; }}
QWidget#controls {{ border-top: 1px solid {BORDER}; }}

QSlider::groove:horizontal {{ height: 4px; background: #2A2A2A; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {accent}; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: {accent_hover}; }}

QScrollBar:vertical {{ background: {BG}; width: 8px; margin: 0; }}
QScrollBar:horizontal {{ background: {BG}; height: 8px; margin: 0; }}
QScrollBar::handle {{ background: #2A2A2A; border-radius: 4px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: {accent_dim}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QStatusBar {{ background: {BG}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {MUTED}; padding: 0 6px; }}

QPushButton {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 16px; }}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton:default {{ background: {accent}; border-color: {accent}; }}
QComboBox {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 8px; }}
QMessageBox, QDialog {{ background: {SURFACE}; }}
"""
