"""Tests for tcp_client module.

Uses a mock TCP server to simulate the RenderMonitor Remote Script.
"""

import socket
import threading
import time

import pytest

from src.tcp_client import RenderMonitorClient, RenderStatus, _parse_status


# --- Mock TCP Server ---


class MockRenderMonitor:
    """Simple TCP server that simulates the RenderMonitor Remote Script."""

    def __init__(self, port: int = 0):
        self._port = port
        self._socket = None
        self.port = 0  # Actual bound port
        self.dialog_message = ""  # Empty = IDLE, non-empty = RENDERING
        self.open_dialog_count = 0  # >0 = export dialog open
        self._running = False
        self._thread = None
        self._create_socket()

    def _create_socket(self):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", self._port))
        self._socket.listen(1)
        self._socket.settimeout(5.0)
        self.port = self._socket.getsockname()[1]
        # Lock port for restarts
        self._port = self.port

    def start(self):
        if self._socket is None:
            self._create_socket()
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        try:
            self._socket.close()
        except OSError:
            pass
        self._socket = None
        if self._thread:
            self._thread.join(timeout=2.0)

    def _serve(self):
        while self._running:
            try:
                client, _ = self._socket.accept()
                client.settimeout(2.0)
                threading.Thread(
                    target=self._handle_client,
                    args=(client,),
                    daemon=True,
                ).start()
            except (socket.timeout, OSError):
                continue

    def _handle_client(self, client: socket.socket):
        try:
            while self._running:
                data = client.recv(1024)
                if not data:
                    break
                request = data.decode("utf-8").strip()
                for line in request.split("\n"):
                    line = line.strip()
                    if line == "STATUS":
                        if self.dialog_message:
                            response = f"RENDERING:{self.dialog_message}"
                        elif self.open_dialog_count > 0:
                            response = "EXPORT_DIALOG"
                        else:
                            response = "IDLE"
                    elif line == "PING":
                        response = "PONG"
                    else:
                        response = f"ERROR:unknown command '{line}'"
                    client.sendall((response + "\n").encode("utf-8"))
        except (socket.timeout, OSError):
            pass
        finally:
            try:
                client.close()
            except OSError:
                pass


@pytest.fixture
def mock_server():
    server = MockRenderMonitor()
    server.start()
    yield server
    server.stop()


# --- _parse_status tests ---


class TestParseStatus:
    def test_idle(self):
        status = _parse_status("IDLE")
        assert status.state == "IDLE"
        assert status.message == ""

    def test_rendering(self):
        status = _parse_status("RENDERING:Exporting audio...")
        assert status.state == "RENDERING"
        assert status.message == "Exporting audio..."

    def test_error(self):
        status = _parse_status("ERROR:something went wrong")
        assert status.state == "ERROR"
        assert status.message == "something went wrong"

    def test_export_dialog(self):
        status = _parse_status("EXPORT_DIALOG")
        assert status.state == "EXPORT_DIALOG"
        assert status.message == ""

    def test_unexpected(self):
        status = _parse_status("GARBAGE")
        assert status.state == "ERROR"
        assert "Unexpected" in status.message


# --- RenderMonitorClient tests ---


class TestRenderMonitorClient:
    def test_connect_and_ping(self, mock_server):
        with RenderMonitorClient(port=mock_server.port) as client:
            assert client.ping() is True

    def test_get_status_idle(self, mock_server):
        mock_server.dialog_message = ""
        with RenderMonitorClient(port=mock_server.port) as client:
            status = client.get_status()
            assert status.state == "IDLE"

    def test_get_status_rendering(self, mock_server):
        mock_server.dialog_message = "Rendering Track 1..."
        with RenderMonitorClient(port=mock_server.port) as client:
            status = client.get_status()
            assert status.state == "RENDERING"
            assert status.message == "Rendering Track 1..."

    def test_get_status_export_dialog(self, mock_server):
        mock_server.open_dialog_count = 1
        with RenderMonitorClient(port=mock_server.port) as client:
            status = client.get_status()
            assert status.state == "EXPORT_DIALOG"

    def test_raises_when_not_connected(self):
        client = RenderMonitorClient()
        with pytest.raises(ConnectionError, match="Not connected"):
            client.get_status()

    def test_raises_on_refused_connection(self):
        # Use a port where nothing is listening
        client = RenderMonitorClient(port=19999)
        with pytest.raises(ConnectionRefusedError):
            client.connect()

    def test_context_manager_closes(self, mock_server):
        client = RenderMonitorClient(port=mock_server.port)
        with client:
            assert client.ping() is True
        # After exiting, socket should be closed
        assert client._socket is None


