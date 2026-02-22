"""Command-line interface for the Ableton Offline Renderer.

Handles argument parsing, config loading, Ableton connection setup,
batch processing loop, and summary output.
"""

import argparse
import sys
import time
import traceback
from pathlib import Path

from src.automation import is_ableton_running, launch_ableton
from src.project_loader import collect_als_files
from src.render_pipeline import render_project
from src.sample_resolver import load_config
from src.tcp_client import RenderMonitorClient


def main() -> int:
    """Entry point for the Ableton Offline Renderer CLI."""
    args = _parse_args()

    als_files = collect_als_files(Path(args.path))
    search_paths = _load_search_paths()

    _print_banner(als_files, search_paths, args.export_dir)
    client = _connect_to_ableton()

    results = _run_batch(als_files, client, args.export_dir, search_paths)

    _print_summary(results)
    return 0 if all(results.values()) else 1


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Ableton Offline Renderer — batch export .als projects",
    )
    parser.add_argument(
        "path",
        help="Path to .als file or directory of .als files",
    )
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=None,
        help="Directory where Ableton exports files (for verification)",
    )
    return parser.parse_args()


def _load_search_paths() -> list[str]:
    """Load sample search paths from config, or return empty list."""
    try:
        config = load_config()
        return config.get("sample_search_paths", [])
    except (FileNotFoundError, ValueError) as e:
        print(f"  Config: {e} — sample resolution disabled")
        return []


def _print_banner(
    als_files: list[Path], search_paths: list[str], export_dir: Path | None,
) -> None:
    """Print startup information."""
    print(f"\n=== Ableton Offline Renderer ===")
    print(f"  Projects: {len(als_files)}")
    if search_paths:
        print(f"  Sample search paths: {len(search_paths)}")
    if export_dir:
        print(f"  Export dir: {export_dir}")


def _connect_to_ableton() -> RenderMonitorClient:
    """Launch Ableton if needed and connect to the RenderMonitor.

    Raises:
        SystemExit: If Ableton can't be launched or RenderMonitor
            doesn't respond within 120 seconds.
    """
    if not is_ableton_running():
        print("  Ableton not running — launching...")
        if not launch_ableton():
            print("  ASSERT FAILED: Failed to launch Ableton Live")
            sys.exit(1)
        print("  Ableton launched")
    else:
        print("  Ableton is already running")

    print("  Connecting to RenderMonitor...")
    client = RenderMonitorClient()
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        try:
            client.connect()
            if client.ping():
                break
            client.close()
        except (ConnectionRefusedError, OSError):
            pass
        time.sleep(2.0)
    else:
        print("  ASSERT FAILED: RenderMonitor not responding after 120s — is the Remote Script active?")
        sys.exit(1)
    print("  Connected to RenderMonitor")
    return client


def _run_batch(
    als_files: list[Path],
    client: RenderMonitorClient,
    export_dir: Path | None,
    search_paths: list[str],
) -> dict[str, bool]:
    """Process all .als files and collect results."""
    results = {}
    try:
        for als_path in als_files:
            try:
                success = render_project(als_path, client, export_dir, search_paths)
                results[als_path.name] = success
            except SystemExit:
                results[als_path.name] = False
                print(f"  FAILED: {als_path.name}")
            except Exception as e:
                results[als_path.name] = False
                print(f"  ERROR: {als_path.name}: {e}")
                traceback.print_exc(file=sys.stderr)
    finally:
        client.close()
    return results


def _print_summary(results: dict[str, bool]) -> None:
    """Print the batch processing summary."""
    print(f"\n{'=' * 60}")
    print(f"  SUMMARY")
    print(f"{'=' * 60}")
    for name, success in results.items():
        status = "OK" if success else "FAILED"
        print(f"  [{status}] {name}")

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"\n  {passed}/{total} projects rendered successfully")
