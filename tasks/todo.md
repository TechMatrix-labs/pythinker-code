# Plan: Full rename `pythinker-cli` → `pythinker-code`

**Status**: Planning — DO NOT execute yet. User to review and approve.
**Created**: 2026-05-07
**Estimated effort**: 4–6 hours focused work, plus 1–2 hours of unanticipated breakage debugging.
**Risk**: HIGH. Touches 393 Python files (3,061 occurrences) plus binary build, web UI, telemetry, agents, examples, and 4 CI workflows. One missed reference can break the standalone binary build, the web UI, or runtime tool-loading.

---

## Goal

Make `pythinker-code` the canonical Python package and module name. After this rename:

```bash
pip install pythinker-code     # canonical install
pythinker --help               # CLI command (unchanged)
python -c "import pythinker_code"   # canonical import
```

`pythinker-cli` (the PyPI name + Python module) is retired. Existing PyPI releases of `pythinker-cli==1.0.0` continue to work for anyone who installed them, but no new versions of `pythinker-cli` will ship.

---

## Why this is risky

Discovered during inventory:

1. **Attribute naming, not just imports**: `joint_session.pythinker_cli_session` and `session.pythinker_cli_session` are property names used across `src/pythinker_cli/web/api/sessions.py` (10+ uses) and `src/pythinker_cli/web/runner/worker.py`. Renaming these is a structural code change, not a search-and-replace.

2. **Dynamic tool imports** in agent YAMLs: `agents/default/coder.yaml` and others reference tool classes via dotted import path strings: `"pythinker_cli.tools.shell:Shell"`. Runtime errors if the import path is wrong, AND lots of these are in user-facing example agents.

3. **PyInstaller binary build**: `pythinker.spec` line 4: `from pythinker_cli.utils.pyinstaller import datas, hiddenimports`, line 13: `["src/pythinker_cli/cli/__main__.py"]`. Standalone executables won't build if these aren't updated, and PyInstaller errors are notoriously cryptic.

4. **Telemetry path regex**: `src/pythinker_cli/telemetry/sentry.py` filters stack frames with `r"^(.*?)(site-packages|pythinker_cli|src/pythinker_cli)/"`. After rename, error reports get noisier until this is fixed.

5. **60+ references in `examples/`** including `pyproject.toml` dependencies — these are reference code users copy. They have to match the canonical name post-rename.

6. **50+ docs files** (`docs/en/`, `tasks_ai/`, `AGENTS.md`, `CONTRIBUTING.md`, `README.md`) reference `pythinker-cli` and `pythinker_cli`.

7. **Workflow files**: 4 `.github/workflows/release-pythinker-*.yml` files. The cli workflow file is referenced in PyPI's trusted publisher records — renaming the file means re-registering the publishers on PyPI dashboard.

8. **PyPI dashboard state**: trusted publishers configured today reference `release-pythinker-cli.yml`. Either keep the workflow filename (less ideal — naming inconsistency) or rename and re-register on PyPI.

---

## Scope summary

| Item | Count |
|------|-------|
| Python files w/ `pythinker_cli` references | 393 |
| Total `pythinker_cli` occurrences in Python | 3,061 |
| Non-Python files w/ references | 50+ |
| Examples referencing the name | 60 |
| Workflow YAMLs to update | 4 |
| `pyproject.toml` files affected | 5 |
| Agent YAML files w/ dotted import paths | 5+ |
| Files touched in total | ~470 |

---

## Architecture decision

**Option A (chosen):** Make `packages/pythinker-code/` the new ROOT package. The current root `pyproject.toml` becomes a thin alias declaring `pythinker-cli` (kept for one release as a deprecation shim, then dropped in 1.1.0).

**Why this layout:**
- The Python module rename `pythinker_cli` → `pythinker_code` is ONE tree move, not a directory swap
- Workspace tooling stays sane
- Existing GitHub Actions workflow filenames can stay (just updated content)
- We keep PyPI's trusted publisher registrations intact (workflow filenames stable)

