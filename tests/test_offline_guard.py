"""The suite is offline: an unmocked lookup of a real hostname fails fast (conftest._offline)."""

import socket

import pytest


def test_real_hostname_lookup_is_refused():
    with pytest.raises(socket.gaierror, match="offline test suite"):
        socket.getaddrinfo("pypi.org", 443)


def test_loopback_lookup_is_allowed():
    assert socket.getaddrinfo("localhost", 80)
