"""Send keystrokes to Ableton Live via JXA (JavaScript for Automation)."""

from src.automation import run_jxa


def send_keystroke(key: str, modifiers: str = "") -> bool:
    """Send a single keystroke via System Events.

    Args:
        key: Character to type, or a numeric key code (e.g. "36" for Enter).
        modifiers: Optional JXA modifier string (e.g. "command down").

    Returns:
        True if the keystroke was sent successfully.
    """
    if modifiers:
        script = (
            '(function() { const se = Application("System Events"); '
            'se.keystroke("%s", {using: [%s]}); return "ok"; })();'
            % (key, modifiers)
        )
    elif key.isdigit():
        script = (
            '(function() { const se = Application("System Events"); '
            'se.keyCode(%s); return "ok"; })();' % key
        )
    else:
        script = (
            '(function() { const se = Application("System Events"); '
            'se.keystroke("%s"); return "ok"; })();' % key
        )
    result = run_jxa(script)
    return result["success"] and result["result"] == "ok"


def send_enter() -> bool:
    """Send the Enter/Return key (key code 36).

    Returns:
        True if the keystroke was sent successfully.
    """
    return send_keystroke("36")