**Trade-off:** The root directory contains the alias instead of the canonical package, which is mildly weird structurally. But it's far less invasive than a full directory swap.

---

## Phases

### Phase 0 — Pre-flight (15 min)

- [ ] **Confirm test suite passes on `main`** before any changes:
  ```bash
  uv sync --frozen --all-extras --all-packages
  uv run pytest tests -x --co -q | head -30   # smoke: tests collect
  ```
- [ ] **Create branch** `rename/pythinker-code` from current `main` (db9545e or later):
  ```bash
  git switch -c rename/pythinker-code
  ```
- [ ] **Snapshot current state**: tag `pre-rename-snapshot` so we can `git diff` later:
  ```bash
  git tag pre-rename-snapshot
  ```
- [ ] **Document the old → new mapping** in this file (below) so we can grep-verify completeness.

#### Name mappings reference

| Old | New |
|-----|-----|
| `pythinker-cli` (PyPI name) | `pythinker-code` |
| `pythinker_cli` (Python module) | `pythinker_code` |
| `pythinker_cli_session` (attribute) | `pythinker_code_session` |
| `src/pythinker_cli/` | `src/pythinker_code/` |
| `release-pythinker-cli.yml` (workflow) | **KEEP** — see Phase 5 |
| `[tool.uv.workspace]` member `pythinker-cli` | `pythinker-code` |
| Telemetry/log service name `pythinker_cli` | `pythinker_code` |

The CLI command `pythinker` stays. The `pythinker-cli` CLI alias also stays (we publish `pythinker-cli` as a thin alias package for one release).

---

### Phase 1 — Module directory rename (30 min)

Single atomic move with git so history is preserved:

- [ ] `git mv src/pythinker_cli src/pythinker_code`
- [ ] Spot-check that `git log --follow src/pythinker_code/__main__.py` shows full history.
- [ ] DO NOT touch any file contents yet. Commit:
  ```bash
  git commit -m "chore: rename src/pythinker_cli/ -> src/pythinker_code/"
  ```

