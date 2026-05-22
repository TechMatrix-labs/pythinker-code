import asyncio
import os
from pathlib import Path
from typing import override

from pydantic import BaseModel, Field, SecretStr
from pythinker_core.tooling import CallableTool2, ToolError, ToolOk, Toolset
from pythinker_core.tooling.simple import SimpleToolset
from pythinker_host.path import HostPath

from pythinker_code.auth.oauth import OAuthManager
from pythinker_code.config import LLMModel, LLMProvider, get_default_config
from pythinker_code.llm import LLM, create_llm
from pythinker_code.session import Session
from pythinker_code.soul.agent import Agent, Runtime
from pythinker_code.soul.context import Context
from pythinker_code.soul.pythinkersoul import PythinkerSoul
from pythinker_code.ui.shell import Shell
from pythinker_code.wire.types import ContentPart, ToolReturnValue


class HapythinkerSoul(PythinkerSoul):
    @staticmethod
    async def create(
        llm: LLM | None,
        system_prompt: str,
        toolset: Toolset,
        session: Session | None = None,
        work_dir: Path | None = None,
    ) -> "HapythinkerSoul":
        config = get_default_config()
        host_work_dir = HostPath.unsafe_from_local_path(work_dir) if work_dir else HostPath.cwd()
        session = session or await Session.create(host_work_dir)
        runtime = await Runtime.create(
            config=config,
            oauth=OAuthManager(config),
            llm=llm,
            session=session,
            yolo=True,
        )
        agent = Agent(
            name="HapythinkerAgent",
            system_prompt=system_prompt,
            toolset=toolset,
            runtime=runtime,
        )
        context = Context(session.context_file)
        return HapythinkerSoul(agent, context=context)

    @property
    @override
    def name(self) -> str:
        return "Hapythinker"

    @override
    async def run(
        self,
        user_input: str | list[ContentPart],
        *,
        skip_user_prompt_hook: bool = False,
    ) -> None:
        if not self._context.history:
            await self._context.restore()
        await super().run(user_input, skip_user_prompt_hook=skip_user_prompt_hook)


class MyBashParams(BaseModel):
    command: str = Field(description="The bash command to execute.")


class MyBashTool(CallableTool2):
    name: str = "MyBashTool"
    description: str = "A tool to execute bash commands."
    params: type[MyBashParams] = MyBashParams

    async def __call__(self, params: MyBashParams) -> ToolReturnValue:
        import shlex
        import subprocess

        try:
            argv = shlex.split(params.command)
        except ValueError as exc:
            return ToolError(output="", message=f"Invalid command: {exc}", brief="Invalid command")
        if not argv:
            return ToolError(output="", message="Command is empty", brief="Invalid command")

        result = subprocess.run(argv, capture_output=True, text=True)
        if result.returncode != 0:
            return ToolError(
                output=result.stdout,
                message=f"Command failed with error: {result.stderr}",
                brief="Bash command failed",
            )
        return ToolOk(output=result.stdout)


async def main():
    toolset = SimpleToolset()
    toolset += MyBashTool()

    soul = await HapythinkerSoul.create(
        llm=create_llm(
            LLMProvider(
                type="pythinker",
                base_url=os.getenv("PYTHINKER_BASE_URL") or "https://api.pythinker-ai.ai/v1",
                api_key=SecretStr(os.getenv("PYTHINKER_API_KEY") or ""),
            ),
            LLMModel(
                provider="pythinker",
                model="pythinker-ai",
                max_context_size=250_000,
            ),
        ),
        system_prompt="You are Hapythinker, an AI assistant that helps users with various tasks.",
        toolset=toolset,
    )
    ui = Shell(soul)
    await ui.run()


if __name__ == "__main__":
    asyncio.run(main())
