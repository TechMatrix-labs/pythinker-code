import asyncio

from pythinker_host.path import HostPath
from rich import print

from pythinker_code.app import PythinkerCLI, enable_logging
from pythinker_code.session import Session


async def main():
    enable_logging()
    session = await Session.create(HostPath.cwd())
    instance = await PythinkerCLI.create(session)
    user_input = "Hello!"

    async for msg in instance.run(
        user_input=user_input,
        cancel_event=asyncio.Event(),
        merge_wire_messages=True,
    ):
        print(msg)

    # print the last assistant message
    print(instance.soul.context.history[-1])


if __name__ == "__main__":
    asyncio.run(main())
