#!/usr/bin/env bash
# Pythinker Code — native curl-bash installer.
#
# Downloads the PyInstaller-built single-file binary for your OS + arch from
# the latest GitHub Release, verifies its SHA-256, and installs it at
#   ~/.local/bin/pythinker
#
# Usage:
#   curl -fsSL https://pythinker.com/install.sh | bash
#
#   # Pin a specific version:
#   curl -fsSL https://pythinker.com/install.sh | bash -s -- --version 0.24.0
#
#   # Custom install prefix (default $HOME/.local):
#   curl -fsSL https://pythinker.com/install.sh | bash -s -- --prefix /opt/pythinker
#
# Supported targets (target triples — matches existing release artifacts):
#   x86_64-unknown-linux-gnu       (Linux x86_64)
#   aarch64-unknown-linux-gnu      (Linux ARM64)
#   aarch64-apple-darwin           (macOS Apple Silicon)
#   x86_64-apple-darwin            (macOS Intel)
#
# Windows users: download PythinkerSetup-x.y.z.exe from the Releases page.
set -euo pipefail

VERSION=""
INSTALL_PREFIX="${PYTHINKER_INSTALL_PREFIX:-$HOME/.local}"
NO_COLOR="${NO_COLOR:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --prefix)  INSTALL_PREFIX="$2"; shift 2 ;;
    -h|--help)
      sed -n '1,/^set -euo/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

REPO="TechMatrix-labs/pythinker-code"

if [ -t 1 ] && [ -z "$NO_COLOR" ] && [ "${TERM:-}" != "dumb" ]; then
  NAVY=$'\033[38;5;24m'; FACE=$'\033[38;5;255m'
  IRIS=$'\033[38;5;152m'; CORAL=$'\033[38;5;216m'; DIM=$'\033[2m'
  BOLD=$'\033[1m'; RESET=$'\033[0m'
  HIDE_CURSOR=$'\033[?25l'; SHOW_CURSOR=$'\033[?25h'
else
  NAVY=""; FACE=""; IRIS=""; CORAL=""; DIM=""; BOLD=""; RESET=""
  HIDE_CURSOR=""; SHOW_CURSOR=""
fi

# Static logo. Used as the animation fallback (non-TTY, NO_COLOR, dumb term,
# CI, or PYTHINKER_NO_ANIMATION=1) and as the source of truth for the final
# settled frame.
print_logo_static() {
  printf '\n'
  printf '      %s●%s\n'                                        "$CORAL" "$RESET"
  printf '      %s│%s\n'                                        "$NAVY"  "$RESET"
  printf '  %s▛%s%s▀▀▀▀▀▀▀%s%s▜%s\n'                            "$NAVY" "$RESET" "$FACE" "$RESET" "$NAVY" "$RESET"
  printf ' %s◖%s%s█%s %s◉%s   %s◉%s %s█%s%s◗%s\n'               "$CORAL" "$RESET" "$NAVY" "$RESET" "$IRIS" "$RESET" "$IRIS" "$RESET" "$NAVY" "$RESET" "$CORAL" "$RESET"
  printf '  %s▙▄▄▄%s%s≡%s%s▄▄▄▟%s\n'                            "$NAVY" "$RESET" "$FACE" "$RESET" "$NAVY" "$RESET"
  printf '\n'
  printf '  %s%spythinker code%s %s· your next CLI agent%s\n\n' "$BOLD" "$FACE" "$RESET" "$DIM" "$RESET"
}

