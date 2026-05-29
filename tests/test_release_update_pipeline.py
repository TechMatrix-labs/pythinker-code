from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# Platform builders that create-or-update the GitHub Release on the tag push.
BUILDER_WORKFLOWS = (
    "windows-installer.yml",
    "linux-installer.yml",
    "release-pythinker-cli.yml",
)


def test_builders_create_release_as_prerelease() -> None:
    """Each builder must mark the Release prerelease.

    /releases/latest is date-based and ignores make_latest, so prerelease is
    the only flag that keeps an in-progress release (whichever builder wins the
    create race) out of the endpoint that install scripts and the in-app
    updater resolve. promote-release.yml clears it once every asset is present.
    """
    for name in BUILDER_WORKFLOWS:
        workflow = (WORKFLOWS / name).read_text()
        assert 'prerelease: "true"' in workflow, f"{name} must mark the release prerelease"


def test_release_is_promoted_only_after_update_assets_are_ready() -> None:
    promote_workflow = (WORKFLOWS / "promote-release.yml").read_text()

    # Runs on the tag push (not `release: published`, which a GITHUB_TOKEN
    # release never fires) so promotion always happens.
    assert "tags:" in promote_workflow

    # Promotion clears prerelease AND marks latest, and only after the wait.
    assert "-F prerelease=false" in promote_workflow
    assert "-f make_latest=true" in promote_workflow
    assert promote_workflow.index("Wait for all release assets") < promote_workflow.index(
        "-F prerelease=false"
    )


def test_install_scripts_gate_on_asset_readiness() -> None:
    """The bootstrap installers must not 404 on a release caught mid-publish.

    install.ps1 resolves the newest release that actually carries the Windows
    installer + its .sha256 (skipping draft/prerelease), and install-native.sh
    waits for this version's archive + checksum before downloading.
    """
    ps1 = (ROOT / "scripts" / "install.ps1").read_text()
    assert "releases?per_page=" in ps1, "install.ps1 must scan releases, not trust /releases/latest"
    assert "$release.prerelease" in ps1
    assert '"$exe.sha256"' in ps1

    sh = (ROOT / "scripts" / "install-native.sh").read_text()
    assert "release_has_assets" in sh
    assert "${tarball}.sha256" in sh

    # The three served copies must match their canonical source byte-for-byte.
    assert (ROOT / "docs" / "public" / "install.ps1").read_text() == ps1
    assert (ROOT / "web" / "public" / "install.ps1").read_text() == ps1
    assert (ROOT / "docs" / "public" / "install.sh").read_text() == sh
    assert (ROOT / "web" / "public" / "install.sh").read_text() == sh


def test_release_asset_wait_covers_all_updater_channels() -> None:
    promote_workflow = (WORKFLOWS / "promote-release.yml").read_text()

    for expected_asset_fragment in (
        "PythinkerSetup-",
        "_amd64.deb",
        "_arm64.deb",
        ".x86_64.rpm",
        ".aarch64.rpm",
        "x86_64-unknown-linux-gnu.tar.gz",
        "aarch64-unknown-linux-gnu.tar.gz",
        "aarch64-apple-darwin.tar.gz",
        "x86_64-apple-darwin.tar.gz",
    ):
        assert expected_asset_fragment in promote_workflow
