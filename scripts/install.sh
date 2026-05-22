#!/usr/bin/env bash
set -euo pipefail

# Colors — match src/pythinker_code/ui/shell/__init__.py logo palette.
# Skip if stdout isn't a TTY or NO_COLOR is set.
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-}" != "dumb" ]; then
  NAVY=$'\033[38;5;24m'
  FACE=$'\033[38;5;255m'
  CORAL=$'\033[38;5;216m'
  IRIS=$'\033[38;5;152m'
  DIM=$'\033[2m'
  BOLD=$'\033[1m'
  RESET=$'\033[0m'
  CLEAR_LINE=$'\r\033[K'
  HIDE_CURSOR=$'\033[?25l'
  SHOW_CURSOR=$'\033[?25h'
else
  NAVY=""; FACE=""; CORAL=""; IRIS=""; DIM=""; BOLD=""; RESET=""; CLEAR_LINE=""
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
# and settle into a 5-row × 13-col grid forming the robot head. Order matters:
# walls first, then the bars, then the face, then the antenna.
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

  # Render ROWS lines of the canvas with the optional falling piece overlay.
  # Args: piece_top_row piece_col cell1 cell2 ...; cell = "dr,dc,ch,color".
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

  printf '%s\n' "$HIDE_CURSOR"
  trap 'printf "%s" "$SHOW_CURSOR"' EXIT INT TERM
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
     || [ ! -t 1 ] || [ -n "${NO_COLOR:-}" ] || [ "${TERM:-}" = "dumb" ]; then
    print_logo_static
  else
    print_logo_animated
  fi
}

step() { printf '  %s⠿%s %s\n' "$IRIS" "$RESET" "$1"; }
ok()   { printf '  %s✓%s %s\n' "$IRIS" "$RESET" "$1"; }
warn() { printf '  %s!%s %s\n' "$CORAL" "$RESET" "$1" >&2; }
fail() { printf '  %s✗%s %s\n' "$CORAL" "$RESET" "$1" >&2; exit 1; }

# Spinner around a long command. Streams the command's output to a tmpfile;
# on failure, replays it so the user can debug.
spin_run() {
  local label="$1"; shift
  if [ ! -t 1 ]; then
    step "$label"
    "$@"
    return
  fi
  local log
  log="$(mktemp)"
  trap 'rm -f "$log"' RETURN
  "$@" >"$log" 2>&1 &
  local pid=$!
  local frames='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
  local i=0
  while kill -0 "$pid" 2>/dev/null; do
    local f="${frames:$((i % ${#frames})):1}"
    printf '%s  %s%s%s %s' "$CLEAR_LINE" "$IRIS" "$f" "$RESET" "$label"
    i=$((i + 1))
    sleep 0.08
  done
  wait "$pid"
  local rc=$?
  if [ $rc -eq 0 ]; then
    printf '%s' "$CLEAR_LINE"
    ok "$label"
  else
    printf '%s' "$CLEAR_LINE"
    fail "$label"$'\n'"$(cat "$log")"
  fi
  rm -f "$log"
  return $rc
}

install_uv_quietly() {
  if command -v curl >/dev/null 2>&1; then
    spin_run "Fetching uv (Python package installer)" \
      bash -c 'curl -fsSL https://astral.sh/uv/install.sh | sh -s -- --quiet >/dev/null 2>&1 || curl -fsSL https://astral.sh/uv/install.sh | sh >/dev/null 2>&1'
    return
  fi
  if command -v wget >/dev/null 2>&1; then
    spin_run "Fetching uv (Python package installer)" \
      bash -c 'wget -qO- https://astral.sh/uv/install.sh | sh >/dev/null 2>&1'
    return
  fi
  fail "curl or wget is required to install uv."
}

print_logo

# ---------------------------------------------------------------------------
# DEPRECATION NOTICE
#
# This uv-based shell installer is now a legacy install path. Pythinker
# ships native installers for every supported OS; new tooling and support
# docs target those installers exclusively.
#
# Recommended replacement:
#   - macOS:    brew install mohamed-elkholy95/pythinker/pythinker-code
#   - Linux:    sudo dpkg -i pythinker-code_*.deb  (or  sudo rpm -i ...)
#   - macOS / Linux without a package manager:
#       curl -fsSL https://raw.githubusercontent.com/mohamed-elkholy95/Pythinker-Code/main/scripts/install-native.sh | bash
#
# This script continues to work for existing automation. Set
# PYTHINKER_INSTALL_QUIET_DEPRECATION=1 to suppress this banner.
# ---------------------------------------------------------------------------
if [ -z "${PYTHINKER_INSTALL_QUIET_DEPRECATION:-}" ]; then
  printf '\n  %s[DEPRECATED]%s This uv-based installer is now a legacy path.\n' \
    "$BOLD$CORAL" "$RESET"
  printf '  Prefer the native installer for your OS:\n'
  printf '    %smacOS:%s   brew install mohamed-elkholy95/pythinker/pythinker-code\n' "$IRIS" "$RESET"
  printf '    %sLinux:%s   sudo dpkg -i pythinker-code_*.deb   # or   sudo rpm -i ...\n' "$IRIS" "$RESET"
  printf '    %sCross-OS:%s curl -fsSL https://raw.githubusercontent.com/mohamed-elkholy95/Pythinker-Code/main/scripts/install-native.sh | bash\n' "$IRIS" "$RESET"
  printf '  Continuing with the legacy uv install in 3s... (Ctrl-C to abort)\n\n'
  sleep 3
fi

if command -v uv >/dev/null 2>&1; then
  ok "uv already installed ($(uv --version 2>/dev/null | awk '{print $2}'))"
else
  install_uv_quietly
  # uv installer drops the binary in ~/.local/bin or ~/.cargo/bin; expose it.
  for candidate in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
    if [ -x "$candidate/uv" ] && [[ ":$PATH:" != *":$candidate:"* ]]; then
      export PATH="$candidate:$PATH"
    fi
  done
fi

if ! command -v uv >/dev/null 2>&1; then
  fail "uv not found after installation. Open a new shell and re-run."
fi

spin_run "Installing pythinker-code" \
  uv tool install --quiet --python 3.13 pythinker-code

printf '\n'
printf '  %s%spythinker%s is ready.\n'                       "$BOLD" "$FACE"  "$RESET"
printf '  %sRun%s %s%spythinker%s %sto start.%s\n\n'         "$DIM"  "$RESET" "$BOLD" "$IRIS" "$RESET" "$DIM" "$RESET"