# Tetris-style animated logo. Pieces fall from above the canvas one at a time
# and settle into a 5-row × 13-col grid forming the robot head.
print_logo_animated() {
  local ROWS=5 COLS=13
  local FRAME_DELAY="${PYTHINKER_LOGO_FRAME_DELAY:-0.06}"
  local STAGGER_DELAY="${PYTHINKER_LOGO_STAGGER_DELAY:-0.04}"

  local -a grid_chars grid_colors
  local i
  for ((i=0; i<ROWS*COLS; i++)); do
    grid_chars[i]=" "
    grid_colors[i]=""
  done

  _set_cell() {
    grid_chars[$(( $1 * COLS + $2 ))]="$3"
    grid_colors[$(( $1 * COLS + $2 ))]="$4"
  }

  _render() {
    local piece_r="$1" piece_c="$2"
    shift 2
    local -a cells=("$@")
    local -a tc=("${grid_chars[@]}") tk=("${grid_colors[@]}")

    if [ -n "$piece_r" ]; then
      local cell dr dc ch color rr cc
      for cell in "${cells[@]}"; do
        IFS=',' read -r dr dc ch color <<<"$cell"
        rr=$((piece_r + dr)); cc=$((piece_c + dc))
        if (( rr >= 0 && rr < ROWS && cc >= 0 && cc < COLS )); then
          tc[$((rr*COLS+cc))]="$ch"
          tk[$((rr*COLS+cc))]="$color"
        fi
      done
    fi

    local r c idx color ch line
    for ((r=0; r<ROWS; r++)); do
      line=""
      for ((c=0; c<COLS; c++)); do
        idx=$((r*COLS+c))
        color="${tk[$idx]}"; ch="${tc[$idx]}"
        if [ -n "$color" ]; then line+="${color}${ch}${RESET}"; else line+="$ch"; fi
      done
      printf '%s\033[K\n' "$line"
    done
  }

  _drop_piece() {
    local target_r=$1 target_c=$2; shift 2
    local -a cells=("$@")
    local r
    for ((r=-1; r<=target_r; r++)); do
      printf '\033[%dA\r' "$ROWS"
      _render "$r" "$target_c" "${cells[@]}"
      sleep "$FRAME_DELAY"
    done
    local cell dr dc ch color
    for cell in "${cells[@]}"; do
      IFS=',' read -r dr dc ch color <<<"$cell"
      _set_cell $((target_r + dr)) $((target_c + dc)) "$ch" "$color"
    done
    if [ "$STAGGER_DELAY" != "0" ]; then sleep "$STAGGER_DELAY"; fi
  }

  printf '%s' "$HIDE_CURSOR"
  trap 'printf "%s" "$SHOW_CURSOR"' EXIT
  trap 'printf "%s" "$SHOW_CURSOR"; exit 130' INT
  trap 'printf "%s" "$SHOW_CURSOR"; exit 143' TERM
  for ((i=0; i<ROWS; i++)); do printf '\n'; done

  _drop_piece 2 2  "0,0,▛,$NAVY" "1,0,█,$NAVY" "2,0,▙,$NAVY"
  _drop_piece 2 10 "0,0,▜,$NAVY" "1,0,█,$NAVY" "2,0,▟,$NAVY"
  _drop_piece 2 3  "0,0,▀,$FACE" "0,1,▀,$FACE" "0,2,▀,$FACE" "0,3,▀,$FACE" "0,4,▀,$FACE" "0,5,▀,$FACE" "0,6,▀,$FACE"
  _drop_piece 4 3  "0,0,▄,$NAVY" "0,1,▄,$NAVY" "0,2,▄,$NAVY" "0,3,≡,$FACE" "0,4,▄,$NAVY" "0,5,▄,$NAVY" "0,6,▄,$NAVY"
  _drop_piece 3 4  "0,0,◉,$IRIS"
  _drop_piece 3 8  "0,0,◉,$IRIS"
  _drop_piece 3 1  "0,0,◖,$CORAL"
  _drop_piece 3 11 "0,0,◗,$CORAL"
  _drop_piece 1 6  "0,0,│,$NAVY"
  _drop_piece 0 6  "0,0,●,$CORAL"

  printf '\n'
  printf '  %s%spythinker code%s %s· your next CLI agent%s\n\n' "$BOLD" "$FACE" "$RESET" "$DIM" "$RESET"
  printf '%s' "$SHOW_CURSOR"
  trap - EXIT INT TERM
}

print_logo() {
  if [ -n "${PYTHINKER_NO_ANIMATION:-}" ] || [ -n "${CI:-}" ] \
     || [ ! -t 1 ] || [ -n "$NO_COLOR" ] || [ "${TERM:-}" = "dumb" ]; then
    print_logo_static
  else
    print_logo_animated
  fi
}

step() { printf '  %s⠿%s %s\n' "$IRIS" "$RESET" "$1"; }
ok()   { printf '  %s✓%s %s\n' "$IRIS" "$RESET" "$1"; }
fail() { printf '  %s✗%s %s\n' "$CORAL" "$RESET" "$1" >&2; exit 1; }

print_logo

