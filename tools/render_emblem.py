#!/usr/bin/env python3
"""Render the Umbrella-style emblem as a crisp transparent PNG at any size.

Vector re-drawing in the style of logo_example.jpg (which is only 150 px):
8 segments with concave outer arcs, deep textured blood-red and metallic white,
thin dark gaps between segments.

    python tools/render_emblem.py 1024 voice2clip_gui/assets/emblem.png
"""

import math
import random
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)


def segment_path(c: QPointF, R: float, i: int, gap: float) -> QPainterPath:
    """Segment i (0 = top, clockwise): centre → tip → concave arc → tip, shrunk by `gap` for the seams."""
    a0 = math.radians(i * 45 - 112.5)
    a1 = math.radians((i + 1) * 45 - 112.5)
    am = (a0 + a1) / 2
    # shift the whole wedge outward along its axis so neighbours leave a thin dark seam
    off = QPointF(math.cos(am) * gap, math.sin(am) * gap)
    cc = c + off * 1.6
    t0 = QPointF(c.x() + R * math.cos(a0), c.y() + R * math.sin(a0)) + off
    t1 = QPointF(c.x() + R * math.cos(a1), c.y() + R * math.sin(a1)) + off
    ctrl = QPointF(c.x() + R * 0.68 * math.cos(am), c.y() + R * 0.68 * math.sin(am)) + off   # concave edge
    p = QPainterPath(cc)
    p.lineTo(t0)
    p.quadTo(ctrl, t1)
    p.closeSubpath()
    return p


def grain(size: int, seed: int, dark: int, alpha: int) -> QImage:
    """Mottled texture: soft dark blotches (like the worn print of the original)."""
    rnd = random.Random(seed)
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    for _ in range(int(size * 0.9)):
        x, y = rnd.uniform(0, size), rnd.uniform(0, size)
        r = rnd.uniform(size * 0.004, size * 0.03)
        g = QRadialGradient(QPointF(x, y), r)
        g.setColorAt(0, QColor(dark, 0, 0, rnd.randint(alpha // 3, alpha)))
        g.setColorAt(1, QColor(dark, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(x, y), r, r)
    p.end()
    return img


def smoke(size: int, seed: int) -> QImage:
    """Smoky worn-print texture for the red wedges: large soft dark clouds + a few lighter wisps."""
    rnd = random.Random(seed)
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    for _ in range(260):
        x, y = rnd.uniform(0, size), rnd.uniform(0, size)
        r = rnd.uniform(size * 0.02, size * 0.09)
        light = rnd.random() < 0.28
        col = QColor(210, 20, 40) if light else QColor(18, 0, 2)
        g = QRadialGradient(QPointF(x, y), r)
        g.setColorAt(0, QColor(col.red(), col.green(), col.blue(), rnd.randint(18, 46 if light else 60)))
        g.setColorAt(1, QColor(col.red(), col.green(), col.blue(), 0))
        p.setBrush(g)
        p.drawEllipse(QPointF(x, y), r * rnd.uniform(1.0, 1.8), r)
    p.end()
    return img


def brushed(size: int, seed: int) -> QImage:
    """Fine brushed-metal streaks for the white wedges."""
    rnd = random.Random(seed)
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    for _ in range(int(size * 1.2)):
        x, y = rnd.uniform(0, size), rnd.uniform(0, size)
        ln, a = rnd.uniform(size * 0.02, size * 0.08), rnd.uniform(0, math.pi)
        dark = rnd.random() < 0.5
        p.setPen(QPen(QColor(90, 85, 90, rnd.randint(10, 30)) if dark else QColor(255, 255, 255, rnd.randint(10, 35)),
                      size * 0.0015))
        p.drawLine(QPointF(x, y), QPointF(x + ln * math.cos(a), y + ln * math.sin(a)))
    p.end()
    return img


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

    c = QPointF(size / 2, size / 2)
    R = size * 0.47
    gap = size * 0.011
    tex = smoke(size, 7)
    metal = brushed(size, 11)

    for i in range(8):
        path = segment_path(c, R, i, gap)
        a_mid = math.radians(i * 45 - 90)
        if i % 2 == 0:
            # blood red: bright core → near-black rim, plus worn texture
            g = QRadialGradient(c, R * 1.02)
            g.setColorAt(0.00, QColor("#c40820"))
            g.setColorAt(0.35, QColor("#8e0014"))
            g.setColorAt(0.75, QColor("#55000a"))
            g.setColorAt(1.00, QColor("#260004"))
            p.fillPath(path, g)
            p.save()
            p.setClipPath(path)
            p.drawImage(0, 0, tex)
            sheen = QLinearGradient(c, QPointF(c.x() + R * math.cos(a_mid), c.y() + R * math.sin(a_mid)))
            sheen.setColorAt(0.0, QColor(255, 60, 70, 35))
            sheen.setColorAt(0.5, QColor(255, 255, 255, 0))
            p.fillRect(QRectF(0, 0, size, size), sheen)
            p.restore()
        else:
            # metallic white: brushed gradient across the wedge + bright ridge
            perp = a_mid + math.pi / 2
            half = R * 0.42
            mid = QPointF(c.x() + R * 0.55 * math.cos(a_mid), c.y() + R * 0.55 * math.sin(a_mid))
            g = QLinearGradient(QPointF(mid.x() - half * math.cos(perp), mid.y() - half * math.sin(perp)),
                                QPointF(mid.x() + half * math.cos(perp), mid.y() + half * math.sin(perp)))
            g.setColorAt(0.00, QColor("#dcdcdf"))
            g.setColorAt(0.30, QColor("#ffffff"))
            g.setColorAt(0.55, QColor("#c2c1c5"))
            g.setColorAt(0.80, QColor("#9a989c"))
            g.setColorAt(1.00, QColor("#6e6b70"))
            p.fillPath(path, g)
            p.save()
            p.setClipPath(path)
            p.drawImage(0, 0, metal)
            shade = QRadialGradient(c, R)
            shade.setColorAt(0.0, QColor(255, 255, 255, 0))
            shade.setColorAt(0.8, QColor(40, 30, 35, 0))
            shade.setColorAt(1.0, QColor(40, 30, 35, 90))
            p.fillRect(QRectF(0, 0, size, size), shade)
            p.restore()
            p.setPen(QPen(QColor(60, 50, 55, 150), size * 0.0025))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)

    # dark hub
    p.setPen(Qt.NoPen)
    hub = QRadialGradient(c, size * 0.022)
    hub.setColorAt(0, QColor("#2a0006"))
    hub.setColorAt(1, QColor("#0a0002"))
    p.setBrush(hub)
    p.drawEllipse(c, size * 0.02, size * 0.02)
    p.end()
    return img


if __name__ == "__main__":
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 1024
    out = sys.argv[2] if len(sys.argv) > 2 else "emblem.png"
    app = QGuiApplication.instance() or QGuiApplication(["render_emblem", "-platform", "offscreen"])
    render(size).save(out)
    print(f"saved {out} ({size}px)")
