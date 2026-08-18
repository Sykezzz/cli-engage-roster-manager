#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  SKYWARD → CLI ENGAGE  |  Mac / Linux Launcher
#  Double-click (Mac) or run  bash LAUNCH_MAC_LINUX.sh
#  to set everything up and launch the importer.
#  You only need to do full setup once.
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_SCRIPT="$SCRIPT_DIR/skyward_to_cliengage.py"

# ── Colours ───────────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
    CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; RESET=''
fi

info()    { echo -e "  ${CYAN}ℹ${RESET}  $*"; }
ok()      { echo -e "  ${GREEN}✓${RESET}  $*"; }
warn()    { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
err()     { echo -e "  ${RED}✗${RESET}  $*"; }
banner()  { echo; echo -e "${BOLD}══════════════════════════════════════════════════${RESET}"; \
            echo -e "${BOLD}  $*${RESET}"; \
            echo -e "${BOLD}══════════════════════════════════════════════════${RESET}"; echo; }

banner "Skyward → CLI Engage Roster Manager — Launcher"

# ── Verify main script exists ─────────────────────────────────────────────────
if [ ! -f "$PY_SCRIPT" ]; then
    err "Cannot find skyward_to_cliengage.py"
    echo "     Make sure LAUNCH_MAC_LINUX.sh and skyward_to_cliengage.py"
    echo "     are in the same folder."
    read -r -p "  Press Enter to exit..." _
    exit 1
fi

OS="$(uname -s)"

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 1 — FIND OR INSTALL PYTHON
# ═══════════════════════════════════════════════════════════════════════════════

PYTHON_CMD=""
for cmd in python3 python python3.12 python3.11 python3.10; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(sys.version_info[:2])" 2>/dev/null || true)
        # Require Python 3.8+
        if "$cmd" -c "import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)" 2>/dev/null; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -n "$PYTHON_CMD" ]; then
    PY_VER=$("$PYTHON_CMD" --version 2>&1)
    ok "Found compatible Python: $PY_VER  ($PYTHON_CMD)"
else
    warn "Python 3.8+ not found. Attempting automatic installation..."
    echo

    if [ "$OS" = "Darwin" ]; then
        # ── macOS ──────────────────────────────────────────────────────────────
        if command -v brew &>/dev/null; then
            info "Installing Python via Homebrew..."
            brew install python@3.12
            PYTHON_CMD="python3"
        else
            echo "  Homebrew (the Mac package manager) is not installed."
            echo "  The script will install Homebrew first, then Python."
            echo "  This may ask for your Mac password."
            echo
            if ! read -r -t 30 -p "  Press Enter to continue (or Ctrl+C to cancel)..." _; then
                echo
            fi
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            # Add brew to PATH for Apple Silicon
            if [ -f "/opt/homebrew/bin/brew" ]; then
                eval "$(/opt/homebrew/bin/brew shellenv)"
            fi
            brew install python@3.12
            PYTHON_CMD="python3"
        fi

    elif [ "$OS" = "Linux" ]; then
        # ── Linux ──────────────────────────────────────────────────────────────
        if command -v apt-get &>/dev/null; then
            info "Installing Python via apt (may need sudo password)..."
            sudo apt-get update -qq
            sudo apt-get install -y python3 python3-pip
            PYTHON_CMD="python3"
        elif command -v dnf &>/dev/null; then
            info "Installing Python via dnf..."
            sudo dnf install -y python3 python3-pip
            PYTHON_CMD="python3"
        elif command -v yum &>/dev/null; then
            info "Installing Python via yum..."
            sudo yum install -y python3 python3-pip
            PYTHON_CMD="python3"
        elif command -v pacman &>/dev/null; then
            info "Installing Python via pacman..."
            sudo pacman -Sy --noconfirm python python-pip
            PYTHON_CMD="python3"
        else
            err "Could not detect a package manager to install Python automatically."
        fi
    fi

    # Verify install worked
    if [ -z "$PYTHON_CMD" ] || ! command -v "$PYTHON_CMD" &>/dev/null; then
        err "Automatic Python installation did not succeed."
        echo
        if [ "$OS" = "Darwin" ]; then
            echo "  Please install Python manually:"
            echo "    1. Go to https://www.python.org/downloads/"
            echo "    2. Download and run the macOS installer."
            echo "    3. Re-run this launcher."
            open "https://www.python.org/downloads/" 2>/dev/null || true
        else
            echo "  Please install Python 3.8+ using your system's package manager, e.g.:"
            echo "    sudo apt-get install python3 python3-pip   (Debian/Ubuntu)"
            echo "    sudo dnf install python3 python3-pip       (Fedora/RHEL)"
            echo "  Then re-run this launcher."
        fi
        echo
        read -r -p "  Press Enter to exit..." _
        exit 1
    fi

    ok "Python installed: $($PYTHON_CMD --version 2>&1)"
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 2 — ENSURE pip IS AVAILABLE
# ═══════════════════════════════════════════════════════════════════════════════

if ! "$PYTHON_CMD" -m pip --version &>/dev/null; then
    info "pip not found — installing..."
    curl -sSL https://bootstrap.pypa.io/get-pip.py | "$PYTHON_CMD" || \
        { err "Could not install pip. Try: sudo apt-get install python3-pip"; exit 1; }
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 3 — INSTALL / VERIFY pandas
# ═══════════════════════════════════════════════════════════════════════════════

if "$PYTHON_CMD" -c "import pandas" &>/dev/null; then
    ok "pandas is already installed."
else
    info "Installing pandas (takes about 30 seconds)..."
    "$PYTHON_CMD" -m pip install --upgrade pip --quiet
    "$PYTHON_CMD" -m pip install pandas --quiet
    if ! "$PYTHON_CMD" -c "import pandas" &>/dev/null; then
        err "pandas installation failed."
        echo "  Try running manually:  pip3 install pandas"
        read -r -p "  Press Enter to exit..." _
        exit 1
    fi
    ok "pandas installed successfully."
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 4 — LAUNCH
# ═══════════════════════════════════════════════════════════════════════════════

info "Launching Skyward to CLI Engage Roster Manager..."
echo
cd "$SCRIPT_DIR"
"$PYTHON_CMD" "$PY_SCRIPT" "$@"

# Keep terminal open on error (helpful when launched via double-click on Mac)
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo
    err "The script exited with an error (code $EXIT_CODE)."
    echo "  Review the messages above for details."
    read -r -p "  Press Enter to close..." _
fi
