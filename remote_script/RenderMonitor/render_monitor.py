"""RenderMonitor Control Surface.

Runs inside Ableton Live as a MIDI Remote Script. Opens a TCP server
on localhost:9877 and responds to status queries with the current
dialog message — allowing external tools to detect when rendering
is in progress or has completed.

Uses non-blocking sockets and Ableton's schedule_message for safe
periodic polling on the main thread.
"""

import socket

from _Framework.ControlSurface import ControlSurface

TCP_HOST = "127.0.0.1"
TCP_PORT = 9877
POLL_TICKS = 2  # ~200ms between polls
MAX_RECV = 1024


class RenderMonitor(ControlSurface):
    """Control Surface that exposes dialog state via TCP."""

    def __init__(self, c_instance):
        super().__init__(c_instance)

        self._server_socket = None
        self._client_socket = None

        self._start_tcp_server()
        self._schedule_poll()

        self.log_message("RenderMonitor: initialized on port %d" % TCP_PORT)

    def _start_tcp_server(self):
        """Create a non-blocking TCP server socket."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((TCP_HOST, TCP_PORT))
            sock.listen(1)
            sock.setblocking(False)
            self._server_socket = sock
        except Exception as e:
            self.log_message("RenderMonitor: TCP server failed: %s" % str(e))

    def _schedule_poll(self):
        """Schedule the next TCP poll on Ableton's main thread."""
        self.schedule_message(POLL_TICKS, self._poll)

    def _poll(self):
        """Check for TCP connections and handle requests."""
        try:
            self._accept_client()
            self._handle_client_data()
        except Exception as e:
            self.log_message("RenderMonitor: poll error: %s" % str(e))
        finally:
            self._schedule_poll()

    def _accept_client(self):
        """Accept a pending connection if no client is connected."""
        if self._server_socket is None:
            return

        # If we have an existing client, probe it for liveness.
        # After a render (main thread blocked), the client may have
        # disconnected — detect that so we can accept a new one.
        if self._client_socket is not None:
            try:
                data = self._client_socket.recv(1, socket.MSG_PEEK)
                if not data:
                    self._disconnect_client()
            except BlockingIOError:
                pass  # Socket alive, no data yet — keep it
            except (ConnectionResetError, BrokenPipeError, OSError):
                self._disconnect_client()

        if self._client_socket is not None:
            return

        try:
            client, addr = self._server_socket.accept()
            client.setblocking(False)
            self._client_socket = client
            self.log_message("RenderMonitor: client connected from %s" % str(addr))
        except BlockingIOError:
            pass  # No pending connection

    def _handle_client_data(self):
        """Read from the connected client and respond."""
        if self._client_socket is None:
            return

        try:
            data = self._client_socket.recv(MAX_RECV)
        except BlockingIOError:
            return  # No data available yet
        except (ConnectionResetError, BrokenPipeError, OSError):
            self._disconnect_client()
            return

        if not data:
            self._disconnect_client()
            return

        request = data.decode("utf-8").strip()

        for line in request.split("\n"):
            line = line.strip()
            if not line:
                continue
            response = self._handle_request(line)
            try:
                self._client_socket.sendall((response + "\n").encode("utf-8"))
            except (ConnectionResetError, BrokenPipeError, OSError):
                self._disconnect_client()
                return

    def _handle_request(self, request):
        """Process a single request line and return a response string."""
        if request == "STATUS":
            return self._get_status()
        elif request == "INFO":
            return self._get_info()
        elif request == "PING":
            return self._get_ping()
        elif request == "DUMP":
            return self._get_dump()
        elif request == "METHODS":
            return self._get_methods()
        elif request.startswith("EXPLORE:"):
            return self._get_explore(request[8:])
        elif request.startswith("SET:"):
            return self._set_property(request[4:])
        elif request.startswith("GET:"):
            return self._get_property(request[4:])
        else:
            return "ERROR:unknown command '%s'" % request

    def _get_ping(self):
        """PONG + current dialog message for quick debugging."""
        try:
            msg = self.application().current_dialog_message
            return "PONG|dialog=%s" % repr(msg)
        except Exception as e:
            return "PONG|dialog=ERR(%s)" % e

    def _get_status(self):
        """Read the current rendering/dialog state from Ableton.

        Returns one of:
          IDLE              — nothing happening
          EXPORT_DIALOG     — export settings window is open
          RENDERING:<msg>   — render progress dialog is showing
          ERROR:<msg>       — something went wrong
        """
        try:
            app = self.application()
            dialog_message = app.current_dialog_message
            if dialog_message:
                return "RENDERING:%s" % dialog_message

            open_dialogs = app.open_dialog_count
            if open_dialogs > 0:
                return "EXPORT_DIALOG"

            return "IDLE"
        except AttributeError:
            return "ERROR:current_dialog_message not available"
        except Exception as e:
            return "ERROR:%s" % str(e)

    def _get_info(self):
        """Return all available dialog-related properties for debugging."""
        parts = []
        app = self.application()
        for attr in ("current_dialog_message", "current_dialog_button_count"):
            try:
                val = getattr(app, attr)
                parts.append("%s=%s" % (attr, repr(val)))
            except Exception as e:
                parts.append("%s=ERR(%s)" % (attr, e))
        return "INFO:" + "|".join(parts)

    def _get_dump(self):
        """Dump all readable attributes on application() and song() for exploration."""
        results = []

        for obj_name, obj in [("app", self.application()), ("song", self.song())]:
            for attr in sorted(dir(obj)):
                if attr.startswith("_"):
                    continue
                try:
                    val = getattr(obj, attr)
                    if callable(val):
                        continue
                    results.append("%s.%s=%s" % (obj_name, attr, repr(val)))
                except Exception:
                    pass

        return "DUMP:" + "|".join(results)

    def _get_methods(self):
        """List all callable methods on application() and song()."""
        results = []

        for obj_name, obj in [("app", self.application()), ("song", self.song())]:
            for attr in sorted(dir(obj)):
                if attr.startswith("_"):
                    continue
                try:
                    val = getattr(obj, attr)
                    if callable(val):
                        results.append("%s.%s()" % (obj_name, attr))
                except Exception:
                    pass

        return "METHODS:" + "|".join(results)

    def _get_explore(self, path):
        """Explore a sub-object by dotted path.

        Examples: EXPLORE:song.master_track
                  EXPLORE:app.view
                  EXPLORE:song.tracks.0
        """
        roots = {"app": self.application(), "song": self.song()}

        parts = path.strip().split(".")
        if not parts or parts[0] not in roots:
            return "ERROR:path must start with 'app' or 'song'"

        obj = roots[parts[0]]
        traversed = parts[0]

        for part in parts[1:]:
            try:
                if part.isdigit():
                    obj = obj[int(part)]
                else:
                    obj = getattr(obj, part)
                traversed += "." + part
            except Exception as e:
                return "ERROR:failed at '%s.%s': %s" % (traversed, part, e)

        results = []
        for attr in sorted(dir(obj)):
            if attr.startswith("_"):
                continue
            try:
                val = getattr(obj, attr)
                if callable(val):
                    results.append("%s.%s()" % (traversed, attr))
                else:
                    results.append("%s.%s=%s" % (traversed, attr, repr(val)))
            except Exception as e:
                results.append("%s.%s=ERR(%s)" % (traversed, attr, e))

        return "EXPLORE:" + "|".join(results)

    def _resolve_path(self, path):
        """Resolve a dotted path like 'song.loop_start' to (object, attr_name).

        Returns (obj, attr, error_string). On success error_string is None.
        """
        roots = {"app": self.application(), "song": self.song()}

        parts = path.strip().split(".")
        if len(parts) < 2 or parts[0] not in roots:
            return None, None, "path must be 'app.<attr>' or 'song.<attr>'"

        obj = roots[parts[0]]
        # Traverse to the parent of the final attribute
        for part in parts[1:-1]:
            try:
                if part.isdigit():
                    obj = obj[int(part)]
                else:
                    obj = getattr(obj, part)
            except Exception as e:
                return None, None, "failed at '%s': %s" % (part, e)

        return obj, parts[-1], None

    def _get_property(self, path):
        """Read a single property. Example: GET:song.loop_start"""
        obj, attr, err = self._resolve_path(path)
        if err:
            return "ERROR:%s" % err

        try:
            val = getattr(obj, attr)
            return "OK:%s" % repr(val)
        except Exception as e:
            return "ERROR:%s" % e

    def _set_property(self, assignment):
        """Set a property. Example: SET:song.loop_start=0.0

        Supports float, int, and bool values.
        """
        if "=" not in assignment:
            return "ERROR:format is SET:path=value"

        path, value_str = assignment.split("=", 1)
        obj, attr, err = self._resolve_path(path)
        if err:
            return "ERROR:%s" % err

        # Parse value
        value_str = value_str.strip()
        if value_str in ("True", "true"):
            value = True
        elif value_str in ("False", "false"):
            value = False
        elif "." in value_str:
            try:
                value = float(value_str)
            except ValueError:
                return "ERROR:cannot parse '%s' as float" % value_str
        else:
            try:
                value = int(value_str)
            except ValueError:
                return "ERROR:cannot parse '%s' as int" % value_str

        try:
            setattr(obj, attr, value)
            # Read back to confirm
            actual = getattr(obj, attr)
            return "OK:%s=%s" % (path, repr(actual))
        except Exception as e:
            return "ERROR:%s" % e

    def _disconnect_client(self):
        """Clean up the current client connection."""
        if self._client_socket is not None:
            try:
                self._client_socket.close()
            except OSError:
                pass
            self._client_socket = None
            self.log_message("RenderMonitor: client disconnected")

    def disconnect(self):
        """Called by Ableton when unloading this Control Surface."""
        self.log_message("RenderMonitor: shutting down")
        self._disconnect_client()

        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass
            self._server_socket = None

        super().disconnect()
