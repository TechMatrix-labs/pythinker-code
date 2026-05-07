# Pythinker Host

Pythinker Host is the OS-abstraction layer used by Pythinker agents. It exposes a `Host` Protocol that unifies local filesystem and shell execution with remote (SSH) and ACP-backed backends, so tools written against Pythinker Host run unchanged regardless of where the agent's work happens.

## Installation

Pythinker Host requires Python 3.12 or higher.

```bash
uv add pythinker-host
```

## Usage

```python
from pythinker_host import LocalHost, set_current_host
from pythinker_host.path import HostPath

backend = LocalHost()
set_current_host(backend)

path = HostPath("/etc/hostname")
```
