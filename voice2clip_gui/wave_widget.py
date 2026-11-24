"""Live voice visualisation: neon sine waves or oscilloscope + FFT spectrum.

Audio arrives as raw int16 mono chunks (16 kHz) via push(); painting runs on a
60 FPS timer and only touches the latest ~4096 samples.
"""

import math
import time

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from .theme import NEON, Theme

RATE = 16000
RING = 4096
FFT_N = 2048
BANDS = 48
F_LO, F_HI = 100.0, 8000.0


def _qcolor(spec: str) -> QColor:
    """Accept '#rrggbb' or 'rgba(r,g,b,a)' with a in 0..255."""
    if spec.startswith("rgba"):
        r, g, b, a = (int(float(v)) for v in spec[5:-1].split(","))
        return QColor(r, g, b, a)
    return QColor(spec)


class WaveWidget(QWidget):
    levelChanged = Signal(float)   # dBFS of the latest chunk, smoothed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setMinimumHeight(220)
        self.theme: Theme = NEON
        self.mode = "sine"
        self.active = False            # True while recording: waves follow the voice fully

        self._ring = np.zeros(RING, dtype=np.float32)
        self._amp = 0.0                # smoothed 0..1 loudness (spring-driven)
        self._amp_vel = 0.0
        self._gain = 0.25              # 1.0 while recording, 0.25 idle — eased, never jumps
        self._speed = 2.2              # wave travel speed, eased separately so motion glides to rest
        self._db = -60.0
        self._bands = np.zeros(BANDS, dtype=np.float32)
        self._peaks = np.zeros(BANDS, dtype=np.float32)
        self._centroid = 0.3           # smoothed spectral centroid 0..1
        self._phase = 0.0
        self._t0 = time.monotonic()
        self._last = self._t0

        freqs = np.fft.rfftfreq(FFT_N, 1.0 / RATE)
        edges = np.geomspace(F_LO, F_HI, BANDS + 1)
        self._band_idx = [(int(np.searchsorted(freqs, edges[i])), max(int(np.searchsorted(freqs, edges[i + 1])), int(np.searchsorted(freqs, edges[i])) + 1))
                          for i in range(BANDS)]
        self._window = np.hanning(FFT_N).astype(np.float32)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    # ------------------------------------------------------------------ API
    def setTheme(self, theme: Theme):
        self.theme = theme
        self.update()

    def setMode(self, mode: str):
        self.mode = mode
        self.update()

    def setActive(self, active: bool):
        self.active = active

    def push(self, chunk: bytes):
        s = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
        n = len(s)
        if n >= RING:
            self._ring[:] = s[-RING:]
        else:
            self._ring = np.roll(self._ring, -n)
            self._ring[-n:] = s

    # ------------------------------------------------------------- analysis
    def _tick(self):
        now = time.monotonic()
        dt = min(0.1, now - self._last)
        self._last = now

        recent = self._ring[-1024:]
        rms = float(np.sqrt(np.mean(recent * recent)) + 1e-9)
        db = max(-60.0, 20 * math.log10(rms))
        self._gain += ((1.0 if self.active else 0.25) - self._gain) * (1 - math.exp(-dt * 1.8))
        target = min(1.0, max(0.0, (db + 52) / 40)) * self._gain   # -52 dB → 0, -12 dB → 1

        # Critically damped spring: snappy rise when speaking, long ease-out (~1 s) on silence.
        w = 22.0 if target > self._amp else 4.5
        self._amp_vel += (w * w * (target - self._amp) - 2 * w * self._amp_vel) * dt
        self._amp = min(1.2, max(0.0, self._amp + self._amp_vel * dt))
        self._db += (db - self._db) * (1 - math.exp(-dt * 12))
        self.levelChanged.emit(self._db)

        spec = np.abs(np.fft.rfft(self._ring[-FFT_N:] * self._window))
        bands = np.array([spec[a:b].mean() for a, b in self._band_idx], dtype=np.float32)
        bands = np.clip((20 * np.log10(bands + 1e-6) + 20) / 50, 0, 1)
        kb = np.where(bands > self._bands, 1 - math.exp(-dt * 14), 1 - math.exp(-dt * 3.5))
        self._bands += (bands - self._bands) * kb
        self._peaks = np.maximum(self._peaks - dt * 0.35, self._bands)
        total = float(self._bands.sum())
        if total > 1e-3:
            c = float((self._bands * np.arange(BANDS)).sum() / total / BANDS)
            self._centroid += (c - self._centroid) * (1 - math.exp(-dt * 4))

        target_speed = 2.2 + 4.0 * self._amp
        self._speed += (target_speed - self._speed) * (1 - math.exp(-dt * (6 if target_speed > self._speed else 1.2)))
        self._phase += dt * self._speed
        self.update()

    # ------------------------------------------------------------- painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # elliptical glow that fades out well inside the widget (no visible edges)
        p.save()
        p.translate(w / 2, h * 0.48)
        p.scale(w / max(h, 1), 1.0)
        glow = QRadialGradient(QPointF(0, 0), h * 0.48)
        glow.setColorAt(0, _qcolor(self.theme.glow))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(-h, -h, 2 * h, 2 * h), QBrush(glow))
        p.restore()

        if self.mode == "scope":
            self._paint_scope(p, w, h)
        else:
            self._paint_sine(p, w, h)
        p.end()

    def _paint_sine(self, p: QPainter, w: int, h: int):
        mid = h / 2
        t = time.monotonic() - self._t0
        breathe = 0.035 + 0.015 * math.sin(t * 1.3)
        amp = h * 0.38 * max(breathe, self._amp)
        stretch = 0.8 + 0.9 * self._centroid      # brighter voice → denser waves
        lines = ((1.6, 1.0, 1.00, 2.4), (2.3, -1.3, 0.75, 2.0), (3.1, 1.7, 0.50, 1.6), (1.1, -0.8, 0.60, 1.4))

        p.setCompositionMode(QPainter.CompositionMode_Plus)
        step = 3
        for (f, s, a, lw), col in zip(lines, self.theme.waves):
            path = QPainterPath()
            ff = f * stretch
            for x in range(0, w + step, step):
                u = x / w
                env = abs(math.sin(math.pi * u)) ** 2.2
                y = mid + env * amp * a * (
                    math.sin(u * math.tau * ff + self._phase * s) * 0.75
                    + math.sin(u * math.tau * ff * 2.7 - self._phase * 0.66 * s) * 0.25)
                if x == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            base = QColor(col)
            for width, alpha in ((lw * 6, 18), (lw * 2.5, 46), (lw, 242)):
                g = QLinearGradient(0, 0, w, 0)
                c_mid = QColor(base)
                c_mid.setAlpha(alpha)
                c_end = QColor(base)
                c_end.setAlpha(0)
                g.setColorAt(0, c_end)
                g.setColorAt(0.5, c_mid)
                g.setColorAt(1, c_end)
                pen = QPen(QBrush(g), width)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                p.drawPath(path)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setPen(QPen(QColor(255, 255, 255, 10), 1))
        p.drawLine(QPointF(24, mid), QPointF(w - 24, mid))

    def _paint_scope(self, p: QPainter, w: int, h: int):
        th = self.theme
        left, right = 24, w - 24
        top, sh = h * 0.06, h * 0.44
        mid = top + sh / 2

        p.setPen(QPen(_qcolor(th.grid), 1))
        for i in range(11):
            x = left + (right - left) * i / 10
            p.drawLine(QPointF(x, top), QPointF(x, top + sh))
        for i in range(5):
            y = top + sh * i / 4
            p.drawLine(QPointF(left, y), QPointF(right, y))

        # waveform: last ~64 ms, auto-gained so quiet speech is still readable
        sig = self._ring[-1024:]
        peak = float(np.max(np.abs(sig))) + 1e-4
        gain = min(1.0 / peak, 40.0) * (0.15 + 0.85 * min(1.0, self._amp * 1.6))
        n = int(right - left)
        idx = np.linspace(0, len(sig) - 1, max(n // 2, 2)).astype(int)
        ys = mid - np.clip(sig[idx] * gain, -1, 1) * sh * 0.46
        xs = np.linspace(left, right, len(idx))
        path = QPainterPath(QPointF(xs[0], ys[0]))
        for x, y in zip(xs[1:], ys[1:]):
            path.lineTo(float(x), float(y))
        c = QColor(th.scope)
        for width, alpha in ((6, 30), (3, 70), (1.6, 255)):
            c.setAlpha(alpha)
            p.setPen(QPen(c, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)

        # spectrum
        by, bh, gap = h * 0.92, h * 0.34, 4
        bw = (right - left - gap * (BANDS - 1)) / BANDS
        g = QLinearGradient(0, by, 0, by - bh)
        g.setColorAt(0, QColor(th.bar_lo))
        g.setColorAt(1, QColor(th.bar_hi))
        p.setPen(Qt.NoPen)
        for i in range(BANDS):
            x = left + i * (bw + gap)
            v = float(self._bands[i])
            bar_h = max(2.0, v * bh)
            p.fillRect(QRectF(x, by - bar_h, bw, bar_h), QBrush(g))
            pk = by - max(4.0, float(self._peaks[i]) * bh) - 4
            p.fillRect(QRectF(x, pk, bw, 2), QColor(th.peak))

        p.setPen(QColor(th.dim))
        f = QFont(p.font())
        f.setPointSizeF(7.5)
        p.setFont(f)
        for label, hz in (("100 Hz", 100), ("500 Hz", 500), ("1k Hz", 1000), ("2k Hz", 2000), ("4k Hz", 4000), ("8k Hz", 8000)):
            u = math.log(hz / F_LO) / math.log(F_HI / F_LO)
            x = left + (right - left) * u
            x = min(x, right - 34)
            p.drawText(QPointF(x, by + 14), label)
