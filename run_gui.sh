#!/bin/bash
# Launch the voice2clip GUI (creates .venv with PySide6 + numpy on first run)
set -e
cd "$(dirname "${BASH_SOURCE[0]}")"
if [ ! -x .venv/bin/python ]; then
    python3 -m venv --system-site-packages .venv
    .venv/bin/pip install -q PySide6 numpy
fi
exec .venv/bin/python -m voice2clip_gui "$@"
