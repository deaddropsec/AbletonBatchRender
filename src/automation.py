"""macOS automation for Ableton Live via JXA (JavaScript for Automation).

Uses osascript to send keyboard shortcuts and control Ableton Live.
All functions are stateless and target the app by name/process name.
"""

import subprocess
import time

ABLETON_APP_NAME = "Ableton Live 12 Suite"
ABLETON_PROCESS_NAME = "Live"
LAUNCH_TIMEOUT = 60.0
LAUNCH_POLL_INTERVAL = 2.0


def run_jxa(script: str, timeout: int = 30) -> dict:
    """Execute a JXA script via osascript.

    Args:
        script: JavaScript for Automation source code.
        timeout: Maximum seconds to wait for the script.

    Returns:
        Dict with 'success' (bool), 'result' (str|None), 'error' (str|None).
    """
    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return {"success": True, "result": result.stdout.strip(), "error": None}
        return {"success": False, "result": None, "error": result.stderr.strip()}

    except subprocess.TimeoutExpired:
        return {"success": False, "result": None, "error": f"Timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}


def is_ableton_running() -> bool:
    """Check if Ableton Live is currently running."""
    script = """
    (function() {
        const se = Application("System Events");
        const procs = se.processes.whose({name: "%s"});
        return procs.length > 0;
    })();
    """ % ABLETON_PROCESS_NAME

    result = run_jxa(script)
    return result["success"] and result["result"] == "true"


def launch_ableton(timeout: float = LAUNCH_TIMEOUT) -> bool:
    """Launch Ableton Live if not already running and wait until it's ready.

    Uses macOS `open -a` to start the app, then polls until the process
    appears in System Events.

    Args:
        timeout: Maximum seconds to wait for Ableton to start.

    Returns:
        True if Ableton is running (either already was or successfully launched).
    """
    if is_ableton_running():
        return True

    try:
        subprocess.run(
            ["open", "-a", ABLETON_APP_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_ableton_running():
            return True
        time.sleep(LAUNCH_POLL_INTERVAL)

    return False


def activate_ableton() -> bool:
    """Bring Ableton Live to the foreground."""
    script = """
    (function() {
        try {
            Application("%s").activate();
            return "ok";
        } catch (e) {
            return "error: " + e.toString();
        }
    })();
    """ % ABLETON_APP_NAME

    result = run_jxa(script)
    return result["success"] and result["result"] == "ok"


def handle_save_dialog() -> bool:
    """Dismiss a 'Save changes?' dialog by sending Cmd+D ('Don't Save').

    Tries Cmd+D first (locale-independent macOS shortcut for 'Don't Save').
    Falls back to clicking the button by name if a sheet is detected.
    Safe to call when no dialog is present — Cmd+D is a no-op without a sheet.

    Returns:
        True if handled (or no dialog found).
    """
    script = """
    (function() {
        try {
            const se = Application("System Events");
            const proc = se.processes.byName("%s");
            const wins = proc.windows;

            if (wins.length > 0) {
                const mainWin = wins[0];
                if (mainWin.sheets.length > 0) {
                    // Sheet found — send Cmd+D for "Don't Save"
                    se.keystroke("d", {using: "command down"});
                    return "shortcut";
                }
            }
            return "no_dialog";
        } catch (e) {
            return "error: " + e.toString();
        }
    })();
    """ % ABLETON_PROCESS_NAME

    result = run_jxa(script)
    return result["success"] and result["result"] != "error"


def wait_for_sheet_and_confirm(timeout: float = 5.0, poll: float = 0.3) -> str:
    """Wait for a system sheet (e.g. overwrite confirmation) and press Enter.

    Polls Ableton's windows for a sheet to appear. When found, sends
    Enter to confirm (hits the default button, e.g. "Replace"/"Ersetzen").
    If no sheet appears within timeout, returns — the file didn't exist
    and the save went through without an overwrite prompt.

    Returns:
        "confirmed_sheet" if a sheet was found and Enter pressed,
        "no_sheet" if no sheet appeared (no overwrite needed),
        "error:<msg>" on failure.
    """
    script = """
    (function() {
        const se = Application("System Events");
        const proc = se.processes.byName("%s");
        const maxWait = %s;
        const pollInterval = %s;
        var elapsed = 0;

        while (elapsed < maxWait) {
            try {
                const wins = proc.windows();
                for (var i = 0; i < wins.length; i++) {
                    var sheets = wins[i].sheets();
                    if (sheets.length > 0) {
                        // Sheet found — press Enter to confirm default button
                        se.keyCode(36);
                        return "confirmed_sheet";
                    }
                }
            } catch(e) {}
            delay(pollInterval);
            elapsed += pollInterval;
        }
        return "no_sheet";
    })();
    """ % (ABLETON_PROCESS_NAME, timeout, poll)

    result = run_jxa(script, timeout=int(timeout) + 5)
    if result["success"]:
        return result["result"]
    return "error:%s" % result["error"]


