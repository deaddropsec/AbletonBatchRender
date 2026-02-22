"""Load Ableton Live projects — file discovery and project opening.

Handles collecting .als files from paths and opening them in Ableton
via the `open` command, with TCP polling to verify the project loaded.
"""

import subprocess
import sys
import time
from pathlib import Path

from src.dialog_handler import dismiss_blocking_dialog
from src.tcp_client import RenderMonitorClient


def collect_als_files(path: Path) -> list[Path]:
    """Collect .als files from a path (single file or directory).

    Excludes files inside 'Backup' folders and '_patched.als' files.

    Args:
        path: Path to a single .als file or a directory to search.

    Returns:
        Sorted list of .als file paths.

    Raises:
        SystemExit: If no .als files are found or path is invalid.
    """
    path = path.resolve()
    if path.is_file() and path.suffix == ".als":
        return [path]
    if path.is_dir():
        files = sorted(
            f for f in path.rglob("*.als")
            if "Backup" not in f.parts and not f.stem.endswith("_patched")
        )
        if not files:
            print(f"  No .als files found in {path}")
            sys.exit(1)
        return files
    print(f"  Not a valid .als file or directory: {path}")
    sys.exit(1)


def open_project_in_ableton(
    als_path: Path, client: RenderMonitorClient, timeout: float = 60.0,
) -> None:
    """Open a project and wait until Ableton has loaded it.

    Polls song.file_path via TCP instead of using a fixed delay.
    Handles the 'save changes' dialog that appears when switching projects.
    Reconnects TCP if needed (Ableton may briefly drop the connection).

    Args:
        als_path: Path to the .als file to open.
        client: Connected RenderMonitorClient.
        timeout: Maximum seconds to wait for project to load.
    """
    resolved_path = als_path.resolve()
    if resolved_path.suffix != ".als":
        raise ValueError(f"Symlink target is not an .als file: {resolved_path}")

    print(f"  Opening: {als_path.name}")
    subprocess.run(["open", str(resolved_path)], capture_output=True, timeout=10)

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        dismiss_blocking_dialog(client)

        try:
            raw = client.get_property("song.file_path")
            loaded_path = raw.strip("'\"")
            if loaded_path and Path(loaded_path).resolve() == als_path.resolve():
                print(f"  Project loaded: {loaded_path}")
                return
        except (OSError, RuntimeError):
            try:
                client.close()
                client.connect()
            except OSError:
                pass

        time.sleep(1.0)

    print("  WARNING: Could not verify song.file_path matches. Proceeding anyway.")
