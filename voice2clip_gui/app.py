"""voice2clip GUI: main window wiring the PushToTalk engine to the Qt widgets."""

import datetime
import math
import os
import sys
import threading
import time
from pathlib import Path

import pyperclip
import pynput
from PySide6.QtCore import QObject, QPointF, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QActionGroup, QColor, QGuiApplication, QIcon, QKeySequence, QPixmap, QLinearGradient, QPainter,
                           QPainterPath, QPen, QShortcut,
                           QRadialGradient)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QToolButton, QVBoxLayout,
                               QWidget)

from .history import HistoryPanel
from .paste import COMBOS, Paster
from .sysmon import SysMonitor
from .theme import THEMES, Theme, stylesheet
from .wave_widget import WaveWidget

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from push_to_talk import PushToTalk  # noqa: E402

EDGE = 6  # px grab margin for resizing the frameless window
ICON = Path(__file__).resolve().parent / "assets" / "emblem.png"   # 1024 px, tools/render_emblem.py
VERSION = "2.1.0"
LANGUAGES = (("ru", "Русский"), ("en", "English"), ("auto", "Авто (определять)"))   # major.minor.patch, shown under the title


def copy_text(text: str):
    """pyperclip (wl-copy) works even when our window isn't focused on Wayland; Qt is the fallback."""
    try:
        pyperclip.copy(text)
    except Exception:
        QGuiApplication.clipboard().setText(text)


def repolish(w: QWidget):
    w.style().unpolish(w)
    w.style().polish(w)


class Bridge(QObject):
    """Moves engine callbacks (mic / pynput / worker threads) onto the Qt thread."""
    audio = Signal(bytes)
    state = Signal(str)
    result = Signal(str, float, float, str)
    error = Signal(str)


class StatusDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self.color = QColor("#3ddc97")
        self.blink = False
        self._on = True
        self._t = QTimer(self, interval=500, timeout=self._toggle)
        self._t.start()

    def _toggle(self):
        self._on = not self._on if self.blink else True
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(self.color)
        if not self._on:
            c.setAlpha(90)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(1, 1, 8, 8))


_emblem_src: QPixmap | None = None
_emblem_cache: dict[int, QPixmap] = {}


