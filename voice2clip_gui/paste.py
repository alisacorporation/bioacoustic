"""Paste the transcription into whichever window has focus by emulating the paste shortcut.

A kernel uinput virtual keyboard (python-evdev) is used, so this works on Wayland for every
app — terminals running Claude Code, browsers, messengers — without xdotool/ydotool.
Needs write access to /dev/uinput (granted to the logged-in user via ACL on most distros).
"""

import time

try:
    from evdev import UInput, ecodes as e
except ImportError:  # pragma: no cover - optional dependency
    UInput = None
    e = None

# label shown in the menu → key sequence (held together, released in reverse)
COMBOS = {
    "ctrl+shift+v": ("Ctrl+Shift+V — терминал, Claude Code", ("KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_V")),
    "ctrl+v": ("Ctrl+V — обычные программы", ("KEY_LEFTCTRL", "KEY_V")),
}


class Paster:
    def __init__(self):
        self._ui = None
        self.error = ""
        if UInput is None:
            self.error = "python-evdev не установлен"
            return
        try:
            keys = sorted({getattr(e, k) for _, seq in COMBOS.values() for k in seq})
            # created once at startup: the compositor needs a moment to pick up a new device
            self._ui = UInput({e.EV_KEY: keys}, name="voice2clip-paste")
        except Exception as ex:  # no /dev/uinput access, module missing, ...
            self.error = str(ex)

    @property
    def available(self) -> bool:
        return self._ui is not None

    def paste(self, combo: str) -> bool:
        if not self._ui or combo not in COMBOS:
            return False
        codes = [getattr(e, k) for k in COMBOS[combo][1]]
        for c in codes:
            self._ui.write(e.EV_KEY, c, 1)
            self._ui.syn()
            time.sleep(0.008)
        time.sleep(0.02)
        for c in reversed(codes):
            self._ui.write(e.EV_KEY, c, 0)
            self._ui.syn()
            time.sleep(0.008)
        return True

    def close(self):
        if self._ui:
            self._ui.close()
            self._ui = None
