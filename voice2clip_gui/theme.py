"""Colour tokens and the app-wide stylesheet for the two themes (Neon, Umbrella).

Everything is square on purpose: no border-radius anywhere except the status dot.
Mirrors design/mockup.html.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Theme:
    name: str
    title: str
    win: str
    panel: str
    panel2: str
    line: str
    header_line: str
    text: str
    muted: str
    dim: str
    accent: str          # main accent (buttons, highlights)
    accent2: str         # second gradient stop
    on_accent: str       # text colour on accent buttons
    label: str           # section labels
    ok: str              # "copied" state
    on_ok: str
    rec: str             # record button / recording dot
    busy: str            # transcribing dot
    ready: str           # idle dot
    glow: str            # radial glow behind the wave (rgba)
    waves: tuple = field(default_factory=tuple)   # 4 sine colours
    scope: str = ""
    bar_lo: str = ""
    bar_hi: str = ""
    grid: str = ""
    peak: str = ""
    meter: tuple = field(default_factory=tuple)   # level meter gradient stops
    corp: bool = False   # Umbrella styling: emblem, spaced caps brand, lab footer line


NEON = Theme(
    name="neon", title="ALISA CORPORATION",
    win="#0e1116", panel="#12161d", panel2="#161b24", line="#1f2632", header_line="#1f2632",
    text="#e6ebf2", muted="#7d8899", dim="#4c5666",
    accent="#3ee6ff", accent2="#9b6bff", on_accent="#071017", label="#4c5666",
    ok="#3ddc97", on_ok="#071017", rec="#ff4d6a", busy="#ffb547", ready="#3ddc97",
    glow="rgba(62,230,255,16)",
    waves=("#3ee6ff", "#9b6bff", "#ff5fa8", "#5b8cff"),
    scope="#3ee6ff", bar_lo="#3ee6ff", bar_hi="#9b6bff",
    grid="rgba(255,255,255,10)", peak="#e6ebf2",
    meter=("#3ddc97", "#3ee6ff", "#ffb547", "#ff4d6a"),
)

UMBRELLA = Theme(
    name="umbrella", title="ALISA CORPORATION",
    win="#0a0a0b", panel="#111113", panel2="#161618", line="#26262a", header_line="#3a0a12",
    text="#f2f2f2", muted="#8e8e93", dim="#5a5a60",
    accent="#ff1f3d", accent2="#a00018", on_accent="#ffffff", label="#a0101f",
    ok="#f2f2f2", on_ok="#0a0a0b", rec="#e4002b", busy="#ff7a1a", ready="#e8e8e8",
    glow="rgba(228,0,43,26)",
    waves=("#ff1f3d", "#b0001e", "#f2f2f2", "#ff6b4a"),
    scope="#ff1f3d", bar_lo="#5c0010", bar_hi="#e4002b",
    grid="rgba(228,0,43,18)", peak="#f2f2f2",
    meter=("#4a0009", "#a00018", "#e4002b", "#ff4d4d"),
    corp=True,
)

# Darker sibling of Umbrella: near-pure black, dense dried-blood reds, dimmed whites.
HIVE = Theme(
    name="hive", title="ALISA CORPORATION",
    win="#050505", panel="#0a0a0b", panel2="#0f0f10", line="#1c1c1f", header_line="#2a0509",
    text="#e8e6e6", muted="#807c7d", dim="#4d494a",
    accent="#b3001b", accent2="#4a0008", on_accent="#ffffff", label="#7a0a16",
    ok="#e8e6e6", on_ok="#050505", rec="#9e0018", busy="#c2410c", ready="#b8b4b4",
    glow="rgba(140,0,20,30)",
    waves=("#b3001b", "#6e000f", "#d8d4d4", "#8c1c10"),
    scope="#c0001d", bar_lo="#2e0005", bar_hi="#a00018",
    grid="rgba(160,0,24,16)", peak="#d8d4d4",
    meter=("#2a0005", "#6e000f", "#a00018", "#d0102a"),
    corp=True,
)

THEMES = {t.name: t for t in (NEON, UMBRELLA, HIVE)}

MONO = '"JetBrains Mono", "Fira Code", "DejaVu Sans Mono", monospace'
SANS = '"Manrope", "Inter", "Noto Sans", sans-serif'


def alpha(hex_color: str, a: int) -> str:
    """'#rrggbb' + alpha 0..255 → QSS rgba() (QSS hex alpha is #AARRGGBB, easy to get wrong)."""
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}, {a})"


