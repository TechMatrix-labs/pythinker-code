import asyncio
from pathlib import Path

from pythinker_host.path import HostPath

from pythinker_code.app import PythinkerCLI, enable_logging
from pythinker_code.session import Session


async def main():
    enable_logging()
    session = await Session.create(HostPath.cwd())
    myagent = Path(__file__).parent / "myagent.yaml"
    instance = await PythinkerCLI.create(session, agent_file=myagent)
    await instance.run_print(
        input_format="text",
        output_format="text",
        command="What tools do you have?",
    )


if __name__ == "__main__":
    asyncio.run(main())
