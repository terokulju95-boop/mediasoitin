"""Itse piirretyt kuvakkeet, jotka mukautuvat teeman väriin."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _poly(path, pts):
    path.moveTo(*pts[0])
    for p in pts[1:]:
        path.lineTo(*p)
    path.closeSubpath()


def icon(kind: str, color="#E6E6E6", size=48) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 24.0, size / 24.0)   # piirretään 24x24-koordinaatistossa
    col = QColor(color)
    p.setBrush(col)
    p.setPen(Qt.NoPen)
    path = QPainterPath()
    stroke = QPen(col, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

    if kind == "play":
        _poly(path, [(8, 5), (19, 12), (8, 19)])
    elif kind == "pause":
        path.addRoundedRect(QRectF(6.5, 5, 4, 14), 1, 1)
        path.addRoundedRect(QRectF(13.5, 5, 4, 14), 1, 1)
    elif kind == "stop":
        path.addRoundedRect(QRectF(6, 6, 12, 12), 1.5, 1.5)
    elif kind == "next":
        _poly(path, [(5, 6), (14, 12), (5, 18)])
        path.addRoundedRect(QRectF(15.5, 6, 3, 12), 1, 1)
    elif kind == "prev":
        _poly(path, [(19, 6), (10, 12), (19, 18)])
        path.addRoundedRect(QRectF(5.5, 6, 3, 12), 1, 1)
    elif kind in ("volume", "mute"):
        _poly(path, [(3, 9), (7, 9), (12, 4.5), (12, 19.5), (7, 15), (3, 15)])
        p.drawPath(path)
        path = QPainterPath()
        p.setBrush(Qt.NoBrush)
        p.setPen(stroke)
        if kind == "volume":
            p.drawArc(QRectF(10, 8, 6, 8), -60 * 16, 120 * 16)
            p.drawArc(QRectF(10, 5, 10, 14), -60 * 16, 120 * 16)
        else:
            p.drawLine(QPointF(15, 9), QPointF(21, 15))
            p.drawLine(QPointF(21, 9), QPointF(15, 15))
    elif kind in ("fullscreen", "exit_fullscreen"):
        p.setBrush(Qt.NoBrush)
        p.setPen(stroke)
        if kind == "fullscreen":
            for a, b, c in [((4, 9), (4, 4), (9, 4)), ((15, 4), (20, 4), (20, 9)),
                            ((20, 15), (20, 20), (15, 20)), ((9, 20), (4, 20), (4, 15))]:
                p.drawPolyline([QPointF(*a), QPointF(*b), QPointF(*c)])
        else:
            for a, b, c in [((4, 9), (9, 9), (9, 4)), ((15, 4), (15, 9), (20, 9)),
                            ((20, 15), (15, 15), (15, 20)), ((9, 20), (9, 15), (4, 15))]:
                p.drawPolyline([QPointF(*a), QPointF(*b), QPointF(*c)])
    elif kind == "menu":
        for y in (7, 12, 17):
            path.addRoundedRect(QRectF(4, y - 1, 16, 2), 1, 1)
    elif kind == "up":
        p.setBrush(Qt.NoBrush)
        p.setPen(stroke)
        p.drawPolyline([QPointF(6, 13), QPointF(12, 7), QPointF(18, 13)])
        p.drawLine(QPointF(12, 7), QPointF(12, 19))
    elif kind == "close":
        p.setBrush(Qt.NoBrush)
        p.setPen(stroke)
        p.drawLine(QPointF(6, 6), QPointF(18, 18))
        p.drawLine(QPointF(18, 6), QPointF(6, 18))
    elif kind == "app":
        path.addEllipse(QRectF(1, 1, 22, 22))
        p.drawPath(path)
        path = QPainterPath()
        p.setBrush(QColor("#000000"))
        _poly(path, [(9, 6.5), (18, 12), (9, 17.5)])

    p.drawPath(path)
    p.end()
    return QIcon(pm)
