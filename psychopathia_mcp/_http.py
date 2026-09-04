"""Bounded Streamable HTTP transport. Stdio remains the default transport.

The public-facing proxy still owns TLS, authentication decisions, connection
limits, and rate limiting. These application guards remain active if the proxy
is misconfigured or the process is reached directly.

Environment:
  MCP_HTTP_HOST                     bind address, default 127.0.0.1
  MCP_HTTP_PORT                     port, default 8080
  MCP_HTTP_ALLOWED_HOSTS            comma-separated exact Host values
  MCP_HTTP_ALLOWED_ORIGINS          comma-separated exact browser origins
  MCP_HTTP_MAX_BODY_BYTES           default 1048576
  MCP_HTTP_MAX_CONCURRENCY          default 32
  MCP_HTTP_REQUEST_TIMEOUT_SECONDS  default 60
  MCP_HTTP_ACQUIRE_TIMEOUT_SECONDS  default 0.1
"""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import os
import re
from typing import TYPE_CHECKING, Any

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

if TYPE_CHECKING:
    from mcp.server import Server


DEFAULT_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "::1")
LOOPBACK_BINDS = {"127.0.0.1", "localhost", "::1"}
DNS_HOST_RE = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)
BRACKETED_IPV6_RE = re.compile(r"\[([^\]]+)\](?::([0-9]{1,5}))?\Z")


def _header(scope: Scope, name: bytes) -> str | None:
    values = [
        value.decode("latin-1")
        for key, value in scope.get("headers", [])
        if key.lower() == name
    ]
    if len(values) > 1:
        raise ValueError(f"duplicate {name.decode('ascii')} header")
    return values[0] if values else None


def _normalise_host(value: str) -> str:
    """Parse a Host value without accepting paths, userinfo, or malformed ports."""
    if value != value.strip() or not value or any(ord(char) < 0x21 or ord(char) > 0x7E for char in value):
        raise ValueError("Host must be non-empty printable ASCII without surrounding whitespace")
    value = value.lower()
    if any(char in value for char in "/\\?#@"):
        raise ValueError("Host contains a forbidden delimiter")

    bracketed = BRACKETED_IPV6_RE.fullmatch(value)
    if bracketed:
        address, port = bracketed.groups()
        if port is not None and not 1 <= int(port) <= 65535:
            raise ValueError("Host port is outside the valid range")
        return ipaddress.IPv6Address(address).compressed
    if value.startswith("[") or "]" in value:
        raise ValueError("Host contains malformed IPv6 brackets")

    try:
        return ipaddress.ip_address(value).compressed
    except ValueError:
        pass

    host = value
    if ":" in value:
        if value.count(":") != 1:
            raise ValueError("Unbracketed Host contains multiple colons")
        host, port = value.rsplit(":", 1)
        if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
            raise ValueError("Host port is invalid")

    try:
        return ipaddress.ip_address(host).compressed
    except ValueError:
        if DNS_HOST_RE.fullmatch(host) is None:
            raise ValueError("Host name is invalid") from None
        return host