def _logo_pixmap(px: int) -> QPixmap | None:
    """Emblem pre-scaled (area-averaged) to ~px, so small rotating copies stay crisp; cached per size."""
    global _emblem_src
    if _emblem_src is None:
        _emblem_src = QPixmap(str(ICON))
    if _emblem_src.isNull():
        return None
    px = max(8, min(1024, px))
    if px not in _emblem_cache:
        _emblem_cache[px] = _emblem_src.scaled(px, px, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return _emblem_cache[px]


def draw_emblem(p: QPainter, c: QPointF, r: float, rotation: float = 0.0, halo: bool = True):
    """Umbrella emblem with a soft red glow: the user's logo image, or a vector fallback if it's missing."""
    if halo:
        glow = QRadialGradient(c, r * 1.26)
        glow.setColorAt(0.75, QColor(228, 0, 43, 45))
        glow.setColorAt(1.0, QColor(228, 0, 43, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(c, r * 1.26, r * 1.26)

    dpr = p.device().devicePixelRatioF() if p.device() else 1.0
    pm = _logo_pixmap(int(round(2 * r * dpr / 4)) * 4)   # quantised sizes keep the cache small
    if pm is not None:
        p.save()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.translate(c)
        p.rotate(rotation)
        p.drawPixmap(QRectF(-r, -r, 2 * r, 2 * r), pm, QRectF(pm.rect()))
        p.restore()
        return

    def pt(k: int, rad: float) -> QPointF:
        a = math.radians(k * 45 - 112.5 + rotation)
        return QPointF(c.x() + rad * math.cos(a), c.y() + rad * math.sin(a))

    # dark octagon rim
    rim = QPainterPath(pt(0, r + r * 0.12))
    for k in range(1, 8):
        rim.lineTo(pt(k, r + r * 0.12))
    rim.closeSubpath()
    p.fillPath(rim, QColor("#1a0004"))

    red = QRadialGradient(c, r)
    red.setColorAt(0.0, QColor("#e3102c"))
    red.setColorAt(0.55, QColor("#a3001a"))
    red.setColorAt(1.0, QColor("#420007"))
    white = QRadialGradient(c, r)
    white.setColorAt(0.0, QColor("#ffffff"))
    white.setColorAt(0.7, QColor("#e9e6e6"))
    white.setColorAt(1.0, QColor("#a9a3a4"))
    for i in range(8):
        seg = QPainterPath(c)
        seg.lineTo(pt(i, r))
        seg.lineTo(pt(i + 1, r))
        seg.closeSubpath()
        p.fillPath(seg, white if i % 2 else red)

    p.setPen(QPen(QColor(26, 0, 4, 200), 0.8))
    for i in range(8):
        p.drawLine(c, pt(i, r))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#1a0004"))
    p.drawEllipse(c, r * 0.15, r * 0.15)


class Logo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.theme: Theme | None = None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self.theme
        if t and t.corp:
            draw_emblem(p, QPointF(17, 17), 15.5, halo=False)
        else:
            p.translate(5, 5)
            g = QLinearGradient(0, 0, 24, 24)
            g.setColorAt(0, QColor(t.accent if t else "#3ee6ff"))
            g.setColorAt(1, QColor(t.accent2 if t else "#9b6bff"))
            p.fillRect(QRectF(1, 1, 22, 22), g)
            p.setPen(QPen(QColor(t.on_accent if t else "#071017"), 2.4, Qt.SolidLine, Qt.RoundCap))
            for x, hh in ((6, 1), (9, 4), (12, 7), (15, 4), (18, 1)):
                p.drawLine(QPointF(x, 12 - hh), QPointF(x, 12 + hh))


class RecButton(QAbstractButton):
    """Hold-to-record button. At rest: a calm square. While recording it turns into a live
    equalizer (Neon) or a slowly spinning Umbrella emblem (Umbrella themes), both driven by the
    voice level. The idle ↔ recording change is eased, never a jump."""

    SIZE = 48

    def __init__(self, level_fn, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.theme: Theme | None = None
        self._level_fn = level_fn
        self.active = False
        self._mix = 0.0            # 0 = idle look, 1 = recording look
        self._angle = 0.0
        self._t0 = self._last = time.monotonic()
        self._timer = QTimer(self, interval=16, timeout=self._tick)

    def setActive(self, on: bool):  # noqa: N802 - Qt naming
        self.active = on
        self._last = time.monotonic()
        self._timer.start()

    def _level(self) -> float:
        try:
            return max(0.0, min(1.0, float(self._level_fn())))
        except Exception:
            return 0.0

    def _tick(self):
        now = time.monotonic()
        dt = min(0.1, now - self._last)
        self._last = now
        # quick to react when recording starts, slow (~1 s) graceful return to the square
        rate = 9.0 if self.active else 2.6
        self._mix += ((1.0 if self.active else 0.0) - self._mix) * (1 - math.exp(-dt * rate))
        self._angle = (self._angle + dt * (20 + 70 * self._level()) * self._mix) % 360   # slow, calm spin
        if not self.active and self._mix < 0.01:
            self._mix = 0.0
            self._timer.stop()
        self.update()

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _):
        t = self.theme
        if not t:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.SIZE / 2, self.SIZE / 2)
        m, lvl = self._mix, self._level()
        e = m * m * (3 - 2 * m)          # smoothstep: soft start and soft landing of the morph
        now = time.monotonic() - self._t0
        rec = QColor(t.rec)

        # body square: for the emblem themes it shrinks into the emblem and grows back out of it
        if t.corp:
            half = 15 * (1 - 0.35 * e)
            body = (1 - e) ** 1.2
        else:
            half = 15 - 3 * e + 1.8 * lvl * e
            body = 1.0
        sq = QRectF(c.x() - half, c.y() - half, 2 * half, 2 * half)
        if body > 0.01:
            p.setOpacity(body)
            edge = QColor(rec)
            edge.setAlpha(55)
            p.fillRect(sq.adjusted(-4, -4, 4, 4), edge)
            g = QRadialGradient(sq.center() - QPointF(half * 0.3, half * 0.4), half * 1.9)
            g.setColorAt(0, rec.lighter(150 if self.underMouse() else 135))
            g.setColorAt(1, rec)
            p.fillRect(sq, g)
            p.setOpacity(1.0)

        if m > 0.01:
            p.setOpacity(e)
            if t.corp:
                draw_emblem(p, c, (14.0 + 2.5 * lvl) * (0.85 + 0.15 * e), rotation=self._angle)
            else:
                bars, bw, gap = 5, 2.6, 2.0
                x0 = c.x() - (bars * bw + (bars - 1) * gap) / 2
                for i in range(bars):
                    wob = 0.5 + 0.5 * math.sin(now * (7 + i * 1.7) + i * 1.3)
                    h = 3 + (2 * half - 8) * (0.12 + 0.88 * lvl) * (0.35 + 0.65 * wob)
                    p.fillRect(QRectF(x0 + i * (bw + gap), c.y() - h / 2, bw, h), QColor("#ffffff"))
            p.setOpacity(1.0)
        p.end()


class Shimmer(QWidget):
    """Placeholder lines with a moving highlight while whisper is working."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme: Theme | None = None
        self._t = QTimer(self, interval=16, timeout=self.update)

    def showEvent(self, e):
        self._t.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._t.stop()
        super().hideEvent(e)

    def paintEvent(self, _):
        if not self.theme:
            return
        p = QPainter(self)
        w = self.width()
        pos = (time.monotonic() / 1.4) % 1.0
        base, hi = QColor(self.theme.panel2).lighter(125), QColor(self.theme.accent2)
        hi.setAlpha(110)
        for i, frac in enumerate((0.92, 0.78, 0.55)):
            g = QLinearGradient(0, 0, w, 0)
            g.setColorAt(0, base)
            g.setColorAt(max(0.0, pos - 0.2), base)
            g.setColorAt(pos, hi)
            g.setColorAt(min(1.0, pos + 0.2), base)
            g.setColorAt(1, base)
            p.fillRect(QRectF(0, 6 + i * 22, w * frac, 11), g)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("voice2clip", "gui")
        self.setWindowTitle("ALISA CORPORATION · VOICIFY")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setMinimumSize(860, 560)
        self.resize(1100, 680)
        self.setMouseTracking(True)

        os.chdir(ROOT)  # engine resolves config.json / transcriptions relative to cwd
        self.engine = PushToTalk(config_path=os.environ.get("VOICE2CLIP_CONFIG", str(ROOT / "config.json")))
        self.engine.notify = self.settings.value("notify", False, type=bool)
        self.engine.auto_copy = self.settings.value("auto_copy", True, type=bool)
        # speech language: GUI choice overrides config.json; "auto" is passed explicitly (whisper-cli defaults to "en")
        self.engine.language = self.settings.value("language", self.engine.language or "auto")

        self.bridge = Bridge()
        self.engine.on_audio = self.bridge.audio.emit
        self.engine.on_state = self.bridge.state.emit
        self.engine.on_result = lambda text, a, t, path: self.bridge.result.emit(text, a, t, str(path or ""))
        self.engine.on_error = self.bridge.error.emit

        self._rec_started = 0.0
        self._state = "idle"
        self._last_text = ""
        self._last_meta = "—"
        self._hover_item = None   # (text, when) previewed from history while hovering
        self._pinned = None       # (text, when) selected in history; stays until deselected
        self._shown_text = ""     # what the card shows now — the Copy button copies this
        # short delay so moving between rows doesn't flicker back to the latest text
        self._preview_end_timer = QTimer(self, singleShot=True, interval=150, timeout=self._end_preview)

        self._clock = QTimer(self, interval=100, timeout=self._update_timer)
        self.paster = Paster()
        self.paste_combo = self.settings.value("paste_combo", "ctrl+shift+v")
        self._build()
        self.bridge.audio.connect(self.wave.push)
        self.bridge.state.connect(self._on_state)
        self.bridge.result.connect(self._on_result)
        self.bridge.error.connect(lambda msg: self._show_toast(msg, warn=True))
        self.wave.levelChanged.connect(self._on_level)

        self.apply_theme(self.settings.value("theme", "neon"))
        self.set_mode(self.settings.value("mode", "sine"))
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.settings.value("on_top", False, type=bool))

        whisper_ok = self.engine._check_whisper_availability()
        model_ok = bool(self.engine.model_path) and os.path.exists(self.engine.model_path)
        self.engine._start_mic_stream()
        self.listener = pynput.keyboard.Listener(on_press=self.engine.on_key_press,
                                                 on_release=self.engine.on_key_release)
        self.listener.start()
        if not whisper_ok or not model_ok:
            self._on_state("error")
            self.status_text.setText("whisper не найден" if not whisper_ok else "модель не найдена")

    # ------------------------------------------------------------------ UI
    def _build(self):
        root = QWidget(objectName="root")
        root.setMouseTracking(True)
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # header
        self.header = QFrame(objectName="header")
        self.header.setFixedHeight(48)
        h = QHBoxLayout(self.header)
        h.setContentsMargins(16, 0, 10, 0)
        h.setSpacing(8)
        self.logo = Logo()
        self.brand = QLabel(objectName="brand")
        ver = QLabel(f"BIOACOUSTIC UNIT · {VERSION}", objectName="brandVer")
        brand_box = QVBoxLayout()
        brand_box.setSpacing(0)
        brand_box.addStretch(1)
        brand_box.addWidget(self.brand)
        brand_box.addWidget(ver)
        brand_box.addStretch(1)
        h.addWidget(self.logo)
        h.addSpacing(4)
        h.addLayout(brand_box)
        h.addSpacing(10)
        for k, val in self._chips():
            chip = QLabel(f"{k} <b>{val}</b>", objectName="chip")
            if k == "lang":                      # clickable: opens the speech-language menu
                self.lang_chip = chip
                chip.setText(f"{k} <b>{val}</b> ▾")
                chip.setCursor(Qt.PointingHandCursor)
                chip.setToolTip("Язык речи")
                chip.mousePressEvent = lambda _e: self.lang_menu.exec(chip.mapToGlobal(chip.rect().bottomLeft()))
            h.addWidget(chip, 0, Qt.AlignVCenter)
        h.addStretch(1)
        status = QFrame(objectName="status")
        status.setFixedHeight(28)
        sl = QHBoxLayout(status)
        sl.setContentsMargins(10, 0, 11, 0)
        sl.setSpacing(8)
        self.dot = StatusDot()
        self.status_text = QLabel("Готов")
        self.status_text.setStyleSheet("background: transparent; border: none;")
        sl.addWidget(self.dot)
        sl.addWidget(self.status_text)
        h.addWidget(status, 0, Qt.AlignVCenter)
        h.addSpacing(6)
        self.gear = QToolButton(objectName="hdrBtn", text="⚙")
        self.gear.setPopupMode(QToolButton.InstantPopup)
        self.gear.setMenu(self._settings_menu())
        mini = QToolButton(objectName="hdrBtn", text="─", clicked=self.showMinimized)
        close = QToolButton(objectName="hdrBtn", text="✕", clicked=self.close)
        for b in (self.gear, mini, close):
            b.setCursor(Qt.PointingHandCursor)
            h.addWidget(b)
        v.addWidget(self.header)

        # body
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        v.addLayout(body, 1)

        stage = QFrame(objectName="stage")
        sv = QVBoxLayout(stage)
        sv.setContentsMargins(20, 16, 20, 6)
        sv.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(QLabel("ГОЛОС · LIVE", objectName="sectionLabel"))
        top.addStretch(1)
        seg = QFrame(objectName="seg")
        segl = QHBoxLayout(seg)
        segl.setContentsMargins(3, 3, 3, 3)
        segl.setSpacing(2)
        self.seg_group = QButtonGroup(self)
        for mode, label in (("sine", "Волна"), ("scope", "Осциллограф")):
            b = QPushButton(label, objectName="segBtn", checkable=True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, m=mode: self.set_mode(m))
            b.setProperty("mode", mode)
            self.seg_group.addButton(b)
            segl.addWidget(b)
        top.addWidget(seg)
        sv.addLayout(top)

        self.wave = WaveWidget()
        self.wave.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sv.addWidget(self.wave, 1)

        rec_row = QHBoxLayout()
        rec_row.addStretch(1)
        ptt = QFrame(objectName="ptt")
        pl = QHBoxLayout(ptt)
        pl.setContentsMargins(4, 4, 18, 4)
        pl.setSpacing(12)
        self.rec_btn = RecButton(lambda: self.wave._amp)
        self.rec_btn.setCursor(Qt.PointingHandCursor)
        self.rec_btn.setToolTip("Удерживайте для записи")
        self.rec_btn.pressed.connect(lambda: threading.Thread(target=self.engine.start_recording, daemon=True).start())
        self.rec_btn.released.connect(lambda: threading.Thread(target=self.engine.stop_recording_and_transcribe, daemon=True).start())
        self.ptt_hint = QLabel(objectName="pttHint")
        self.ptt_hint.setTextFormat(Qt.RichText)
        pl.addWidget(self.rec_btn)
        pl.addWidget(self.ptt_hint)
        rec_row.addWidget(ptt)
        rec_row.addSpacing(24)
        self.timer_lbl = QLabel("00:00.0", objectName="timer")
        self.timer_lbl.setMinimumWidth(130)
        self.timer_lbl.setAlignment(Qt.AlignCenter)
        rec_row.addWidget(self.timer_lbl)
        rec_row.addStretch(1)
        sv.addLayout(rec_row)

        meter_row = QHBoxLayout()
        meter_row.setSpacing(12)
        meter_row.addWidget(QLabel("-60 dB", objectName="meterLabel"))
        self.meter = QProgressBar(objectName="meter", textVisible=False, maximum=1000)
        meter_row.addWidget(self.meter, 1)
        self.db_lbl = QLabel("-60 dB", objectName="meterLabel")
        self.db_lbl.setMinimumWidth(44)
        self.db_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        meter_row.addWidget(self.db_lbl)
        sv.addLayout(meter_row)

        # system load: CPU (whole system) and GPU (load + VRAM) — whisper runs on the GPU unless VRAM is full
        sys_row = QHBoxLayout()
        sys_row.setSpacing(10)
        self.sys_bars = {}
        for key in ("CPU", "GPU"):
            sys_row.addWidget(QLabel(key, objectName="meterLabel"))
            bar = QProgressBar(objectName="sysBar", textVisible=False, maximum=1000)
            val = QLabel("—", objectName="meterLabel")
            val.setMinimumWidth(118 if key == "GPU" else 40)
            sys_row.addWidget(bar, 1)
            sys_row.addWidget(val)
            if key == "CPU":
                sys_row.addSpacing(14)
            self.sys_bars[key] = (bar, val)
        sv.addLayout(sys_row)
        self.sysmon = SysMonitor(self)
        self.sysmon.updated.connect(self._on_sys)
        self.stage_foot = QLabel("ALISA CORP. · BIOACOUSTIC MONITOR · SECTOR B-7", objectName="stageFoot")
        sv.addWidget(self.stage_foot)
        body.addWidget(stage, 1)

        self.toast = QLabel(stage, objectName="toast")
        self.toast.hide()
        self._toast_timer = QTimer(self, singleShot=True, interval=1600, timeout=self.toast.hide)

        # side column
        side = QFrame(objectName="side")
        side.setFixedWidth(380)
        av = QVBoxLayout(side)
        av.setContentsMargins(16, 16, 12, 8)
        av.setSpacing(10)
        label_row = QHBoxLayout()
        self.now_label = QLabel("СЕЙЧАС", objectName="sectionLabel")
        label_row.addWidget(self.now_label)
        label_row.addStretch(1)
        self.unpin_btn = QToolButton(objectName="unpinBtn", text="✕  к последней")
        self.unpin_btn.setCursor(Qt.PointingHandCursor)
        self.unpin_btn.setToolTip("Снять выбор (Esc)")
        self.unpin_btn.clicked.connect(lambda: self.history.clearSelection())
        # keep its space when hidden: otherwise the label row changes height and the card jumps by a few px
        sp = self.unpin_btn.sizePolicy(); sp.setRetainSizeWhenHidden(True); self.unpin_btn.setSizePolicy(sp)
        self.unpin_btn.hide()
        label_row.addWidget(self.unpin_btn)
        av.addLayout(label_row)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=lambda: self.history.clearSelection())
        card = QFrame(objectName="card")
        self.card = card
        cv = QVBoxLayout(card)
        cv.setContentsMargins(14, 12, 14, 12)
        cv.setSpacing(10)
        self.card_text = QPlainTextEdit(objectName="cardText", readOnly=True)
        self.card_text.setFrameShape(QFrame.NoFrame)
        self.card_text.setFixedHeight(104)
        self.card_text.setPlaceholderText("Удерживайте Right Alt и говорите — текст появится здесь.")
        self.shimmer = Shimmer()
        self.shimmer.setFixedHeight(104)
        self.shimmer.hide()
        cv.addWidget(self.card_text)
        cv.addWidget(self.shimmer)
        meta = QHBoxLayout()
        meta.setSpacing(10)
        self.card_meta = QLabel("—", objectName="cardMeta")
        self.card_meta.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        meta.addWidget(self.card_meta, 1)
        self.copy_btn = QPushButton("⧉  Копировать", objectName="copyBtn", enabled=False)
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(lambda: self._copy(self._shown_text, self.copy_btn))
        meta.addWidget(self.copy_btn)
        cv.addLayout(meta)
        av.addWidget(card)
        av.addSpacing(12)

        self.history = HistoryPanel(self.engine.transcription_dir)
        self.history.copyRequested.connect(lambda text: self._copy(text))
        self.history.previewStarted.connect(self._preview)
        self.history.previewEnded.connect(self._preview_end_timer.start)
        self.history.entrySelected.connect(self._on_selected)
        self.history.selectionCleared.connect(self._on_selection_cleared)
        av.addWidget(self.history, 1)
        body.addWidget(side)

        # footer
        footer = QFrame(objectName="footer")
        footer.setFixedHeight(34)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 0, 16, 0)
        self.foot_hint = QLabel()
        fl.addWidget(self.foot_hint)
        fl.addStretch(1)
        self.foot_last = QLabel("last —", objectName="footStat")
        fl.addWidget(self.foot_last)
        fl.addSpacing(18)
        fl.addWidget(QLabel("pre-roll 0.5 s", objectName="footStat"))
        fl.addSpacing(18)
        fl.addWidget(QLabel("16 kHz mono", objectName="footStat"))
        v.addWidget(footer)
        self._update_hints()

    def _chips(self):
        e = self.engine
        model = Path(e.model_path or "—").name.replace("ggml-", "").replace(".bin", "")
        model = model.replace("-q5_0", " q5").replace("-q8_0", " q8")
        mic = "default" if e.audio_device is None else str(e.audio_device)
        return (("lang", e.language or "auto"), ("model", model), ("mic", mic))

    def _settings_menu(self) -> QMenu:
        m = QMenu(self)
        tm = m.addMenu("Тема")
        grp = QActionGroup(self)
        self.theme_actions = {}
        for name, label in (("neon", "Neon"), ("umbrella", "Umbrella"), ("hive", "Umbrella Dark")):
            a = QAction(label, self, checkable=True)
            a.triggered.connect(lambda _=False, n=name: self.apply_theme(n))
            grp.addAction(a)
            tm.addAction(a)
            self.theme_actions[name] = a
        self.lang_menu = m.addMenu("Язык речи")
        lgrp = QActionGroup(self)
        self.lang_actions = {}
        for code, label in LANGUAGES:
            a = QAction(label, self, checkable=True)
            a.setChecked(self.engine.language == code)
            a.triggered.connect(lambda _=False, c=code: self._set_language(c))
            lgrp.addAction(a)
            self.lang_menu.addAction(a)
            self.lang_actions[code] = a
        m.addSeparator()
        for key, label, default, setter in (
            ("auto_copy", "Автокопирование в буфер", True, lambda v: setattr(self.engine, "auto_copy", v)),
            ("notify", "Системные уведомления", False, lambda v: setattr(self.engine, "notify", v)),
            ("on_top", "Поверх всех окон", False, self._set_on_top),
        ):
            a = QAction(label, self, checkable=True)
            a.setChecked(self.settings.value(key, default, type=bool))
            a.toggled.connect(lambda v, k=key, s=setter: (self.settings.setValue(k, v), s(v), self._update_hints()))
            m.addAction(a)

        pm = m.addMenu("Автовставка в активное окно")
        pgrp = QActionGroup(self)
        for combo, label in (("off", "Выкл"), *((k, v[0]) for k, v in COMBOS.items())):
            a = QAction(label, self, checkable=True)
            a.setChecked(self.paste_combo == combo)
            a.setEnabled(combo == "off" or self.paster.available)
            a.triggered.connect(lambda _=False, c=combo: self._set_paste(c))
            pgrp.addAction(a)
            pm.addAction(a)
        if not self.paster.available:
            pm.setToolTip(f"Недоступно: {self.paster.error}")
        return m

    def _set_language(self, code: str):
        self.engine.language = code
        self.settings.setValue("language", code)
        if code in self.lang_actions:
            self.lang_actions[code].setChecked(True)
        if hasattr(self, "lang_chip"):
            self.lang_chip.setText(f"lang <b>{code}</b> ▾")
        self._show_toast("Язык речи: " + dict(LANGUAGES).get(code, code))

    def _set_paste(self, combo: str):
        self.paste_combo = combo
        self.settings.setValue("paste_combo", combo)
        self._update_hints()

    def _set_on_top(self, on: bool):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.show()

    # -------------------------------------------------------------- theming
    def apply_theme(self, name: str):
        t = THEMES.get(name, THEMES["neon"])
        self.theme = t
        self.settings.setValue("theme", t.name)
        QApplication.instance().setStyleSheet(stylesheet(t))
        self.brand.setText(t.title)
        self.logo.theme = t
        self.logo.update()
        self.shimmer.theme = t
        self.rec_btn.theme = t
        self.rec_btn.update()
        self.history.setTheme(t)
        self.wave.setTheme(t)
        self.stage_foot.setVisible(t.corp)
        self.theme_actions[t.name].setChecked(True)
        self._on_state(self._state)

    def set_mode(self, mode: str):
        self.settings.setValue("mode", mode)
        self.wave.setMode(mode)
        for b in self.seg_group.buttons():
            b.setChecked(b.property("mode") == mode)

    def _update_hints(self):
        key = "Right Alt"
        kbd = f"<span style='font-family:monospace; background:{self.theme.panel2 if hasattr(self, 'theme') else '#161b24'};'>&nbsp;{key}&nbsp;</span>"
        if self._state == "recording":
            self.ptt_hint.setText(f"Говорите — отпустите {kbd} для распознавания")
        else:
            self.ptt_hint.setText(f"Удерживайте {kbd} или кнопку")
        if self._paste_on():
            keys = COMBOS[self.paste_combo][0].split(" — ")[0]
            self.foot_hint.setText(f"Текст копируется и вставляется в активное окно ({keys})")
        elif self.engine.auto_copy:
            self.foot_hint.setText("Текст автоматически копируется в буфер после распознавания")
        else:
            self.foot_hint.setText("Автокопирование выключено — используйте кнопки «Копировать»")

    def _paste_on(self) -> bool:
        return self.paste_combo in COMBOS and self.paster.available

    # ---------------------------------------------------------- engine events
    def _on_state(self, state: str):
        self._state = state
        t = self.theme
        colors = {"idle": t.ready, "recording": t.rec, "transcribing": t.busy, "error": t.rec}
        texts = {"idle": "Готов", "recording": "Запись…", "transcribing": "Распознаю…", "error": "Ошибка"}
        self.dot.color = QColor(colors.get(state, t.ready))
        self.dot.blink = state == "recording"
        self.dot.update()
        self.status_text.setText(texts.get(state, state))
        self.wave.setActive(state == "recording")
        self.rec_btn.setActive(state == "recording")
        if state == "recording":
            self._rec_started = time.monotonic()
            self._clock.start()
        else:
            self._clock.stop()
        self.timer_lbl.setProperty("idle", state != "recording")
        repolish(self.timer_lbl)
        busy = state == "transcribing"
        self.shimmer.setVisible(busy)
        self.card_text.setVisible(not busy)
        self._update_hints()

    def _update_timer(self):
        s = time.monotonic() - self._rec_started
        self.timer_lbl.setText(f"{int(s // 60):02d}:{s % 60:04.1f}")

    # ------------------------------------------------- history hover preview
    @staticmethod
    def _stamp(when: datetime.datetime) -> str:
        today = datetime.date.today()
        if when.date() == today:
            day = "СЕГОДНЯ"
        elif when.date() == today - datetime.timedelta(days=1):
            day = "ВЧЕРА"
        else:
            day = when.strftime("%d.%m.%Y")
        return f"{day} {when:%H:%M}"

    def _render_card(self):
        """Card priority: hovered history row > selected (pinned) row > latest transcription."""
        if self._hover_item:
            text, when = self._hover_item
            mode, label = "preview", f"ИЗ ИСТОРИИ · {self._stamp(when)}"
            meta = "клик — выбрать  ·  ⧉ — копировать"
        elif self._pinned:
            text, when = self._pinned
            mode, label = "pinned", f"ВЫБРАНО · {self._stamp(when)}"
            meta = f"{len(text.split())} слов"
        else:
            text, mode, label, meta = self._last_text, "", "СЕЙЧАС", self._last_meta
        self.now_label.setText(label)
        if self.card_text.toPlainText() != text:     # keep the reader's scroll position otherwise
            self.card_text.setPlainText(text)
        self.card_meta.setText(meta)
        self.card_meta.setToolTip(meta)
        self._shown_text = text
        self.copy_btn.setEnabled(bool(text))
        self.unpin_btn.setVisible(self._pinned is not None)   # also while previewing other rows
        self.card.setProperty("preview", mode == "preview")
        self.card.setProperty("pinned", mode == "pinned")
        repolish(self.card)

    def _preview(self, text: str, when: datetime.datetime):
        self._preview_end_timer.stop()
        if self._state == "transcribing":
            return
        self._hover_item = None if self._pinned == (text, when) else (text, when)
        self._render_card()

    def _end_preview(self):
        if self._hover_item is None:
            return
        self._hover_item = None
        self._render_card()

    def _on_selected(self, text: str, when: datetime.datetime):
        self._preview_end_timer.stop()
        self._hover_item = None
        self._pinned = (text, when)
        self._render_card()

    def _on_selection_cleared(self):
        self._pinned = None
        self._render_card()

    def _on_result(self, text: str, audio_s: float, transcribe_s: float, _path: str):
        self._preview_end_timer.stop()
        self._hover_item = None
        self._pinned = None
        self.history.clearSelection(notify=False)
        self._last_text = text
        self._last_meta = f"{audio_s:.1f} s  ·  whisper {transcribe_s:.1f} s"
        self._render_card()
        self.foot_last.setText(f"last {transcribe_s:.1f} s · {self.engine.last_device}")
        self.history.prepend(text, datetime.datetime.now())
        if self._paste_on():
            if not self.engine.auto_copy:
                copy_text(text)   # paste needs the text in the clipboard
            # small delay: let wl-copy take clipboard ownership before the paste shortcut fires
            QTimer.singleShot(150, lambda: self.paster.paste(self.paste_combo))
            self._flash_copied(self.copy_btn)
            self._show_toast("Вставлено в активное окно")
        elif self.engine.auto_copy:
            self._flash_copied(self.copy_btn)
            self._show_toast("Скопировано в буфер обмена")

    def _on_sys(self, cpu: float, gpu: float, used: float, total: float):
        bar, val = self.sys_bars["CPU"]
        bar.setValue(int(cpu * 10))
        val.setText(f"{cpu:.0f}%")
        bar, val = self.sys_bars["GPU"]
        if gpu < 0:
            bar.setValue(0)
            val.setText("н/д")
        else:
            bar.setValue(int(gpu * 10))
            val.setText(f"{gpu:.0f}% · {used / 1024:.1f}/{total / 1024:.0f} GB")
            val.setToolTip(f"Видеопамять занята {used:.0f} из {total:.0f} MiB")

    def _on_level(self, db: float):
        self.meter.setValue(int(max(0.0, min(1.0, (db + 60) / 60)) * 1000))
        self.db_lbl.setText(f"{db:.0f} dB")

    # ----------------------------------------------------------------- copy
    def _copy(self, text: str, button: QPushButton | None = None):
        if not text:
            return
        copy_text(text)
        if button:
            self._flash_copied(button)
        self._show_toast("Скопировано в буфер обмена")

    def _flash_copied(self, b: QPushButton):
        b.setProperty("copied", True)
        b.setText("✓  Скопировано")
        repolish(b)

        def back():
            b.setProperty("copied", False)
            b.setText("⧉  Копировать")
            repolish(b)
        QTimer.singleShot(1400, back)

    def _show_toast(self, msg: str, warn: bool = False):
        self.toast.setProperty("warn", warn)
        repolish(self.toast)
        self._toast_timer.setInterval(4500 if warn else 1600)
        self.toast.setText(("⚠  " if warn else "✓  ") + msg)
        self.toast.adjustSize()
        stage = self.toast.parentWidget()
        self.toast.move((stage.width() - self.toast.width()) // 2, 14)
        self.toast.raise_()
        self.toast.show()
        self._toast_timer.start()

    # ------------------------------------------------- frameless move/resize
    def _edges(self, pos) -> Qt.Edges:
        r = self.rect()
        e = Qt.Edges()
        if pos.x() <= EDGE:
            e |= Qt.LeftEdge
        if pos.x() >= r.width() - EDGE:
            e |= Qt.RightEdge
        if pos.y() <= EDGE:
            e |= Qt.TopEdge
        if pos.y() >= r.height() - EDGE:
            e |= Qt.BottomEdge
        return e

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            pos = ev.position().toPoint()
            edges = self._edges(pos)
            if edges:
                self.windowHandle().startSystemResize(edges)
                return
            if self.header.geometry().contains(pos):
                self.windowHandle().startSystemMove()
                return
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if self.header.geometry().contains(ev.position().toPoint()):
            self.showNormal() if self.isMaximized() else self.showMaximized()
        super().mouseDoubleClickEvent(ev)

    def mouseMoveEvent(self, ev):
        e = self._edges(ev.position().toPoint())
        shapes = {Qt.LeftEdge: Qt.SizeHorCursor, Qt.RightEdge: Qt.SizeHorCursor,
                  Qt.TopEdge: Qt.SizeVerCursor, Qt.BottomEdge: Qt.SizeVerCursor,
                  Qt.LeftEdge | Qt.TopEdge: Qt.SizeFDiagCursor, Qt.RightEdge | Qt.BottomEdge: Qt.SizeFDiagCursor,
                  Qt.RightEdge | Qt.TopEdge: Qt.SizeBDiagCursor, Qt.LeftEdge | Qt.BottomEdge: Qt.SizeBDiagCursor}
        if e in shapes:
            self.setCursor(shapes[e])
        else:
            self.unsetCursor()
        super().mouseMoveEvent(ev)

    # ---------------------------------------------------------------- close
    def closeEvent(self, ev):
        self.listener.stop()
        self.paster.close()
        self.engine._stop_mic_stream()
        self.engine.audio.terminate()
        super().closeEvent(ev)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("voice2clip")
    app.setDesktopFileName("voice2clip")
    app.setWindowIcon(QIcon(str(ICON)))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
