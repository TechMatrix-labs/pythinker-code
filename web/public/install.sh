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
#   curl -fsSL https://pythinker.com/install.sh | bash -s -- --version 0.17.0
#
#   # Custom install prefix (default $HOME/.local):
#   curl -fsSL https://pythinker.com/install.sh | bash -s -- --prefix /opt/pythinker
#
# Supported targets (target triples — matches existing release artifacts):
#   x86_64-unknown-linux-gnu       (Linux x86_64)
#   aarch64-unknown-linux-gnu      (Linux ARM64)
#   aarch64-apple-darwin           (macOS Apple Silicon)
#
# Windows users: download PythinkerSetup-x.y.z.exe from the Releases page.
# Intel macOS: no native binary is published; use Homebrew or pip install.
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

REPO="mohamed-elkholy95/Pythinker-Code"

if [ -t 1 ] && [ -z "$NO_COLOR" ] && [ "${TERM:-}" != "dumb" ]; then
  IRIS=$'\033[38;5;152m'; CORAL=$'\033[38;5;216m'; DIM=$'\033[2m'
  BOLD=$'\033[1m'; RESET=$'\033[0m'
else
  IRIS=""; CORAL=""; DIM=""; BOLD=""; RESET=""
fi
step() { printf '  %s⠿%s %s\n' "$IRIS" "$RESET" "$1"; }
ok()   { printf '  %s✓%s %s\n' "$IRIS" "$RESET" "$1"; }
fail() { printf '  %s✗%s %s\n' "$CORAL" "$RESET" "$1" >&2; exit 1; }

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
    fail "No PyInstaller-built Intel macOS binary is published.
Use Homebrew (\`brew install mohamed-elkholy95/pythinker/pythinker-code\`),
or pip (\`pip install pythinker-code\`)." ;;
  MINGW*/*|MSYS*/*|CYGWIN*/*)
    fail "On Windows, download PythinkerSetup-x.y.z.exe from:
https://github.com/${REPO}/releases/latest

PowerShell installer:
powershell -c \"irm https://pythinker.com/install.ps1 | iex\" ;;
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

printf '\n  %s%spythinker%s is ready. Run %s%spythinker%s to start.\n\n' \
  "$BOLD" "$IRIS" "$RESET" "$BOLD" "$IRIS" "$RESET"
