#!/usr/bin/env bash
#
# claude-manager installer.
#
#   curl -fsSL https://raw.githubusercontent.com/busi-reddy-karnati/claude-manager/main/install.sh | bash
#
# What it does: downloads the claude-manager source, builds a single
# self-contained executable with your local Python (zipapp, no dependencies),
# and installs it to ~/.local/bin/claude-manager.
#
# Configurable via environment variables:
#   CLAUDE_MANAGER_REPO     GitHub owner/repo   (default: busi-reddy-karnati/claude-manager)
#   CLAUDE_MANAGER_REF      branch/tag/commit   (default: main)
#   CLAUDE_MANAGER_BIN_DIR  install directory   (default: $HOME/.local/bin)

set -euo pipefail

REPO="${CLAUDE_MANAGER_REPO:-busi-reddy-karnati/claude-manager}"
REF="${CLAUDE_MANAGER_REF:-main}"
BIN_DIR="${CLAUDE_MANAGER_BIN_DIR:-$HOME/.local/bin}"
APP_NAME="claude-manager"

# --- pretty output ---------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
  YELLOW=$'\033[33m'; CYAN=$'\033[36m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; CYAN=""; RESET=""
fi
info()  { printf '%s\n' "${CYAN}${BOLD}claude-manager${RESET} $*"; }
warn()  { printf '%s\n' "${YELLOW}warning:${RESET} $*" >&2; }
die()   { printf '%s\n' "${RED}error:${RESET} $*" >&2; exit 1; }

# --- prerequisites ---------------------------------------------------------
PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
[ -n "$PY" ] || die "Python 3.9+ is required but no 'python3' was found on PATH."

"$PY" - <<'PYEOF' || die "Python 3.9+ is required (found an older version)."
import sys
sys.exit(0 if sys.version_info >= (3, 9) else 1)
PYEOF

DL=""
if command -v curl >/dev/null 2>&1; then DL="curl"; fi
if [ -z "$DL" ] && command -v wget >/dev/null 2>&1; then DL="wget"; fi
[ -n "$DL" ] || die "Need 'curl' or 'wget' to download the source."
command -v tar >/dev/null 2>&1 || die "Need 'tar' to unpack the source."

# --- download + build ------------------------------------------------------
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

TARBALL_URL="https://github.com/${REPO}/archive/${REF}.tar.gz"
info "downloading ${DIM}${REPO}@${REF}${RESET}"
if [ "$DL" = "curl" ]; then
  curl -fsSL "$TARBALL_URL" -o "$TMP/src.tar.gz" \
    || die "Failed to download $TARBALL_URL"
else
  wget -qO "$TMP/src.tar.gz" "$TARBALL_URL" \
    || die "Failed to download $TARBALL_URL"
fi

mkdir -p "$TMP/extract"
tar -xzf "$TMP/src.tar.gz" -C "$TMP/extract"
SRC_ROOT="$(find "$TMP/extract" -maxdepth 1 -mindepth 1 -type d | head -n1)"
[ -d "$SRC_ROOT/claude_manager" ] \
  || die "Downloaded source is missing the claude_manager package."

info "building single-file executable"
mkdir -p "$TMP/stage"
cp -R "$SRC_ROOT/claude_manager" "$TMP/stage/"
"$PY" -m zipapp "$TMP/stage" \
  -m "claude_manager.cli:main" \
  -p "/usr/bin/env python3" \
  -o "$TMP/$APP_NAME"
chmod 0755 "$TMP/$APP_NAME"

# Sanity check the artifact actually runs.
"$TMP/$APP_NAME" --version >/dev/null 2>&1 \
  || die "Built executable failed to run."

# --- install ---------------------------------------------------------------
mkdir -p "$BIN_DIR"
cp "$TMP/$APP_NAME" "$BIN_DIR/$APP_NAME"
chmod 0755 "$BIN_DIR/$APP_NAME"
VERSION="$("$BIN_DIR/$APP_NAME" --version 2>/dev/null || echo "$APP_NAME")"

printf '\n'
info "${GREEN}installed${RESET} ${VERSION} ${DIM}→${RESET} ${BOLD}${BIN_DIR}/${APP_NAME}${RESET}"

# --- PATH guidance ---------------------------------------------------------
case ":$PATH:" in
  *":$BIN_DIR:"*)
    printf '\n%s\n' "Run ${BOLD}${APP_NAME}${RESET} to get started."
    ;;
  *)
    printf '\n%s\n' "${YELLOW}${BIN_DIR} is not on your PATH.${RESET} Add this to your shell profile:"
    printf '\n    %s\n\n' "export PATH=\"${BIN_DIR}:\$PATH\""
    printf '%s\n' "Then restart your shell and run ${BOLD}${APP_NAME}${RESET}."
    ;;
esac
