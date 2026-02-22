"""RenderMonitor — Ableton MIDI Remote Script.

Exposes the current dialog message via TCP so external tools
can detect when rendering is complete.

Installation:
    Symlink or copy this folder to:
    ~/Music/Ableton/User Library/Remote Scripts/RenderMonitor/

    Then in Ableton: Preferences > Link, Tempo & MIDI >
    Control Surface > RenderMonitor

Protocol (TCP on localhost:9877, newline-delimited):
    Client sends: STATUS\\n
    Server responds: RENDERING:<message>\\n or IDLE\\n

    Client sends: PING\\n
    Server responds: PONG\\n
"""

from .render_monitor import RenderMonitor


def create_instance(c_instance):
    """Entry point called by Ableton when loading this Control Surface."""
    return RenderMonitor(c_instance)