# --- detect target -------------------------------------------------------
os="$(uname -s)"
arch="$(uname -m)"
case "$os/$arch" in
  Linux/x86_64|Linux/amd64)
    target="x86_64-unknown-linux-gnu" ;;
  Linux/aarch64|Linux/arm64)
    target="aarch64-unknown-linux-gnu" ;;
  Darwin/arm64)
    target="aarch64-apple-darwin" ;;
  Darwin/x86_64)
    target="x86_64-apple-darwin" ;;
  MINGW*/*|MSYS*/*|CYGWIN*/*)
    fail "On Windows, download PythinkerSetup-x.y.z.exe from:
https://github.com/${REPO}/releases/latest

PowerShell installer:
powershell -c \"irm https://pythinker.com/install.ps1 | iex\"" ;;
  *)
    fail "unsupported target: $os/$arch" ;;
esac

# --- resolve version -----------------------------------------------------
if [ -z "$VERSION" ]; then
  step "Looking up latest Pythinker release"
  api="https://api.github.com/repos/${REPO}/releases/latest"
  if command -v curl >/dev/null 2>&1; then
    payload="$(curl -fsSL "$api")"
  elif command -v wget >/dev/null 2>&1; then
    payload="$(wget -qO- "$api")"
  else
    fail "need curl or wget to fetch the release index"
  fi
  VERSION="$(printf '%s' "$payload" | sed -nE 's/.*"tag_name": *"v([0-9]+\.[0-9]+\.[0-9]+)".*/\1/p' | head -n 1)"
  [ -z "$VERSION" ] && fail "could not parse latest release tag from $api"
  ok "Latest version is $VERSION"
fi

tarball="pythinker-${VERSION}-${target}.tar.gz"
tarball_url="https://github.com/${REPO}/releases/download/v${VERSION}/${tarball}"
sha_url="${tarball_url}.sha256"

# --- download + verify --------------------------------------------------
tmpdir="$(mktemp -d -t pythinker-install.XXXXXX)"
trap 'rm -rf "$tmpdir"' EXIT
step "Downloading $tarball"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$tarball_url" -o "$tmpdir/$tarball" || fail "download failed: $tarball_url"
  curl -fsSL "$sha_url"     -o "$tmpdir/$tarball.sha256" || fail "sha256 missing: $sha_url"
else
  wget -q "$tarball_url" -O "$tmpdir/$tarball" || fail "download failed"
  wget -q "$sha_url"     -O "$tmpdir/$tarball.sha256" || fail "sha256 missing"
fi

step "Verifying SHA-256"
expected="$(awk '{print $1}' "$tmpdir/$tarball.sha256")"
if command -v sha256sum >/dev/null 2>&1; then
  actual="$(sha256sum "$tmpdir/$tarball" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  actual="$(shasum -a 256 "$tmpdir/$tarball" | awk '{print $1}')"
else
  fail "need sha256sum or shasum to verify the download"
fi
[ "$expected" != "$actual" ] && fail "SHA-256 mismatch: expected $expected, got $actual"
ok "Checksum OK"

# --- install -----------------------------------------------------------
bin_dir="$INSTALL_PREFIX/bin"
step "Installing into $bin_dir/pythinker"
mkdir -p "$bin_dir"
# The existing release tarball contains a single `pythinker` file at the
# tarball root (PyInstaller --onefile output).
tar -C "$tmpdir" -xzf "$tmpdir/$tarball"
[ -x "$tmpdir/pythinker" ] || fail "tarball did not contain an executable named 'pythinker'"
install -m 0755 "$tmpdir/pythinker" "$bin_dir/pythinker"
printf 'pythinker-native-build\n' > "$bin_dir/.pythinker-native"
ok "Installed $("$bin_dir/pythinker" --version 2>/dev/null || echo "pythinker $VERSION")"

# --- PATH guidance --------------------------------------------------------
case ":$PATH:" in
  *":$bin_dir:"*) ;;
  *)
    printf '\n  %sNote:%s %s is not on your PATH.\n' "$BOLD" "$RESET" "$bin_dir"
    printf '  Add this to your shell profile (~/.bashrc, ~/.zshrc, ~/.config/fish/config.fish):\n'
    printf '\n    %sexport PATH="%s:$PATH"%s\n\n' "$DIM" "$bin_dir" "$RESET"
    ;;
esac

printf '\n  %s%spythinker%s is ready. Run %s%spythinker%s to launch.\n\n' \
  "$BOLD" "$IRIS" "$RESET" "$BOLD" "$IRIS" "$RESET"
