from pythinker_host import LocalHost, current_host
from pythinker_host.path import HostPath


def test_host_public_imports() -> None:
    assert LocalHost is not None
    assert current_host is not None
    assert HostPath is not None
