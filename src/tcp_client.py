"""TCP client for communicating with the RenderMonitor Remote Script.

Connects to the RenderMonitor running inside Ableton Live and
queries the current dialog state to detect rendering progress
and completion.
"""

import socket
import time
from dataclasses import dataclass

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9877
RECV_BUFFER = 1024


@dataclass(frozen=True)
class RenderStatus:
    """Status response from the RenderMonitor."""

    state: str  # "IDLE", "EXPORT_DIALOG", "RENDERING", or "ERROR"
    message: str  # Dialog message (empty when idle/export_dialog)


class RenderMonitorClient:
    """TCP client for the Ableton RenderMonitor Remote Script.

    Usage:
        with RenderMonitorClient() as client:
            status = client.get_status()
            print(status.state, status.message)
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self._host = host
        self._port = port
        self._socket: socket.socket | None = None

    def connect(self) -> None:
        """Establish TCP connection to the RenderMonitor.

        Raises:
            ConnectionRefusedError: If RenderMonitor is not running.
            OSError: If connection fails for other reasons.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((self._host, self._port))
        self._socket = sock

    def close(self) -> None:
        """Close the TCP connection."""
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def get_property(self, path: str) -> str:
        """Read a property from Ableton via GET command.

        Args:
            path: Dotted path like 'song.loop_start' or 'song.file_path'.

        Returns:
            The property value as a string.

        Raises:
            ConnectionError: If not connected.
            RuntimeError: If the Remote Script returned an error.
        """
        response = self._send_command(f"GET:{path}")
        if response.startswith("OK:"):
            return response[3:]
        raise RuntimeError(f"GET {path} failed: {response}")

    def set_property(self, path: str, value) -> str:
        """Set a property in Ableton via SET command.

        Args:
            path: Dotted path like 'song.loop_start'.
            value: Value to set (bool, int, or float).

        Returns:
            The confirmed value as a string.

        Raises:
            ConnectionError: If not connected.
            RuntimeError: If the Remote Script returned an error.
        """
        response = self._send_command(f"SET:{path}={value}")
        if response.startswith("OK:"):
            return response[3:]
        raise RuntimeError(f"SET {path}={value} failed: {response}")

    def ping(self) -> bool:
        """Check if the RenderMonitor is responsive.

        Returns:
            True if PONG received, False otherwise.
        """
        try:
            response = self._send_command("PING")
            return response.startswith("PONG")
        except (OSError, TimeoutError):
            return False

    def get_status(self) -> RenderStatus:
        """Query the current rendering status.

        Returns:
            RenderStatus with state and message.

        Raises:
            ConnectionError: If not connected.
            TimeoutError: If no response within timeout.
        """
        response = self._send_command("STATUS")
        return _parse_status(response)

    def wait_for_render_complete(
        self,
        timeout: float = 300.0,
        poll_interval: float = 1.0,
        on_status: callable = None,
        assume_started: bool = False,
    ) -> bool:
        """Poll until rendering completes.

        Ableton's offline render blocks its main thread, making the TCP
        server unresponsive during rendering. We detect completion when
        the server becomes responsive again with IDLE after being busy.

        When assume_started=True (caller already triggered the export),
        the first IDLE response means the render is done. This handles
        fast renders that complete before polling begins.

        Args:
            timeout: Maximum seconds to wait total.
            poll_interval: Seconds between status checks.
            on_status: Optional callback(RenderStatus) called on each poll.
            assume_started: If True, treat render as already in progress.

        Returns:
            True if render completed, False if timed out.
        """
        start_time = time.monotonic()
        saw_busy = assume_started

        while time.monotonic() - start_time < timeout:
            try:
                status = self.get_status()
            except (OSError, TimeoutError):
                # Server unresponsive = Ableton is rendering
                if not saw_busy:
                    saw_busy = True
                    if on_status is not None:
                        on_status(RenderStatus(state="RENDERING", message="(server unresponsive — render in progress)"))
                # Reconnect for next attempt since the socket may be dead
                try:
                    self.close()
                    self.connect()
                except OSError:
                    pass
                time.sleep(poll_interval)
                continue

            if on_status is not None:
                on_status(status)

            if status.state in ("RENDERING", "EXPORT_DIALOG"):
                saw_busy = True
            elif status.state == "IDLE" and saw_busy:
                return True

            time.sleep(poll_interval)

        return False

    def _send_command(self, command: str) -> str:
        """Send a command and read the response line.

        Raises:
            ConnectionError: If not connected.
            TimeoutError: If no response within socket timeout.
        """
        if self._socket is None:
            raise ConnectionError("Not connected to RenderMonitor")

        self._socket.sendall((command + "\n").encode("utf-8"))
        data = self._socket.recv(RECV_BUFFER)

        if not data:
            raise ConnectionError("RenderMonitor closed the connection")

        return data.decode("utf-8").strip()


def _parse_status(response: str) -> RenderStatus:
    """Parse a STATUS response into a RenderStatus."""
    if response.startswith("RENDERING:"):
        message = response[len("RENDERING:"):]
        return RenderStatus(state="RENDERING", message=message)
    elif response == "IDLE":
        return RenderStatus(state="IDLE", message="")
    elif response == "EXPORT_DIALOG":
        return RenderStatus(state="EXPORT_DIALOG", message="")
    elif response.startswith("ERROR:"):
        message = response[len("ERROR:"):]
        return RenderStatus(state="ERROR", message=message)
    else:
        return RenderStatus(state="ERROR", message=f"Unexpected response: {response}")
