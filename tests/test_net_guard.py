"""The SSRF guard: public addresses only, pinned, redirect hops checked, answers size-capped."""

import gzip
import socket
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from web.core import net_guard
from web.providers import openrouter

PUBLIC = "93.184.216.34"
Handler = Callable[[httpx.Request], httpx.Response]


def _resolves(monkeypatch: pytest.MonkeyPatch, table: dict[str, list[str]]) -> list[str]:
    """Make names resolve as `table` says (each lookup recorded); anything else doesn't resolve."""
    asked: list[str] = []

    def getaddrinfo(
        host: str, port: object, *_a: object, **_k: object
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        asked.append(host)
        if host not in table:
            raise socket.gaierror
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in table[host]]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return asked


def _client(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestAddresses:
    """Which URLs are refused before anything is sent."""

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",
            "10.0.0.5",
            "192.168.1.1",
            "172.16.0.9",
            "169.254.169.254",  # the cloud metadata address
            "100.64.0.1",  # shared address space: Tailscale, carrier NAT
            "192.0.2.1",  # documentation range
            "::1",
            "::",
            "fe80::1",
            "fd00::1",
            "::ffff:127.0.0.1",  # an IPv4 address wearing an IPv6 one
        ],
    )
    def test_non_public_addresses_are_refused(self, monkeypatch: pytest.MonkeyPatch, ip: str) -> None:
        """Loopback, the LAN, and the cloud metadata address."""
        _resolves(monkeypatch, {"evil.example": [ip]})
        with pytest.raises(net_guard.NonPublicAddressError):
            net_guard.public_address("https://evil.example/x.png")

    def test_one_private_answer_is_enough_to_refuse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A name that resolves to a public address and a private one is refused."""
        _resolves(monkeypatch, {"mixed.example": [PUBLIC, "10.0.0.1"]})
        with pytest.raises(net_guard.NonPublicAddressError):
            net_guard.public_address("https://mixed.example/")

    @pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x.example/a", "gopher://x/"])
    def test_only_http_and_https(self, url: str) -> None:
        """Other schemes never reach a connection."""
        with pytest.raises(net_guard.UnsupportedSchemeError):
            net_guard.public_address(url)

    def test_a_name_that_does_not_resolve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Refused, not left to fail later."""
        _resolves(monkeypatch, {})
        with pytest.raises(net_guard.UnresolvableHostError):
            net_guard.public_address("https://nowhere.example/")


class TestPinning:
    """The address that was checked is the address connected to."""

    def test_the_request_goes_to_the_checked_ip_under_the_real_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """IP in the URL; the name as Host and for TLS; resolved once."""
        asked = _resolves(monkeypatch, {"cdn.example": [PUBLIC]})
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, content=b"png")

        r = net_guard.get_public(_client(handler), "https://cdn.example/a/b.png?x=1", timeout=5)
        assert r.content == b"png"
        (request,) = seen
        assert request.url.host == PUBLIC
        assert request.url.path == "/a/b.png"
        assert request.headers["host"] == "cdn.example"
        assert request.extensions["sni_hostname"] == "cdn.example"
        assert asked == ["cdn.example"]

    def test_a_name_that_changes_its_answer_cannot_be_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DNS rebinding: the first answer is public, a second lookup would be private. Only the first is used."""
        asked = _resolves(monkeypatch, {"rebind.example": [PUBLIC]})  # a second lookup is what `asked` would show
        connected: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            connected.append(request.url.host)
            return httpx.Response(200, content=b"ok")

        net_guard.get_public(_client(handler), "https://rebind.example/", timeout=5)
        assert connected == [PUBLIC]
        assert asked == ["rebind.example"]

    def test_a_port_is_kept_in_host_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-default port stays on the Host header."""
        _resolves(monkeypatch, {"cdn.example": [PUBLIC]})
        hosts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            hosts.append(request.headers["host"])
            return httpx.Response(200)

        net_guard.get_public(_client(handler), "https://cdn.example:8443/x", timeout=5)
        assert hosts == ["cdn.example:8443"]