class TestWaitForRenderComplete:
    def test_detects_render_via_rendering_state(self, mock_server):
        """Simulate: IDLE → RENDERING → IDLE = complete."""
        mock_server.dialog_message = ""

        statuses = []

        def on_status(s):
            statuses.append(s)

        with RenderMonitorClient(port=mock_server.port) as client:
            def simulate_render():
                time.sleep(0.3)
                mock_server.dialog_message = "Rendering..."
                time.sleep(0.8)
                mock_server.dialog_message = ""

            t = threading.Thread(target=simulate_render, daemon=True)
            t.start()

            completed = client.wait_for_render_complete(
                timeout=5.0,
                poll_interval=0.2,
                on_status=on_status,
            )

            assert completed is True
            states = [s.state for s in statuses]
            assert "RENDERING" in states

    def test_detects_render_via_timeout(self, mock_server):
        """Simulate: responsive → server stops → server resumes = complete.

        This mimics Ableton blocking its main thread during rendering,
        making the TCP server unresponsive.
        """
        mock_server.dialog_message = ""

        statuses = []

        def on_status(s):
            statuses.append(s)

        with RenderMonitorClient(port=mock_server.port) as client:
            def simulate_blocked_render():
                time.sleep(0.3)
                mock_server.stop()       # Server becomes unresponsive
                time.sleep(1.0)
                mock_server.start()      # Server comes back (render done)

            t = threading.Thread(target=simulate_blocked_render, daemon=True)
            t.start()

            completed = client.wait_for_render_complete(
                timeout=5.0,
                poll_interval=0.2,
                on_status=on_status,
            )

            assert completed is True

    def test_detects_render_via_export_dialog(self, mock_server):
        """Simulate full flow: IDLE → EXPORT_DIALOG → IDLE = complete."""
        mock_server.dialog_message = ""
        mock_server.open_dialog_count = 0

        statuses = []

        def on_status(s):
            statuses.append(s)

        with RenderMonitorClient(port=mock_server.port) as client:
            def simulate_export_flow():
                time.sleep(0.3)
                mock_server.open_dialog_count = 1   # Export dialog opens
                time.sleep(0.5)
                mock_server.open_dialog_count = 0   # Dialog closes, render done

            t = threading.Thread(target=simulate_export_flow, daemon=True)
            t.start()

            completed = client.wait_for_render_complete(
                timeout=5.0,
                poll_interval=0.2,
                on_status=on_status,
            )

            assert completed is True
            states = [s.state for s in statuses]
            assert "EXPORT_DIALOG" in states

    def test_timeout_when_never_renders(self, mock_server):
        """If rendering never starts, should timeout."""
        mock_server.dialog_message = ""
        with RenderMonitorClient(port=mock_server.port) as client:
            completed = client.wait_for_render_complete(
                timeout=0.5,
                poll_interval=0.1,
            )
            assert completed is False

    def test_timeout_when_stuck_rendering(self, mock_server):
        """If rendering starts but never finishes, should timeout."""
        mock_server.dialog_message = "Rendering forever..."
        with RenderMonitorClient(port=mock_server.port) as client:
            completed = client.wait_for_render_complete(
                timeout=0.5,
                poll_interval=0.1,
            )
            assert completed is False


# --- RenderStatus tests ---


class TestRenderStatus:
    def test_is_frozen(self):
        status = RenderStatus(state="IDLE", message="")
        with pytest.raises(AttributeError):
            status.state = "RENDERING"
