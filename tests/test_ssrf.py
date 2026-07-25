import socket

import pytest

from app.security import ssrf

BLOCKED_LITERALS = [
    "http://127.0.0.1/x",
    "http://10.0.0.1/x",
    "http://172.16.0.1/x",
    "http://192.168.1.1/x",
    "http://169.254.169.254/latest/meta-data/",
    "http://169.254.170.2/v2/credentials",
    "http://100.100.100.200/latest/meta-data/",
    "http://192.0.0.192/x",
    "http://224.0.0.1/x",
    "http://0.0.0.0/x",
    "http://[::1]/x",
    "http://[fe80::1]/x",
    "http://[fd00:ec2::254]/x",
]


@pytest.mark.parametrize("url", BLOCKED_LITERALS)
def test_blocked_literal_addresses(url: str) -> None:
    with pytest.raises(ssrf.SSRFError):
        ssrf.resolve_and_validate(url)


def test_public_literal_passes() -> None:
    target = ssrf.resolve_and_validate("https://93.184.216.34/recording.mp3")
    assert target.ip == "93.184.216.34"
    assert target.port == 443


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",
        "file:///etc/passwd",
        "https://user:pass@example.com/x",
        "https:///nohost",
    ],
)
def test_bad_schemes_userinfo_and_missing_host(url: str) -> None:
    with pytest.raises(ssrf.SSRFError):
        ssrf.resolve_and_validate(url)


def test_hostname_resolving_private_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host: str, port: int, **kwargs: object) -> list[tuple]:  # type: ignore[type-arg]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.9.9.9", port))]

    monkeypatch.setattr("app.security.ssrf.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ssrf.SSRFError):
        ssrf.resolve_and_validate("https://rebinding.example/recording.mp3")


def test_hostname_with_any_private_ip_in_answers_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(host: str, port: int, **kwargs: object) -> list[tuple]:  # type: ignore[type-arg]
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
        ]

    monkeypatch.setattr("app.security.ssrf.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ssrf.SSRFError):
        ssrf.resolve_and_validate("https://halfpublic.example/x")


def test_hostname_resolving_public_pins_first_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host: str, port: int, **kwargs: object) -> list[tuple]:  # type: ignore[type-arg]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr("app.security.ssrf.socket.getaddrinfo", fake_getaddrinfo)
    target = ssrf.resolve_and_validate("https://cdn.example/recording.mp3")
    assert target.ip == "93.184.216.34"
    assert target.host == "cdn.example"


def test_unresolvable_host_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host: str, port: int, **kwargs: object) -> list[tuple]:  # type: ignore[type-arg]
        raise socket.gaierror("no such host")

    monkeypatch.setattr("app.security.ssrf.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ssrf.SSRFError):
        ssrf.resolve_and_validate("https://doesnotresolve.example/x")