class TestRedirects:
    """Every hop is checked, not just the first."""

    def test_a_redirect_to_a_private_address_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A public URL that bounces to the metadata service."""
        _resolves(monkeypatch, {"cdn.example": [PUBLIC], "meta.example": ["169.254.169.254"]})

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "https://meta.example/latest"})

        with pytest.raises(net_guard.NonPublicAddressError):
            net_guard.get_public(_client(handler), "https://cdn.example/a", timeout=5)

    def test_a_relative_redirect_is_followed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Resolved against the URL it came from, then checked like any other."""
        _resolves(monkeypatch, {"cdn.example": [PUBLIC], "other.example": ["93.184.216.35"]})
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            if request.url.path == "/a":
                return httpx.Response(301, headers={"location": "/b"})
            return httpx.Response(200, content=b"done")

        r = net_guard.get_public(_client(handler), "https://cdn.example/a", timeout=5)
        assert (r.content, paths) == (b"done", ["/a", "/b"])

    def test_a_loop_stops(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Too many hops is an error, not a hang."""
        asked = _resolves(monkeypatch, {"cdn.example": [PUBLIC]})

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "https://cdn.example/again"})

        with pytest.raises(net_guard.TooManyRedirectsError):
            net_guard.get_public(_client(handler), "https://cdn.example/a", timeout=5)
        assert len(asked) == net_guard.DEFAULT_REDIRECTS + 1


class TestSizeCap:
    """An answer bigger than the cap is refused as it arrives."""

    def test_a_declared_size_over_the_cap_is_refused_before_reading(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Content-Length alone is enough."""
        _resolves(monkeypatch, {"cdn.example": [PUBLIC]})

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-length": "999999"}, content=b"x")

        with pytest.raises(net_guard.ResponseTooLargeError):
            net_guard.get_public(_client(handler), "https://cdn.example/", timeout=5, max_bytes=1000)

    def test_a_body_that_outgrows_what_it_declared_is_cut_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No Content-Length, or a false one: counted as it is read."""
        _resolves(monkeypatch, {"cdn.example": [PUBLIC]})

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * 5000)

        with pytest.raises(net_guard.ResponseTooLargeError):
            net_guard.get_public(_client(handler), "https://cdn.example/", timeout=5, max_bytes=1000)

    def test_a_gzipped_answer_comes_back_whole(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The returned response doesn't try to decode what is already decoded."""
        _resolves(monkeypatch, {"cdn.example": [PUBLIC]})

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-encoding": "gzip"}, content=gzip.compress(b"hello"))

        r = net_guard.get_public(_client(handler), "https://cdn.example/", timeout=5)
        assert r.content == b"hello"
        assert r.text == "hello"


class TestDownload:
    """Files go through a .part file and leave nothing behind on failure."""

    def test_writes_the_file(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Success: the file, no .part."""
        _resolves(monkeypatch, {"cdn.example": [PUBLIC]})
        dest = tmp_path / "out" / "v.mp4"
        net_guard.download_public(
            _client(lambda _r: httpx.Response(200, content=b"video")), "https://cdn.example/v", dest, timeout=5
        )
        assert dest.read_bytes() == b"video"
        assert not dest.with_suffix(".mp4.part").exists()

    def test_too_large_leaves_nothing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Over the cap mid-stream: no file and no .part."""
        _resolves(monkeypatch, {"cdn.example": [PUBLIC]})
        folder = tmp_path / "downloads"
        dest = folder / "v.mp4"
        with pytest.raises(net_guard.ResponseTooLargeError):
            net_guard.download_public(
                _client(lambda _r: httpx.Response(200, content=b"x" * 5000)),
                "https://cdn.example/v",
                dest,
                timeout=5,
                max_bytes=1000,
            )
        assert list(folder.iterdir()) == []

    def test_an_error_status_leaves_nothing(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """A 404 is an HTTP error, and nothing is written."""
        _resolves(monkeypatch, {"cdn.example": [PUBLIC]})
        folder = tmp_path / "downloads"
        dest = folder / "v.mp4"
        with pytest.raises(httpx.HTTPStatusError):
            net_guard.download_public(_client(lambda _r: httpx.Response(404)), "https://cdn.example/v", dest, timeout=5)
        assert list(folder.iterdir()) == []

    def test_a_private_address_never_connects(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Refused before any request is made."""
        _resolves(monkeypatch, {"evil.example": ["127.0.0.1"]})
        sent: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            return httpx.Response(200)

        with pytest.raises(net_guard.NonPublicAddressError):
            net_guard.download_public(_client(handler), "https://evil.example/v", tmp_path / "v", timeout=5)
        assert sent == []


class TestOpenRouterVideo:
    """OpenRouter's video download: the file itself, or a redirect that must lead somewhere public."""

    @pytest.fixture(autouse=True)
    def _key(self, provider_keys: dict[str, str | None]) -> None:
        provider_keys["openrouter"] = "sk-test"

    def _use(self, monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
        monkeypatch.setattr(openrouter, "http_client", _client(handler))

    def test_the_file_itself(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Written, with the key sent to OpenRouter."""
        keys: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            keys.append(request.headers.get("authorization") or "")
            return httpx.Response(200, content=b"mp4")

        self._use(monkeypatch, handler)
        dest = tmp_path / "v.mp4"
        openrouter.download_video("job1", dest)
        assert dest.read_bytes() == b"mp4"
        assert keys == ["Bearer sk-test"]

    def test_a_redirect_to_storage_is_fetched_without_the_key(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The storage address goes through the guard, with none of OpenRouter's credentials."""
        self._use(
            monkeypatch, lambda _r: httpx.Response(302, headers={"location": "https://store.example/v.mp4?sig=1"})
        )
        _resolves(monkeypatch, {"store.example": [PUBLIC]})
        seen: list[httpx.Request] = []

        def storage(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, content=b"stored")

        monkeypatch.setattr(net_guard, "public_http", _client(storage))
        dest = tmp_path / "v.mp4"
        openrouter.download_video("job1", dest)
        assert dest.read_bytes() == b"stored"
        assert "authorization" not in seen[0].headers

    def test_a_redirect_to_a_private_address_is_refused(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Nothing is written, and the reason is plain."""
        self._use(monkeypatch, lambda _r: httpx.Response(302, headers={"location": "https://internal.example/v"}))
        _resolves(monkeypatch, {"internal.example": ["10.1.2.3"]})
        dest = tmp_path / "v.mp4"
        with pytest.raises(openrouter.UnsafeVideoUrlError):
            openrouter.download_video("job1", dest)
        assert not dest.exists()