At this point the tree is broken (393 files import a module that doesn't exist by that name). Phase 2 fixes it.

---

### Phase 2 — Python import rewrite (60 min)

This is the biggest mechanical change. Use `sed` for the bulk pass, then verify by hand.

- [ ] **Bulk substitution** (preserving identifiers and strings):
  ```bash
  # All Python files
  find src tests tests_ai tests_e2e packages sdks scripts examples -name "*.py" -type f \
    -exec sed -i 's/\bpythinker_cli\b/pythinker_code/g' {} +
  ```

- [ ] **Verify no orphan `pythinker_cli` strings remain in *.py**:
  ```bash
  grep -rn "pythinker_cli" --include="*.py" src/ packages/ sdks/ tests/ tests_e2e/ tests_ai/ scripts/ examples/ \
    | grep -v "pythinker_cli_session"
  ```
  Expect: empty output. Any hits are either:
  - Comments referencing the old name (ok to leave or update inline)
  - Strings that intentionally hold the old name (e.g. backward-compat fallbacks)

- [ ] **Handle `pythinker_cli_session` attribute renames separately** — these are part of the property API, not imports:
  ```bash
  find src tests -name "*.py" -type f \
    -exec sed -i 's/\bpythinker_cli_session\b/pythinker_code_session/g' {} +
  ```
  Verify that the dataclass/typed-dict that *defines* this attribute also got renamed (likely in `src/pythinker_code/web/runner/worker.py` or similar).

- [ ] **Run the test collector** to confirm all imports resolve:
  ```bash
  uv sync --frozen --all-extras --all-packages
  uv run pytest tests --co -q 2>&1 | tail -20
  ```
  Expect: tests collect without `ModuleNotFoundError`.

- [ ] **Spot-check import correctness** for known critical files:
  - `src/pythinker_code/__main__.py`
  - `src/pythinker_code/cli/__init__.py`
  - `src/pythinker_code/cli/__main__.py`
  - `src/pythinker_code/web/api/sessions.py`
  - `src/pythinker_code/telemetry/sentry.py` (regex must be updated to match new path)

- [ ] **Update telemetry path regex** in `sentry.py`:
  ```python
  r"^(.*?)(site-packages|pythinker_code|src/pythinker_code)/"
  ```
  (Keep `pythinker_cli` if you want backward-compat for older stack frames, but it shouldn't be needed now that we control the codebase.)

- [ ] Commit:
  ```bash
  git commit -am "refactor: rewrite pythinker_cli imports to pythinker_code"
  ```

---

### Phase 3 — pyproject.toml + workspace surgery (45 min)

Three pyprojects change roles. The current state:

| File | Today | After |
|------|-------|-------|
| `pyproject.toml` (root) | declares `pythinker-cli` w/ all deps + scripts | declares `pythinker-cli` (thin alias depending on `pythinker-code==1.1.0`); minimal stub |
| `packages/pythinker-code/pyproject.toml` | declares `pythinker-code` w/ alias dep on `pythinker-cli==1.0.0` | becomes the canonical package: full deps, scripts, web/vis bundled, classifiers, urls |
| `packages/pythinker-cli/pyproject.toml` | does not exist | NEW — moved from root, but role-flipped to be the alias |

Wait — this is confusing. Let me restate the cleaner approach.

**Cleaner approach:** Don't ship `pythinker-cli` at all in 1.1.0. Just retire it.

- [ ] **Move root pyproject contents** to `packages/pythinker-code/pyproject.toml`:
  - Copy `dependencies`, `dependency-groups`, `[project.scripts]`, `[project.urls]`, `classifiers`, `keywords` from root into `packages/pythinker-code/pyproject.toml`
  - Update `name = "pythinker-code"`, `version = "1.1.0"` (semver bump for breaking change in package layout)
  - Keep `module-name = ["pythinker_code"]` in `[tool.uv.build-backend]`
  - Add `license`, `license-files`, `authors` (already there from earlier work)

- [ ] **Decide root pyproject's fate** — pick one:
  - **Option A**: Delete root `pyproject.toml` entirely, move workspace config into a new top-level file. (Cleanest but might break tooling.)
  - **Option B**: Keep root `pyproject.toml` as a **dev/workspace-only** file with no package; uv can still treat the repo root as a workspace coordinator. Set `[project] name = "pythinker-monorepo"` private (do not publish).
  - **Option C** (recommended): Keep root `pyproject.toml` as a thin alias for `pythinker-cli==1.1.0` that just `dependencies = ["pythinker-code==1.1.0"]`. Ships ONCE in 1.1.0 to give existing pythinker-cli users a deprecation upgrade path. Skip in 1.2.0+.

  Recommend **Option C** for migration clarity.

- [ ] **Update `[tool.uv.workspace]`** members list — depends on Option chosen.
- [ ] **Update `[tool.uv.sources]`** to reflect new dependency wiring.
- [ ] Update `module-name` in root pyproject's `[tool.uv.build-backend]` if Option C — point it at a stub directory (or remove the section if there's no module to build).

- [ ] **Adjust `[project.scripts]`**:
  - In `packages/pythinker-code/pyproject.toml`: 
    ```toml
    [project.scripts]
    pythinker      = "pythinker_code.__main__:main"
    pythinker-cli  = "pythinker_code.__main__:main"   # legacy alias for one release
    pythinker-code = "pythinker_code.__main__:main"
    ```

- [ ] **Build all packages locally**:
  ```bash
  rm -rf dist/ packages/*/dist/ sdks/*/dist/
  uv build --package pythinker-code --no-sources --out-dir dist
  uv build --package pythinker-core --no-sources --out-dir dist
  uv build --package pythinker-host --no-sources --out-dir dist
  uv build --package pythinker-sdk  --no-sources --out-dir dist
  # If Option C:
  uv build --package pythinker-cli  --no-sources --out-dir dist
  ```
  All five must succeed.

- [ ] Commit:
  ```bash
  git commit -am "refactor: pyproject swap - pythinker-code as canonical, pythinker-cli as alias"
  ```

---

### Phase 4 — Build/release infrastructure (30 min)

- [ ] **Update `pythinker.spec` (PyInstaller)**:
  ```python
  from pythinker_code.utils.pyinstaller import datas, hiddenimports
  # ...
  ["src/pythinker_code/cli/__main__.py"],
  ```
- [ ] **Update `Makefile`** target body (Makefile target *names* can stay: `build-pythinker-cli` is just an internal alias, but rename for consistency):
  ```makefile
  build-pythinker-code: build-web build-vis
      @uv build --package pythinker-code --no-sources --out-dir dist
  ```
  Keep `build-pythinker-cli` as a deprecated alias that calls the new target if you want to avoid breaking developer muscle memory.
- [ ] **Update `scripts/build_web.py`** if it copies output into `src/pythinker_cli/web/...` — change to `src/pythinker_code/web/...`.
- [ ] **Update `scripts/build_vis.py`** likewise.
- [ ] **Update `scripts/check_pythinker_dependency_versions.py`** to validate `pythinker-code` vs old name.
- [ ] **Local sanity build**:
  ```bash
  make build-pythinker-code
  ls dist/   # verify pythinker_code-*.whl present
  ```
- [ ] **Local PyInstaller dry run** (catches the most catastrophic class of breakage early):
  ```bash
  PYINSTALLER_ONEDIR=1 make build-bin-onedir
  dist/onedir/pythinker/pythinker --version   # should print 1.1.0
  ```
- [ ] Commit.

---

### Phase 5 — Workflow files & PyPI publisher records (45 min)

**Decision**: Keep the workflow filenames as `release-pythinker-cli.yml` for one release cycle to avoid re-registering PyPI publishers, then rename to `release-pythinker-code.yml` in a follow-up.

- [ ] **Edit `.github/workflows/release-pythinker-cli.yml`**:
  - Update `make build-pythinker-cli` → `make build-pythinker-code`
  - Update `environment.url` to `https://pypi.org/project/pythinker-code/`
  - Validate-tag step: still uses root `pyproject.toml` version OR switch to `packages/pythinker-code/pyproject.toml` (depends on Option chosen in Phase 3)
- [ ] **Update `scripts/check_version_tag.py` callsites** in workflow if pyproject paths changed.
- [ ] **Update `scripts/check_pythinker_dependency_versions.py` callsite**.
- [ ] **PyPI dashboard work** (manual via Chrome MCP or browser):
  - Visit https://pypi.org/manage/project/pythinker-code/settings/publishing/
  - Confirm the pending publisher (`release-pythinker-cli.yml`, env=pypi) is still there. After 1.1.0 publishes, it'll convert to active.
  - If using Option C (keep cli alias for one release): confirm pythinker-cli's existing publisher still references `release-pythinker-cli.yml` with env=pypi. It will fire on 1.1.0 tag.
- [ ] Commit.

---

### Phase 6 — Documentation, examples, agent YAMLs (60 min)

This is mostly mechanical sed-replace, but every file needs a quick eyeball pass to make sure the rename reads naturally in prose.

- [ ] **README.md**: Replace `pythinker-cli` → `pythinker-code` in install commands, badges, package references. Lead the install section with `pip install pythinker-code`.
- [ ] **CONTRIBUTING.md**, **SECURITY.md**, **CHANGELOG.md**: Update package references.
- [ ] **`docs/en/**/*.md`**: 15+ files. Bulk sed first, then read each for prose oddity:
  ```bash
  find docs -name "*.md" -exec sed -i 's/pythinker-cli/pythinker-code/g; s/pythinker_cli/pythinker_code/g' {} +
  ```
- [ ] **`AGENTS.md`** (top-level + nested): same treatment.
- [ ] **`.agents/skills/**/*.md`**: same.
- [ ] **`tasks_ai/**/*.md`**: same.
- [ ] **`examples/**`** (60 references):
  - Update each `pyproject.toml` dependency line: `"pythinker-cli==1.0.0"` → `"pythinker-code==1.1.0"`
  - Update example READMEs and yaml files
- [ ] **Agent YAMLs** in `src/pythinker_code/agents/default/*.yaml`, `okabe/agent.yaml`:
  - Update tool import paths: `"pythinker_cli.tools.shell:Shell"` → `"pythinker_code.tools.shell:Shell"` (×30+)
  - These are CRITICAL — wrong paths cause runtime tool-loading failures, often only when a specific tool is invoked
- [ ] **`web/openapi.json` and `web/package.json`**: Update package name references.
- [ ] **`web/src/lib/api/docs/ConfigApi.md`**: doc reference.
- [ ] **Skill markdown** (`src/pythinker_code/skills/pythinker-cli-help/SKILL.md`): rename directory itself to `pythinker-code-help/` and update internal references.
- [ ] **Pre-commit config** `.pre-commit-config.yaml`: any path filters?
- [ ] **`.python-version`, `flake.nix`, `flake.lock`**: scan for references.
- [ ] Commit.

---

### Phase 7 — Verification (60 min)

- [ ] **Full test suite**:
  ```bash
  uv run pytest tests -v 2>&1 | tail -50
  ```
  Expect: same pass/fail rate as `pre-rename-snapshot`. Compare:
  ```bash
  git diff pre-rename-snapshot HEAD --stat -- 'tests/**' 'src/**'
  ```
- [ ] **`uv sync` clean**:
  ```bash
  rm -rf .venv uv.lock
  uv sync --frozen=false --all-extras --all-packages
  ```
- [ ] **Type check**:
  ```bash
  uv run pyright src/
  uv run ty check
  ```
  Expect: no new errors.
- [ ] **Ruff/lint**:
  ```bash
  uv run ruff check
  uv run ruff format --check
  ```
- [ ] **Smoke import**:
  ```bash
  uv run python -c "import pythinker_code; print(pythinker_code.__file__)"
  uv run python -c "from pythinker_code.cli import main"
  ```
- [ ] **Run the CLI**:
  ```bash
  uv run pythinker --version           # prints 1.1.0
  uv run pythinker --help               # full help text
  uv run pythinker-code --help          # alias works
  ```
- [ ] **PyInstaller binary** (the most common late-stage failure):
  ```bash
  rm -rf build/ dist/onedir/ dist/onefile/
  PYINSTALLER_ONEDIR=1 make build-bin-onedir
  dist/onedir/pythinker/pythinker --version   # 1.1.0
  ```
- [ ] **Web UI build** (if applicable):
  ```bash
  npm --prefix web run build
  ```
- [ ] **TestPyPI dry run** before PyPI:
  ```bash
  uv build --package pythinker-code --no-sources --out-dir dist
  uvx twine upload --repository testpypi dist/pythinker_code-1.1.0*
  ```
  Then smoke install:
  ```bash
  python -m venv /tmp/v && /tmp/v/bin/pip install \
    --index-url https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ \
    pythinker-code==1.1.0
  /tmp/v/bin/pythinker --version
  ```

---

### Phase 8 — Tag and release (30 min)

- [ ] Update `CHANGELOG.md` with 1.1.0 entry: rename, breaking changes, migration notes for users coming from `pythinker-cli==1.0.0`.
- [ ] Squash-merge `rename/pythinker-code` to `main` (or fast-forward if commits are clean):
  ```bash
  git switch main
  git merge --ff-only rename/pythinker-code
  git push origin main
  ```
- [ ] Tag and push:
  ```bash
  git tag -a 1.1.0 -m "v1.1.0: rename pythinker-cli to pythinker-code"
  git push origin 1.1.0
  ```
- [ ] **Watch the workflow**:
  ```bash
  gh run watch $(gh run list --workflow=release-pythinker-cli.yml --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status
  ```
- [ ] **Verify on PyPI**:
  ```bash
  pip index versions pythinker-code   # 1.1.0
  pip index versions pythinker-cli    # 1.0.0 + 1.1.0 (alias release)
  ```
- [ ] **Smoke install in clean venv**:
  ```bash
  python -m venv /tmp/v-final && /tmp/v-final/bin/pip install pythinker-code==1.1.0
  /tmp/v-final/bin/pythinker --version
  ```

---

### Phase 9 — Post-release cleanup (deferred to 1.2.0)

To do later, in a separate PR after we know 1.1.0 is healthy:

- [ ] Drop the `pythinker-cli` alias package — stop publishing it
- [ ] Rename workflow files: `release-pythinker-cli.yml` → `release-pythinker-code.yml` and update PyPI publisher records
- [ ] Remove `pythinker-cli` script entry from `[project.scripts]`
- [ ] Update root README to remove the migration callout
- [ ] Bump everything to 1.2.0

---

## Out of scope

- Renaming `pythinker-core`, `pythinker-host`, `pythinker-sdk` packages (their names are already fine)
- Renaming the GitHub repo itself (`mohamed-elkholy95/Pythinker-Code`) — name is already correct
- Breaking the public Python API (we're keeping `import pythinker_code` ergonomic; the *internal* import path changes but the module's public API surface stays the same)
- Migrating user data directories (the rename creates a new path, but no existing user data exists yet — by user statement)

---

## Risks and rollback

If anything goes catastrophically wrong:

```bash
# On the rename branch, before merging to main:
git switch main           # back to clean state, rename branch unaffected

# After merging, if 1.1.0 is broken on PyPI:
# Yank the broken release (don't unpublish — that's permanent)
twine ... # PyPI doesn't have CLI yank; do it via dashboard
```

PyPI 1.0.0 of pythinker-cli stays published forever. Anyone who installed it before 1.1.0 ships keeps working. 1.1.0 of pythinker-cli (the alias) and pythinker-code (canonical) ship together.

---

## Success criteria

- [ ] `pip install pythinker-code` from real PyPI in a clean venv succeeds
- [ ] `pythinker --version` prints `1.1.0`
- [ ] `import pythinker_code` works; `import pythinker_cli` does NOT (after 1.2.0)
- [ ] PyInstaller binary on GitHub Releases for v1.1.0 runs and prints `1.1.0`
- [ ] All tests pass at the same rate as `pre-rename-snapshot`
- [ ] No new pyright/ty errors
- [ ] Documentation (README, docs/, examples/) leads with `pythinker-code` everywhere

---

## Open questions — ANSWER BEFORE EXECUTION

1. **Do you want to ship `pythinker-cli==1.1.0` as a one-shot deprecation alias** (Option C in Phase 3), or **drop it cold-turkey at 1.1.0** (Option A/B)? Cold-turkey is simpler but anyone who happened to grab `pythinker-cli==1.0.0` won't be migrated automatically.

2. **Workflow filename**: keep `release-pythinker-cli.yml` for one release (no PyPI publisher changes needed), or rename to `release-pythinker-code.yml` immediately (requires re-registering PyPI publishers, which we just did once and rate-limited)?

3. **Module name**: confirm `pythinker_code` is what you want for the Python module. Alternative: `pythinker` alone (cleaner but might collide with random PyPI projects).

4. **Migration text in README**: Do you want a "migrating from pythinker-cli" callout in 1.1.0's README, or just silently switch?

5. **CHANGELOG framing**: Is this a breaking change that warrants 2.0.0, or a layout change that's fine at 1.1.0? PyPI users perspective: install command changed, that's user-visible breakage. Could argue 2.0.0.
