from contextvars import ContextVar

from pythinker_host import Host
from pythinker_host.local import local_host

current_host = ContextVar[Host]("current_host", default=local_host)