def _json_error(status: int, code: int, message: str, *, allow: str | None = None) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if allow:
        headers["Allow"] = allow
    return JSONResponse(
        {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": None},
        status_code=status,
        headers=headers,
    )


class HTTPGuards:
    """ASGI wrapper enforcing host, origin, size, concurrency, and time limits."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS,
        allowed_origins: tuple[str, ...] = (),
        max_body_bytes: int = 1024 * 1024,
        max_concurrency: int = 32,
        request_timeout_seconds: float = 60.0,
        acquire_timeout_seconds: float = 0.1,
    ) -> None:
        if not allowed_hosts:
            raise ValueError("At least one allowed Host is required")
        if max_body_bytes < 1024 or max_concurrency < 1:
            raise ValueError("HTTP limits must be positive and bounded")
        if not 0 < request_timeout_seconds <= 300 or not 0 < acquire_timeout_seconds <= 5:
            raise ValueError("HTTP timeouts are outside the supported range")
        self.app = app
        self.allowed_hosts = {_normalise_host(host) for host in allowed_hosts}
        self.allowed_origins = {origin.rstrip("/") for origin in allowed_origins}
        self.max_body_bytes = max_body_bytes
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.request_timeout_seconds = request_timeout_seconds
        self.acquire_timeout_seconds = acquire_timeout_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        try:
            host = _header(scope, b"host")
            normalised_host = _normalise_host(host) if host else None
        except ValueError:
            normalised_host = None
        if normalised_host not in self.allowed_hosts:
            await _json_error(400, -32600, "Unrecognised Host")(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        is_mcp = path == "/mcp" or path.startswith("/mcp/")
        if not is_mcp:
            await self.app(scope, receive, send)
            return

        if scope.get("method") != "POST":
            await _json_error(405, -32600, "Only POST is supported", allow="POST")(scope, receive, send)
            return

        try:
            origin = _header(scope, b"origin")
            content_length = _header(scope, b"content-length")
        except ValueError:
            await _json_error(400, -32600, "Duplicate security-sensitive header")(scope, receive, send)
            return
        if origin is not None and origin.rstrip("/") not in self.allowed_origins:
            await _json_error(403, -32600, "Origin is not allowed")(scope, receive, send)
            return

        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                await _json_error(400, -32600, "Invalid Content-Length")(scope, receive, send)
                return
            if declared < 0 or declared > self.max_body_bytes:
                await _json_error(413, -32600, "Request body is too large")(scope, receive, send)
                return

        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=self.acquire_timeout_seconds)
        # asyncio.TimeoutError is only an alias of TimeoutError from 3.11; the
        # package still supports 3.10, where they are distinct classes.
        except (TimeoutError, asyncio.TimeoutError):
            await _json_error(503, -32000, "Server is busy")(scope, receive, send)
            return

        response_started = False
        response_abandoned = False

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if response_abandoned:
                return
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        forward_task = asyncio.create_task(
            self._read_and_forward(scope, receive, guarded_send)
        )
        release_deferred = False

        def release_when_finished(task: asyncio.Task[None]) -> None:
            # Retrieve any late exception so an abandoned timed-out request does
            # not produce an unhandled-task warning. Its capacity remains held
            # until the synchronous worker actually exits.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                task.result()
            self.semaphore.release()

        def defer_release() -> None:
            nonlocal release_deferred
            if not release_deferred:
                release_deferred = True
                forward_task.add_done_callback(release_when_finished)

        try:
            await asyncio.wait_for(
                asyncio.shield(forward_task),
                timeout=self.request_timeout_seconds,
            )
        except (TimeoutError, asyncio.TimeoutError):
            response_abandoned = True
            defer_release()
            if not response_started:
                await _json_error(504, -32000, "Request timed out")(scope, receive, send)
        except asyncio.CancelledError:
            response_abandoned = True
            defer_release()
            raise
        finally:
            if not release_deferred:
                self.semaphore.release()

    async def _read_and_forward(self, scope: Scope, receive: Receive, send: Send) -> None:
        body = bytearray()
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                return
            if message.get("type") != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > self.max_body_bytes:
                await _json_error(413, -32600, "Request body is too large")(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)


def _csv_env(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _float_env(name: str, default: float, *, minimum: float, maximum: float) -> float:
    value = float(os.environ.get(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def build_http_app(server: "Server") -> ASGIApp:
    """Wrap an MCP Server in a guarded, stateless Streamable HTTP app."""
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    manager = StreamableHTTPSessionManager(
        app=server,
        event_store=None,
        json_response=True,
        stateless=True,
    )

    async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
        await manager.handle_request(scope, receive, send)

    async def health(_request: Any) -> JSONResponse:
        return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        async with manager.run():
            yield

    app = Starlette(
        debug=False,
        routes=[Route("/health", health, methods=["GET"]), Mount("/mcp", app=handle_mcp)],
        lifespan=lifespan,
    )
    return HTTPGuards(
        app,
        allowed_hosts=_csv_env("MCP_HTTP_ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS),
        allowed_origins=_csv_env("MCP_HTTP_ALLOWED_ORIGINS"),
        max_body_bytes=_int_env("MCP_HTTP_MAX_BODY_BYTES", 1024 * 1024, minimum=1024, maximum=16 * 1024 * 1024),
        max_concurrency=_int_env("MCP_HTTP_MAX_CONCURRENCY", 32, minimum=1, maximum=1024),
        request_timeout_seconds=_float_env("MCP_HTTP_REQUEST_TIMEOUT_SECONDS", 60.0, minimum=1.0, maximum=300.0),
        acquire_timeout_seconds=_float_env("MCP_HTTP_ACQUIRE_TIMEOUT_SECONDS", 0.1, minimum=0.01, maximum=5.0),
    )


def run_http(server: "Server") -> None:
    """Serve over Streamable HTTP. Import uvicorn only for HTTP installs."""
    import uvicorn

    host = os.environ.get("MCP_HTTP_HOST", "127.0.0.1")
    if host not in LOOPBACK_BINDS and "MCP_HTTP_ALLOWED_HOSTS" not in os.environ:
        raise SystemExit("MCP_HTTP_ALLOWED_HOSTS is required for a non-loopback bind")
    port = _int_env("MCP_HTTP_PORT", 8080, minimum=1, maximum=65535)
    uvicorn.run(
        build_http_app(server),
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        proxy_headers=False,
        server_header=False,
        date_header=False,
        timeout_keep_alive=5,
    )
