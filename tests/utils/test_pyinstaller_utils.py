from __future__ import annotations

import platform
import sys
from pathlib import Path

from inline_snapshot import snapshot


def test_pyinstaller_datas():
    from pythinker_code.utils.pyinstaller import datas

    project_root = Path(__file__).parent.parent.parent
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    site_packages = f".venv/lib/python{python_version}/site-packages"
    rg_binary = "rg.exe" if platform.system() == "Windows" else "rg"
    has_rg_binary = (project_root / "src/pythinker_code/deps/bin" / rg_binary).exists()
    datas = [
        (
            Path(path)
            .relative_to(project_root)
            .as_posix()
            .replace(f".venv/lib64/python{python_version}/site-packages", site_packages)
            .replace(".venv/Lib/site-packages", site_packages),
            Path(dst).as_posix(),
        )
        for path, dst in datas
    ]

    datas = [(p, d) for p, d in datas if "web/static" not in d and "vis/static" not in d]

    expected_datas = [
        (
            f"{site_packages}/dateparser/data/dateparser_tz_cache.pkl",
            "dateparser/data",
        ),
        (
            f"{site_packages}/fastmcp/../fastmcp-2.12.5.dist-info/INSTALLER",
            "fastmcp/../fastmcp-2.12.5.dist-info",
        ),
        (
            f"{site_packages}/fastmcp/../fastmcp-2.12.5.dist-info/METADATA",
            "fastmcp/../fastmcp-2.12.5.dist-info",
        ),
        (
            f"{site_packages}/fastmcp/../fastmcp-2.12.5.dist-info/RECORD",
            "fastmcp/../fastmcp-2.12.5.dist-info",
        ),
        (
            f"{site_packages}/fastmcp/../fastmcp-2.12.5.dist-info/REQUESTED",
            "fastmcp/../fastmcp-2.12.5.dist-info",
        ),
        (
            f"{site_packages}/fastmcp/../fastmcp-2.12.5.dist-info/WHEEL",
            "fastmcp/../fastmcp-2.12.5.dist-info",
        ),
        (
            f"{site_packages}/fastmcp/../fastmcp-2.12.5.dist-info/entry_points.txt",
            "fastmcp/../fastmcp-2.12.5.dist-info",
        ),
        (
            f"{site_packages}/fastmcp/../fastmcp-2.12.5.dist-info/licenses/LICENSE",
            "fastmcp/../fastmcp-2.12.5.dist-info/licenses",
        ),
        (
            "src/pythinker_code/CHANGELOG.md",
            "pythinker_code",
        ),
        ("src/pythinker_code/agents/default/agent.yaml", "pythinker_code/agents/default"),
        ("src/pythinker_code/agents/default/coder.yaml", "pythinker_code/agents/default"),
        ("src/pythinker_code/agents/default/explore.yaml", "pythinker_code/agents/default"),
        ("src/pythinker_code/agents/default/implementer.yaml", "pythinker_code/agents/default"),
        ("src/pythinker_code/agents/default/plan.yaml", "pythinker_code/agents/default"),
        ("src/pythinker_code/agents/default/review.yaml", "pythinker_code/agents/default"),
        ("src/pythinker_code/agents/default/system.md", "pythinker_code/agents/default"),
        ("src/pythinker_code/agents/default/verifier.yaml", "pythinker_code/agents/default"),
        ("src/pythinker_code/agents/okabe/agent.yaml", "pythinker_code/agents/okabe"),
        ("src/pythinker_code/prompts/compact.md", "pythinker_code/prompts"),
        ("src/pythinker_code/prompts/init.md", "pythinker_code/prompts"),
        (
            "src/pythinker_code/skills/pythinker-code-help/SKILL.md",
            "pythinker_code/skills/pythinker-code-help",
        ),
        (
            "src/pythinker_code/skills/skill-creator/SKILL.md",
            "pythinker_code/skills/skill-creator",
        ),
        ("src/pythinker_code/tools/agent/description.md", "pythinker_code/tools/agent"),
        ("src/pythinker_code/tools/ask_user/description.md", "pythinker_code/tools/ask_user"),
        (
            "src/pythinker_code/tools/dmail/dmail.md",
            "pythinker_code/tools/dmail",
        ),
        ("src/pythinker_code/tools/background/list.md", "pythinker_code/tools/background"),
        ("src/pythinker_code/tools/background/output.md", "pythinker_code/tools/background"),
        ("src/pythinker_code/tools/background/stop.md", "pythinker_code/tools/background"),
        (
            "src/pythinker_code/tools/file/glob.md",
            "pythinker_code/tools/file",
        ),
        (
            "src/pythinker_code/tools/file/grep.md",
            "pythinker_code/tools/file",
        ),
        (
            "src/pythinker_code/tools/file/read.md",
            "pythinker_code/tools/file",
        ),
        (
            "src/pythinker_code/tools/file/read_media.md",
            "pythinker_code/tools/file",
        ),
        (
            "src/pythinker_code/tools/file/replace.md",
            "pythinker_code/tools/file",
        ),
        (
            "src/pythinker_code/tools/file/write.md",
            "pythinker_code/tools/file",
        ),
        ("src/pythinker_code/tools/plan/description.md", "pythinker_code/tools/plan"),
        ("src/pythinker_code/tools/plan/enter_description.md", "pythinker_code/tools/plan"),
        ("src/pythinker_code/tools/shell/bash.md", "pythinker_code/tools/shell"),
        ("src/pythinker_code/tools/shell/powershell.md", "pythinker_code/tools/shell"),
        (
            "src/pythinker_code/tools/think/think.md",
            "pythinker_code/tools/think",
        ),
        (
            "src/pythinker_code/tools/todo/set_todo_list.md",
            "pythinker_code/tools/todo",
        ),
        (
            "src/pythinker_code/tools/web/fetch.md",
            "pythinker_code/tools/web",
        ),
        (
            "src/pythinker_code/tools/web/search.md",
            "pythinker_code/tools/web",
        ),
    ]
    if has_rg_binary:
        expected_datas.append(
            (f"src/pythinker_code/deps/bin/{rg_binary}", "pythinker_code/deps/bin")
        )

    assert sorted(datas) == sorted(expected_datas)