def stylesheet(t: Theme) -> str:
    m0, m1, m2, m3 = t.meter
    return f"""
* {{ font-family: {SANS}; color: {t.text}; outline: none; }}
QMainWindow, #root {{ background: {t.win}; }}
QToolTip {{ background: {t.panel2}; color: {t.text}; border: 1px solid {t.line}; padding: 6px; }}

/* header */
#header {{ background: {t.panel}; border-bottom: 1px solid {t.header_line}; }}
#brand {{ font-size: 15px; font-weight: 700; letter-spacing: {"2.5px" if t.corp else "0.2px"}; }}
#brandVer {{ font-family: {MONO}; color: {t.muted}; font-size: 10px; letter-spacing: 2px; }}
#chip {{ font-family: {MONO}; font-size: 11px; color: {t.muted}; padding: 4px 9px;
         background: {t.panel}; border: 1px solid {t.line}; }}
QToolButton#chip {{ padding: 0px 9px; }}
QToolButton#chip::menu-indicator {{ image: none; width: 0; }}
QToolButton#chip:hover {{ color: {t.text}; border-color: {t.dim}; }}
#status {{ font-size: 12px; color: {t.muted}; padding: 4px 11px; background: {t.panel};
           border: 1px solid {t.line}; }}
#hdrBtn {{ background: transparent; border: 1px solid transparent; color: {t.muted};
           min-width: 30px; min-height: 30px; font-size: 15px; }}
#hdrBtn::menu-indicator {{ image: none; width: 0; }}
#hdrBtn:hover {{ background: {t.panel2}; border-color: {t.line}; color: {t.text}; }}

/* stage */
#stage {{ background: {t.win}; border-right: 1px solid {t.line}; }}
#sectionLabel {{ font-size: 11px; font-weight: 600; letter-spacing: 2px; color: {t.label}; }}
#seg {{ background: {t.panel}; border: 1px solid {t.line}; }}
#segBtn {{ background: transparent; border: 1px solid transparent; color: {t.muted};
           padding: 5px 11px; font-size: 12px; }}
#segBtn:checked {{ background: {t.panel2}; border-color: {t.line}; color: {t.text}; }}
#ptt {{ background: {t.panel}; border: 1px solid {t.line}; }}
#pttHint {{ color: {t.muted}; font-size: 13px; }}
#recBtn {{ background: qradialgradient(cx:0.35, cy:0.3, radius:0.9, fx:0.35, fy:0.3,
            stop:0 {alpha(t.rec, 170)}, stop:1 {t.rec}); border: 4px solid {alpha(t.rec, 50)};
           min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px; }}
#recBtn[active="true"] {{ border: 4px solid {alpha(t.rec, 120)}; }}
#timer {{ font-family: {MONO}; font-size: 26px; font-weight: 500; color: {t.text}; }}
#timer[idle="true"] {{ color: {t.dim}; }}
#meterLabel {{ font-family: {MONO}; font-size: 11px; color: {t.dim}; }}
#meter {{ background: {t.panel2}; border: none; max-height: 6px; min-height: 6px; }}
#meter::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                 stop:0 {m0}, stop:0.6 {m1}, stop:0.85 {m2}, stop:1 {m3}); }}
#sysBar {{ background: {t.panel2}; border: none; max-height: 4px; min-height: 4px; }}
#sysBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t.accent2}, stop:1 {t.accent}); }}
#stageFoot {{ font-family: {MONO}; font-size: 9px; letter-spacing: 2px; color: #3a3a40; }}
#toast[warn="true"] {{ color: {t.busy}; border: 1px solid {alpha(t.busy, 110)}; }}
#toast {{ background: {t.panel2}; color: {t.ok}; border: 1px solid {alpha(t.ok, 90)};
          padding: 7px 14px; font-size: 12px; }}

/* side */
#side {{ background: {t.panel}; }}
#card {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {t.panel2}, stop:1 {t.panel});
         border: 1px solid {t.line}; border-top: 2px solid {t.accent}; }}
#card[preview="true"] {{ border-top: 2px solid {t.accent2}; background: {t.panel}; }}
#card[pinned="true"] {{ border-top: 2px solid {t.accent}; border-left: 1px solid {t.accent2}; }}
#unpinBtn {{ background: transparent; border: none; color: {t.dim}; font-size: 11px; padding: 0 2px; }}
#unpinBtn:hover {{ color: {t.accent}; }}
#cardText {{ font-size: 14px; color: {t.text}; background: transparent; border: none;
             selection-background-color: {t.accent2}; }}
#cardMeta {{ font-family: {MONO}; font-size: 11px; color: {t.dim}; }}
#copyBtn {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {t.accent}, stop:1 {t.accent2});
            color: {t.on_accent}; border: none; padding: 7px 14px; font-weight: 600; font-size: 12px; }}
#copyBtn:hover {{ background: {t.accent}; }}
#copyBtn[copied="true"] {{ background: {t.ok}; color: {t.on_ok}; }}
#copyBtn:disabled {{ background: {t.panel2}; color: {t.dim}; }}

/* history (history.py) */
#historyCount {{ font-family: {MONO}; font-size: 11px; color: {t.dim}; }}
#historySearch {{ background: {t.panel2}; border: 1px solid {t.line}; padding: 5px 8px;
                  font-size: 12px; color: {t.text}; selection-background-color: {t.accent2}; }}
#historySearch:focus {{ border-color: {t.accent}; }}
#historyList {{ background: transparent; border: none; }}
#historyList > QWidget {{ background: transparent; }}
#dayHeader {{ font-size: 10px; font-weight: 600; letter-spacing: 1.5px; color: {t.dim}; padding: 10px 8px 4px 8px; }}
#historyItem {{ background: transparent; border: 1px solid transparent; }}
#historyItem[hover="true"] {{ background: {t.panel2}; border-color: {t.line}; }}
#historyItem[copied="true"] {{ border-color: {t.ok}; }}
#historyTime {{ font-family: {MONO}; font-size: 11px; color: {t.dim}; }}
#historyText {{ font-size: 13px; color: {t.muted}; }}
#historyItem[hover="true"] #historyText {{ color: {t.text}; }}
#copyIcon {{ background: transparent; border: none; color: {t.dim}; }}
#copyIcon:hover {{ background: {t.panel}; color: {t.accent}; }}
#historyEmpty {{ color: {t.dim}; padding: 20px; }}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {t.line}; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t.dim}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}

/* footer */
#footer {{ background: {t.win}; border-top: 1px solid {t.header_line}; }}
#footer QLabel {{ font-size: 11px; color: {t.dim}; }}
#footStat {{ font-family: {MONO}; }}

QMenu {{ background: {t.panel2}; border: 1px solid {t.line}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; }}
QMenu::item:selected {{ background: {t.panel}; color: {t.accent}; }}
"""
