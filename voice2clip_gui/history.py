"""History panel: previous transcriptions, newest first, grouped by day.

Rendering is virtualised (QListView + painting delegate): only the visible
rows are drawn, so thousands of entries scroll smoothly. Rows are copied on
the copy icon; clicking elsewhere on a row selects it (pins it in the
window's top card), clicking it again deselects. Hovering previews.
"""

from __future__ import annotations

import datetime
import json
import textwrap
import time
from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QEvent, QModelIndex, QObject, QPersistentModelIndex, QRectF,
                            QRunnable, QSize, Qt, QThreadPool, QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QListView, QStyle,
                               QStyledItemDelegate, QStyleOptionViewItem, QVBoxLayout, QWidget)

from .theme import NEON, Theme

__all__ = ["HistoryPanel"]

_THIN_SPACE = " "
_COPY_FLASH_MS = 900
_SEARCH_DEBOUNCE_MS = 150
_TOOLTIP_WIDTH = 60
_ROW_H = 38
_HEADER_H = 30
_SCROLL_QUIET_S = 0.25   # no hover preview while the list is moving under the cursor

_MONTHS_GENITIVE = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}

Entry = tuple[datetime.datetime, str]

KIND_ROLE = Qt.UserRole + 1
WHEN_ROLE = Qt.UserRole + 2
TEXT_ROLE = Qt.UserRole + 3


def _format_count(value: int) -> str:
    """Format an integer with a thin space as thousands separator."""
    return f"{value:,}".replace(",", _THIN_SPACE)


def _day_title(day: datetime.date) -> str:
    """Return the Russian day caption for a date."""
    today = datetime.date.today()
    if day == today:
        return "Сегодня"
    if day == today - datetime.timedelta(days=1):
        return "Вчера"
    return f"{day.day} {_MONTHS_GENITIVE[day.month]} {day.year}"


def _single_line(text: str) -> str:
    """Collapse a text to a single line for display purposes."""
    return " ".join(text.split())


# ---------------------------------------------------------------- loading
class _LoaderSignals(QObject):
    """Signals emitted by the background history loader."""

    loaded = Signal(list)


class _HistoryLoader(QRunnable):
    """Reads and parses all transcription files off the UI thread."""

    def __init__(self, directory: Path) -> None:
        super().__init__()
        self.signals = _LoaderSignals()
        self._directory = directory

    def run(self) -> None:
        try:
            entries = self._collect()
        except Exception:  # pragma: no cover - defensive, never surface to UI
            entries = []
        self.signals.loaded.emit(entries)

    def _collect(self) -> list[Entry]:
        entries: list[Entry] = []
        try:
            paths = sorted(self._directory.glob("*.json"))
        except OSError:
            return entries

        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                text = payload["transcription"]
                when = datetime.datetime.fromisoformat(payload["timestamp"])
            except (OSError, KeyError, TypeError, ValueError):
                continue
            if not isinstance(text, str):
                continue
            if when.tzinfo is not None:
                try:
                    when = when.astimezone().replace(tzinfo=None)
                except (OSError, ValueError):
                    continue
            entries.append((when, text))

        entries.sort(key=lambda entry: entry[0], reverse=True)
        return entries


