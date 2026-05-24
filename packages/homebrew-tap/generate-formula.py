"""Generate the Homebrew Formula for pythinker-code from the just-published
PyPI release.

Runs in the homebrew-tap.yml workflow after PyPI has the new version.
Expects ``pythinker-code==<VERSION>`` to already be installed into the
current Python environment so we can enumerate its transitive deps via
``pip freeze``.

Usage:
    python generate-formula.py \\
        --version 0.14.0 \\
        --template packages/homebrew-tap/pythinker-code.rb.tmpl \\
        --output Formula/pythinker-code.rb

We do not use ``homebrew-pypi-poet`` — that package was last updated in
2018, still imports ``pkg_resources`` (removed in setuptools 81), and
crashes on modern packages whose metadata declares extras like
``html_clean``. Reimplementing the relevant bits is < 40 lines.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

PYPI_PROJECT_JSON = "https://pypi.org/pypi/{name}/{version}/json"


def fetch_sdist_metadata(name: str, version: str) -> tuple[str, str]:
    """Return (sdist_url, sdist_sha256) for the given package/version on PyPI."""
    url = PYPI_PROJECT_JSON.format(name=name, version=version)
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.load(resp)
    for f in data.get("urls", []):
        if f.get("packagetype") == "sdist":
            return f["url"], f["digests"]["sha256"]
    raise RuntimeError(f"no sdist on PyPI for {name}=={version}")


def list_dependencies(root_package: str) -> list[tuple[str, str]]:
    """Return [(name, version), ...] for every dep of root_package except itself.

    We rely on ``pip freeze`` of the venv we're running in, which lists the
    full transitive closure after ``pip install pythinker-code==<ver>``.
    """
    res = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--exclude", root_package],
        check=True,
        capture_output=True,
        text=True,
    )
    deps: list[tuple[str, str]] = []
    for line in res.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-e "):
            continue
        # Skip editable installs / VCS pins that don't have a clean PyPI sdist.
        if " @ " in line or line.startswith("file:") or line.startswith("git+"):
            continue
        if "==" not in line:
            continue
        name, version = line.split("==", 1)
        deps.append((name.strip(), version.strip()))
    return deps


def render_resource(name: str, version: str) -> str:
    """Render a single Homebrew `resource` stanza for one PyPI package."""
    url, sha = fetch_sdist_metadata(name, version)
    return f'  resource "{name}" do\n    url "{url}"\n    sha256 "{sha}"\n  end\n'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--template", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    sdist_url, sdist_sha = fetch_sdist_metadata("pythinker-code", args.version)
    deps = list_dependencies("pythinker-code")
    print(f"enumerated {len(deps)} transitive deps from pip freeze")

    resource_blocks: list[str] = []
    for name, version in deps:
        try:
            resource_blocks.append(render_resource(name, version))
        except Exception as exc:
            print(f"WARN: skipping {name}=={version}: {exc}", file=sys.stderr)
    resources = "\n".join(resource_blocks).rstrip()

    tmpl = args.template.read_text(encoding="utf-8")
    formula = (
        tmpl.replace("__SDIST_URL__", sdist_url)
        .replace("__SDIST_SHA256__", sdist_sha)
        .replace("__RESOURCES__", resources)
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(formula, encoding="utf-8")

    digest = hashlib.sha256(formula.encode("utf-8")).hexdigest()
    print(f"formula written to {args.output}")
    print(f"sdist URL    : {sdist_url}")
    print(f"sdist sha256 : {sdist_sha}")
    print(f"resources    : {len(resource_blocks)}")
    print(f"formula sha  : {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
