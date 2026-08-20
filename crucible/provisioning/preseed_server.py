from __future__ import annotations

import threading

from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from pathlib import Path


DEFAULT_BIND_ADDRESS = "127.0.0.1"

# With VirtualBox's default NAT configuration,
# 10.0.2.2 represents the host from inside the guest.
DEFAULT_GUEST_HOST = "10.0.2.2"


class PreseedServerError(RuntimeError):
    """Raised when the temporary preseed server fails."""


class _PreseedRequestHandler(
    BaseHTTPRequestHandler
):
    """
    Serve exactly one file:

        /preseed.cfg

    The actual preseed path and fetch event are attached
    to the HTTP server instance by PreseedServer.
    """

    server_version = "CruciblePreseed/1.0"

    def do_GET(self) -> None:
        if self.path != "/preseed.cfg":
            self.send_error(
                404,
                "Not Found",
            )
            return

        preseed_path = getattr(
            self.server,
            "preseed_path",
            None,
        )

        fetch_event = getattr(
            self.server,
            "fetch_event",
            None,
        )

        if not isinstance(
            preseed_path,
            Path,
        ):
            self.send_error(
                500,
                "Preseed path unavailable",
            )
            return

        try:
            payload = (
                preseed_path.read_bytes()
            )

        except OSError:
            self.send_error(
                500,
                "Could not read preseed",
            )
            return

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(payload)),
        )
        self.send_header(
            "Cache-Control",
            "no-store",
        )
        self.end_headers()

        try:
            self.wfile.write(
                payload
            )

        except (
            BrokenPipeError,
            ConnectionResetError,
        ):
            return

        if isinstance(
            fetch_event,
            threading.Event,
        ):
            fetch_event.set()

    def log_message(
        self,
        format: str,
        *args: object,
    ) -> None:
        # Avoid cluttering Crucible's Forge UI with
        # the standard BaseHTTPRequestHandler log.
        return


class PreseedServer:
    """
    Temporary HTTP service used by Debian Installer.

    The server listens only on the controller's loopback
    interface. VirtualBox NAT exposes that loopback service
    inside the guest as 10.0.2.2 when
    nat-localhostreachable is enabled.
    """

    def __init__(
        self,
        preseed_path: Path,
        *,
        bind_address: str = (
            DEFAULT_BIND_ADDRESS
        ),
        port: int = 0,
        guest_host: str = (
            DEFAULT_GUEST_HOST
        ),
    ) -> None:
        self.preseed_path = (
            preseed_path
            .expanduser()
            .resolve()
        )

        self.bind_address = (
            bind_address
        )

        self.requested_port = (
            port
        )

        self.guest_host = (
            guest_host
        )

        self._httpd: (
            ThreadingHTTPServer
            | None
        ) = None

        self._thread: (
            threading.Thread
            | None
        ) = None

        self._fetch_event = (
            threading.Event()
        )

    @property
    def port(self) -> int:
        if self._httpd is None:
            raise PreseedServerError(
                "Preseed server has not "
                "been started."
            )

        return int(
            self._httpd.server_address[1]
        )

    @property
    def host_url(self) -> str:
        """
        URL usable directly from the controller.
        """

        return (
            f"http://"
            f"{self.bind_address}:"
            f"{self.port}/preseed.cfg"
        )

    @property
    def guest_url(self) -> str:
        """
        URL supplied to the Kali installer.
        """

        return (
            f"http://"
            f"{self.guest_host}:"
            f"{self.port}/preseed.cfg"
        )

    @property
    def fetched(self) -> bool:
        return (
            self._fetch_event.is_set()
        )

    def start(self) -> None:
        if self._httpd is not None:
            raise PreseedServerError(
                "Preseed server is "
                "already running."
            )

        if not (
            self.preseed_path.is_file()
        ):
            raise PreseedServerError(
                "Preseed file does not exist: "
                f"{self.preseed_path}"
            )

        try:
            httpd = ThreadingHTTPServer(
                (
                    self.bind_address,
                    self.requested_port,
                ),
                _PreseedRequestHandler,
            )

        except OSError as exc:
            raise PreseedServerError(
                "Could not start temporary "
                "preseed HTTP server: "
                f"{exc}"
            ) from exc

        # Attributes consumed by our custom handler.
        httpd.preseed_path = (
            self.preseed_path
        )

        httpd.fetch_event = (
            self._fetch_event
        )

        self._httpd = httpd

        self._thread = threading.Thread(
            target=httpd.serve_forever,
            name="crucible-preseed-http",
            daemon=True,
        )

        self._thread.start()

    def wait_for_fetch(
        self,
        *,
        timeout: float = 180.0,
    ) -> None:
        """
        Wait until the installer successfully downloads
        /preseed.cfg.
        """

        if self._httpd is None:
            raise PreseedServerError(
                "Cannot wait for preseed fetch "
                "because the server is not running."
            )

        if self._fetch_event.wait(
            timeout
        ):
            return

        raise PreseedServerError(
            "Timed out waiting for the "
            "Kali installer to fetch "
            f"{self.guest_url}"
        )

    def stop(self) -> None:
        if self._httpd is None:
            return

        httpd = self._httpd
        thread = self._thread

        self._httpd = None
        self._thread = None

        httpd.shutdown()
        httpd.server_close()

        if thread is not None:
            thread.join(
                timeout=5.0
            )

    def __enter__(
        self,
    ) -> "PreseedServer":
        self.start()
        return self

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        self.stop()