def test_pyinstaller_hiddenimports():
    from pythinker_code.utils.pyinstaller import hiddenimports

    assert sorted(hiddenimports) == snapshot(
        [
            "pythinker_code.cli._lazy_group",
            "pythinker_code.cli.export",
            "pythinker_code.cli.info",
            "pythinker_code.cli.mcp",
            "pythinker_code.cli.plugin",
            "pythinker_code.cli.update",
            "pythinker_code.cli.vis",
            "pythinker_code.cli.web",
            "pythinker_code.tools",
            "pythinker_code.tools.agent",
            "pythinker_code.tools.ask_user",
            "pythinker_code.tools.background",
            "pythinker_code.tools.display",
            "pythinker_code.tools.dmail",
            "pythinker_code.tools.file",
            "pythinker_code.tools.file.glob",
            "pythinker_code.tools.file.grep_local",
            "pythinker_code.tools.file.plan_mode",
            "pythinker_code.tools.file.read",
            "pythinker_code.tools.file.read_media",
            "pythinker_code.tools.file.replace",
            "pythinker_code.tools.file.utils",
            "pythinker_code.tools.file.write",
            "pythinker_code.tools.plan",
            "pythinker_code.tools.plan.enter",
            "pythinker_code.tools.plan.handoff",
            "pythinker_code.tools.plan.heroes",
            "pythinker_code.tools.shell",
            "pythinker_code.tools.test",
            "pythinker_code.tools.think",
            "pythinker_code.tools.todo",
            "pythinker_code.tools.utils",
            "pythinker_code.tools.web",
            "pythinker_code.tools.web.fetch",
            "pythinker_code.tools.web.search",
            "setproctitle",
        ]
    )


def test_pyinstaller_hiddenimports_include_lazy_cli_subcommands():
    from pythinker_code.cli._lazy_group import LazySubcommandGroup
    from pythinker_code.utils.pyinstaller import hiddenimports

    expected_hiddenimports = {
        module_name
        for module_name, _attribute_name, _help_text in LazySubcommandGroup.lazy_subcommands.values()
    }

    assert expected_hiddenimports <= set(hiddenimports)
