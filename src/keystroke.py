"""Send keystrokes to Ableton Live via JXA (JavaScript for Automation)."""

import re

from src.automation import run_jxa

# Whitelist patterns for JXA keystroke safety
_VALID_KEY = re.compile(r"^[a-zA-Z0-9]$")
_VALID_KEYCODE = re.compile(r"^[0-9]{1,3}$")
_VALID_MODIFIER = re.compile(
    r'^"(command|shift|option|control|fn) down"'
    r'(, "(command|shift|option|control|fn) down")*$'
)


def send_keystroke(key: str, modifiers: str = "") -> bool:
    """Send a single keystroke via System Events.

    Args:
        key: Single alphanumeric character, or a numeric key code
            (e.g. "36" for Enter).
        modifiers: Optional JXA modifier string
            (e.g. '"command down", "shift down"').

    Returns:
        True if the keystroke was sent successfully.

    Raises:
        ValueError: If key or modifiers fail validation.
    """
    if not isinstance(key, str) or not (_VALID_KEY.match(key) or _VALID_KEYCODE.match(key)):
        raise ValueError(f"Invalid key (must be single alphanumeric or keycode): {key!r}")
    if modifiers and not _VALID_MODIFIER.match(modifiers):
        raise ValueError(f"Invalid modifiers: {modifiers!r}")

    if modifiers:
        script = (
            '(function() { const se = Application("System Events"); '
            'se.keystroke("%s", {using: [%s]}); return "ok"; })();'
            % (key, modifiers)
        )
    elif _VALID_KEYCODE.match(key) and not _VALID_KEY.match(key):
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
