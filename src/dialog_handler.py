"""Detect and dismiss Ableton Live dialogs that block the export workflow.

Handles save dialogs, sample decoding dialogs, and unknown dialogs.
Uses the TCP client to query dialog state and JXA keystrokes to dismiss.
"""

import time

from src.automation import activate_ableton
from src.keystroke import send_enter, send_keystroke
from src.tcp_client import RenderMonitorClient


def dismiss_blocking_dialog(client: RenderMonitorClient) -> str | None:
    """Detect and dismiss known Ableton dialogs that block the workflow.

    Handles:
      - Save dialog ("sichern"/"save") -> sends 'n' to decline
      - Sample decoding dialog ("dekodiert"/"decoded"/"bereit") -> sends Enter
      - Unknown dialog with text -> sends Enter as fallback

    Args:
        client: Connected RenderMonitorClient instance.

    Returns:
        Name of dismissed dialog ("save", "sample_loading", "unknown"),
        or None if no dialog found or on connection error.
    """
    try:
        dialog_count = int(float(client.get_property("app.open_dialog_count")))
        if dialog_count == 0:
            return None

        msg = client.get_property("app.current_dialog_message").lower()

        if "sichern" in msg or "save" in msg:
            activate_ableton()
            time.sleep(0.2)
            send_keystroke("n")
            time.sleep(0.5)
            return "save"

        if "dekodiert" in msg or "decoded" in msg or "bereit" in msg or "ready" in msg:
            activate_ableton()
            time.sleep(0.2)
            send_enter()
            time.sleep(0.5)
            return "sample_loading"

        if msg.strip():
            activate_ableton()
            time.sleep(0.2)
            send_enter()
            time.sleep(0.5)
            return "unknown"

    except (OSError, RuntimeError):
        pass
    return None


def poll_dialog_count(
    client: RenderMonitorClient, target: int, timeout: float = 10.0,
) -> int:
    """Poll app.open_dialog_count until it reaches target or times out.

    Used to wait for a dialog to appear (e.g. after triggering an export)
    before attempting to interact with it.

    Args:
        client: Connected RenderMonitorClient instance.
        target: Minimum dialog count to wait for.
        timeout: Maximum seconds to wait.

    Returns:
        The last observed dialog count, or -1 on persistent error.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            count = int(float(client.get_property("app.open_dialog_count")))
            if count >= target:
                return count
        except (OSError, RuntimeError):
            pass
        time.sleep(0.5)
    try:
        return int(float(client.get_property("app.open_dialog_count")))
    except (OSError, RuntimeError):
        return -1
