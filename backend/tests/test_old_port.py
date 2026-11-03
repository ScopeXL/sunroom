"""The image answers on its old port too (ADR 0045), so compose files and proxies from before 7867
keep working; and ``boot.reexec`` needs those sockets closed on exec, or the new process can't bind
its own port."""

from __future__ import annotations

import socket
from collections.abc import Iterator

import pytest

from sunroom import cli
from sunroom.core.config import load_settings

HOST = "127.0.0.1"


@pytest.fixture
def two_ports() -> Iterator[tuple[int, int]]:
    """Two ports the system says are free, let go of again."""
    with socket.socket() as first, socket.socket() as second:
        first.bind((HOST, 0))
        second.bind((HOST, 0))
        ports = first.getsockname()[1], second.getsockname()[1]
    yield ports


@pytest.mark.enable_socket
def test_the_image_listens_on_both_ports_and_closes_them_on_exec(
    two_ports: tuple[int, int],
) -> None:
    port, old = two_ports
    settings = load_settings({"PORT": str(port), "SUNROOM_OLD_PORT": str(old)})

    sockets = cli._both_ports(HOST, settings)  # pyright: ignore[reportPrivateUsage]

    assert sockets is not None
    try:
        assert [sock.getsockname()[1] for sock in sockets] == [port, old]
        assert not any(sock.get_inheritable() for sock in sockets)
    finally:
        for sock in sockets:
            sock.close()


def test_with_one_port_uvicorn_binds_it_itself() -> None:
    both = cli._both_ports  # pyright: ignore[reportPrivateUsage]
    assert both(HOST, load_settings({"PORT": "7867"})) is None  # away from the image
    same = load_settings({"PORT": "8000", "SUNROOM_OLD_PORT": "8000"})
    assert both(HOST, same) is None  # a household that set PORT to the old one


@pytest.mark.enable_socket
def test_a_taken_port_stops_the_start(two_ports: tuple[int, int]) -> None:
    port, old = two_ports
    settings = load_settings({"PORT": str(port), "SUNROOM_OLD_PORT": str(old)})
    with socket.socket() as taken:
        taken.bind((HOST, old))
        taken.listen()
        with pytest.raises(SystemExit) as stopped:
            cli._both_ports(HOST, settings)  # pyright: ignore[reportPrivateUsage]
    assert stopped.value.code == 1
