#!/usr/bin/bash

# ------------------------------------------------
# 1.  Create/activate a virtualenv in ".venv"
# ------------------------------------------------
if [ ! -d ".venv" ]; then
    echo "[+] Creating venv..."
    python3 -m venv .venv
fi

source .venv/bin/activate

# ------------------------------------------------
# 2.  Install / update required Python packages
# ------------------------------------------------
echo "[+] Installing Python deps..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pip install --upgrade -r "$SCRIPT_DIR/../requirements.txt"

# ------------------------------------------------
# 3.  Prepend Instant Client to PATH for this session
# ------------------------------------------------
export PATH="$SCRIPT_DIR/../instantclient_23_8:$PATH"

# ------------------------------------------------
# 4.  Launch the GUI
# ------------------------------------------------
echo "[+] Launching database GUI..."
python "$SCRIPT_DIR/../src/dbgui.py"