# ------------------------------------------------------------------ model
class _HistoryModel(QAbstractListModel):
    """Flat list of day headers and entries for the current filter."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # ("header", title) | ("empty", message) | ("entry", when, text, one_line)
        self._rows: list[tuple] = []

    def set_entries(self, entries: list[Entry], empty_text: str | None) -> None:
        self.beginResetModel()
        rows: list[tuple] = []
        day = None
        for when, text in entries:
            if when.date() != day:
                day = when.date()
                rows.append(("header", _day_title(day).upper()))
            rows.append(("entry", when, text, _single_line(text)))
        if not rows and empty_text:
            rows.append(("empty", empty_text))
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt API
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        kind = row[0]
        if role == KIND_ROLE:
            return kind
        if role == Qt.DisplayRole:
            return row[3] if kind == "entry" else row[1]
        if kind != "entry":
            return None
        if role == WHEN_ROLE:
            return row[1]
        if role == TEXT_ROLE:
            return row[2]
        if role == Qt.ToolTipRole:
            return textwrap.fill(row[2], _TOOLTIP_WIDTH)
        return None

    def flags(self, index: QModelIndex):
        if index.isValid() and self._rows[index.row()][0] == "entry":
            return Qt.ItemIsEnabled
        return Qt.NoItemFlags


# --------------------------------------------------------------- delegate
class _HistoryDelegate(QStyledItemDelegate):
    """Paints headers and entry rows using the active theme colours."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.theme: Theme = NEON
        self.flash: QPersistentModelIndex | None = None
        self.selected: Entry | None = None
        self._mono = QFont("JetBrains Mono")
        self._mono.setStyleHint(QFont.Monospace)
        self._mono.setPointSizeF(8.5)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        kind = index.data(KIND_ROLE)
        return QSize(option.rect.width(), _ROW_H if kind == "entry" else _HEADER_H)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        t = self.theme
        r = option.rect
        kind = index.data(KIND_ROLE)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if kind != "entry":
            f = QFont(option.font)
            f.setPointSizeF(7.5)
            f.setWeight(QFont.DemiBold)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
            p.setFont(f)
            p.setPen(QColor(t.dim))
            align = Qt.AlignCenter if kind == "empty" else Qt.AlignLeft | Qt.AlignBottom
            p.drawText(r.adjusted(8, 0, -8, -6), align, index.data(Qt.DisplayRole))
            p.restore()
            return

        when: datetime.datetime = index.data(WHEN_ROLE)
        hover = bool(option.state & QStyle.State_MouseOver)
        selected = self.selected is not None and self.selected == (when, index.data(TEXT_ROLE))
        flashed = self.flash is not None and self.flash.isValid() and self.flash.row() == index.row()
        box = QRectF(r).adjusted(0.5, 1.5, -0.5, -1.5)
        if hover or flashed or selected:
            p.fillRect(box, QColor(t.panel2))
            p.setPen(QPen(QColor(t.ok if flashed else (t.accent2 if selected else t.line)), 1))
            p.drawRect(box)
        if selected:
            p.fillRect(QRectF(box.left(), box.top(), 2, box.height()), QColor(t.accent))
        hover = hover or selected

        p.setFont(self._mono)
        p.setPen(QColor(t.dim))
        p.drawText(QRectF(r.left() + 8, r.top(), 44, r.height()), Qt.AlignVCenter | Qt.AlignLeft, f"{when:%H:%M}")

        icon = QRectF(r.right() - 30, r.center().y() - 7, 14, 14)
        text_rect = QRectF(r.left() + 58, r.top(), icon.left() - 10 - (r.left() + 58), r.height())
        p.setFont(option.font)
        p.setPen(QColor(t.text if hover else t.muted))
        elided = option.fontMetrics.elidedText(index.data(Qt.DisplayRole), Qt.ElideRight, int(text_rect.width()))
        p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)

        p.setPen(QPen(QColor(t.ok if flashed else (t.accent if hover else t.dim)), 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(icon.adjusted(4, 0, 0, -4))
        p.drawRect(icon.adjusted(0, 4, -4, 0))
        p.restore()


# ------------------------------------------------------------------ panel
class HistoryPanel(QWidget):
    """Panel listing previous transcriptions with search and copy support."""

    copyRequested = Signal(str)
    countChanged = Signal(int)
    previewStarted = Signal(str, object)   # hovered row: (text, datetime)
    previewEnded = Signal()
    entrySelected = Signal(str, object)    # clicked row (outside the copy icon): (text, datetime)
    selectionCleared = Signal()

    def __init__(self, transcription_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: list[Entry] = []
        self._loaded = False
        self._last_scroll = 0.0
        self._build_ui()

        self._search_timer = QTimer(self, singleShot=True, interval=_SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._apply_filter)
        self._flash_timer = QTimer(self, singleShot=True, interval=_COPY_FLASH_MS)
        self._flash_timer.timeout.connect(self._clear_flash)

        self._loader = _HistoryLoader(transcription_dir)
        self._loader.signals.loaded.connect(self._on_loaded)
        QThreadPool.globalInstance().start(self._loader)

    # -- public API ---------------------------------------------------------
    def prepend(self, text: str, when: datetime.datetime) -> None:
        """Insert a freshly transcribed entry at the top of the list."""
        self._entries.insert(0, (when, text))
        self._update_count()
        self._apply_filter()

    def total(self) -> int:
        """Return the number of loaded entries, ignoring the filter."""
        return len(self._entries)

    def clearSelection(self, notify: bool = True) -> None:  # noqa: N802 - Qt naming
        if self._delegate.selected is None:
            return
        self._delegate.selected = None
        self._view.viewport().update()
        if notify:
            self.selectionCleared.emit()

    def setTheme(self, theme: Theme) -> None:  # noqa: N802 - Qt naming
        self._delegate.theme = theme
        self._view.viewport().update()

    # -- construction -------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(QLabel("ИСТОРИЯ", self, objectName="sectionLabel"))
        self._count_label = QLabel("0", self, objectName="historyCount")
        header.addWidget(self._count_label)
        header.addStretch(1)
        self._search = QLineEdit(self, objectName="historySearch", placeholderText="Поиск…")
        self._search.setClearButtonEnabled(True)
        self._search.setMaximumWidth(190)
        self._search.textChanged.connect(lambda _t: self._search_timer.start())
        header.addWidget(self._search)

        self._model = _HistoryModel(self)
        self._delegate = _HistoryDelegate(self)
        self._view = QListView(self, objectName="historyList")
        self._view.setModel(self._model)
        self._view.setItemDelegate(self._delegate)
        self._view.setFrameShape(QListView.NoFrame)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._view.verticalScrollBar().setSingleStep(16)
        self._view.setSelectionMode(QAbstractItemView.NoSelection)
        self._view.setMouseTracking(True)
        self._view.setCursor(Qt.PointingHandCursor)
        self._view.viewport().setAttribute(Qt.WA_Hover, True)
        self._view.viewport().installEventFilter(self)
        self._view.entered.connect(self._on_entered)
        self._view.verticalScrollBar().valueChanged.connect(self._on_scrolled)

        layout.addLayout(header)
        layout.addWidget(self._view, 1)

    # -- events -------------------------------------------------------------
    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt API
        if obj is self._view.viewport():
            if event.type() == QEvent.Leave:
                self.previewEnded.emit()
            elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                self._on_clicked(event.position().toPoint())
        return super().eventFilter(obj, event)

    def _on_scrolled(self, _value: int) -> None:
        self._last_scroll = time.monotonic()
        self.previewEnded.emit()

    def _on_entered(self, index: QModelIndex) -> None:
        if time.monotonic() - self._last_scroll < _SCROLL_QUIET_S:
            return
        if index.data(KIND_ROLE) == "entry":
            self.previewStarted.emit(index.data(TEXT_ROLE), index.data(WHEN_ROLE))
        else:
            self.previewEnded.emit()

    def _on_clicked(self, pos) -> None:
        index = self._view.indexAt(pos)
        if not index.isValid() or index.data(KIND_ROLE) != "entry":
            return
        text, when = index.data(TEXT_ROLE), index.data(WHEN_ROLE)
        if pos.x() >= self._view.visualRect(index).right() - 40:   # copy icon zone
            self._delegate.flash = QPersistentModelIndex(index)
            self._view.viewport().update()
            self._flash_timer.start()
            self.copyRequested.emit(text)
            return
        if self._delegate.selected == (when, text):
            self.clearSelection()
            return
        self._delegate.selected = (when, text)
        self._view.viewport().update()
        self.entrySelected.emit(text, when)

    def _clear_flash(self) -> None:
        self._delegate.flash = None
        self._view.viewport().update()

    # -- data ---------------------------------------------------------------
    def _on_loaded(self, entries: list[Entry]) -> None:
        self._loaded = True
        # Entries prepended before the load finished are already saved on disk,
        # so the disk snapshot supersedes them (avoids duplicates).
        self._entries = list(entries)
        self._update_count()
        self._apply_filter()

    def _update_count(self) -> None:
        total = len(self._entries)
        self._count_label.setText(_format_count(total))
        self.countChanged.emit(total)

    def _apply_filter(self) -> None:
        needle = self._search.text().strip().casefold()
        visible = [e for e in self._entries if needle in e[1].casefold()] if needle else self._entries
        self._delegate.flash = None
        self._model.set_entries(visible, "Ничего не найдено" if self._loaded else None)
