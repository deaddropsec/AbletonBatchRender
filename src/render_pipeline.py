"""Per-project render pipeline for Ableton Live offline export.

Orchestrates the full workflow: parse .als, resolve samples, open in
Ableton, set loop boundaries, trigger export, monitor render, verify output.
"""

import time
from pathlib import Path

from src.als_parser import extract_sample_refs, get_project_length, parse_als
from src.als_patcher import patch_sample_paths, write_als
from src.automation import activate_ableton, wait_for_sheet_and_confirm
from src.dialog_handler import dismiss_blocking_dialog, poll_dialog_count
from src.keystroke import send_enter, send_keystroke
from src.project_loader import open_project_in_ableton
from src.sample_resolver import resolve_missing_samples
from src.tcp_client import RenderMonitorClient

PADDING_BARS = 2
EXPORT_TIMEOUT = 600.0
POLL_INTERVAL = 2.0


def render_project(
    als_path: Path,
    client: RenderMonitorClient,
    export_dir: Path | None,
    search_paths: list[str] | None = None,
) -> bool:
    """Full render pipeline for a single project.

    Steps:
        1. Parse .als and get content length
        2. Resolve missing samples, patch .als if needed
        3. Open project in Ableton
        4. Verify Ableton is idle
        5. Set loop to content length + padding
        6. Trigger export and confirm dialogs
        7. Wait for render to complete
        8. Verify export file exists

    Returns:
        True on success, False on failure.
    """
    print(f"\n{'=' * 60}")
    print(f"  Project: {als_path.name}")
    print(f"{'=' * 60}")

    print(f"\n>> Parsing .als file")
    tree = parse_als(als_path)
    content_length = get_project_length(tree)
    print(f"  Content length: {content_length} beats")
    if content_length <= 0:
        print(f"  ASSERT FAILED: No content found (no clips in arrangement)")
        return False

    print(f"\n>> Checking samples")
    render_path, is_patched = _resolve_samples(
        tree, als_path, search_paths or [],
    )

    try:
        print(f"\n>> Opening in Ableton")
        open_project_in_ableton(render_path, client)

        print(f"\n>> Verifying Ableton state")
        status = client.get_status()
        if status.state != "IDLE":
            print(f"  ASSERT FAILED: Expected IDLE, got {status.state}")
            return False
        print("  Ableton is IDLE and ready")

        print(f"\n>> Setting loop to content length")
        _set_loop_to_content(client, content_length)

        print(f"\n>> Triggering export")
        _trigger_export_and_confirm(client)

        print(f"\n>> Monitoring render")
        completed = _wait_for_render(client)

        if completed:
            print("  Render complete!")
        else:
            print("  WARNING: Render monitoring timed out")
            return False

        if export_dir:
            print(f"\n>> Verifying export")
            if not _verify_export(als_path, export_dir):
                return False

        return True
    finally:
        if is_patched and render_path.exists():
            render_path.unlink()
            print(f"  Cleaned up patched copy: {render_path.name}")


def _set_loop_to_content(
    client: RenderMonitorClient, content_length: float,
) -> None:
    """Set the loop brace to cover the full content + padding."""
    sig_num = int(float(client.get_property("song.signature_numerator")))
    sig_den = int(float(client.get_property("song.signature_denominator")))
    beats_per_bar = sig_num * (4.0 / sig_den)
    padding_beats = PADDING_BARS * beats_per_bar
    loop_length = content_length + padding_beats

    client.set_property("song.loop_start", 0.0)
    client.set_property("song.loop_length", loop_length)
    client.set_property("song.loop", True)

    print(f"  Loop set: 0 to {loop_length} beats "
          f"({content_length} content + {PADDING_BARS} bars padding)")


def _trigger_export_and_confirm(
    client: RenderMonitorClient, max_retries: int = 10,
) -> None:
    """Trigger the export shortcut, verify dialogs, and confirm."""
    for attempt in range(max_retries):
        dismissed = dismiss_blocking_dialog(client)
        if dismissed:
            print(f"  Dismissed '{dismissed}' dialog, waiting before retry...")
            time.sleep(2.0)
            continue

        try:
            dialog_count = int(float(client.get_property("app.open_dialog_count")))
        except (OSError, RuntimeError):
            print(f"  Ableton unresponsive (attempt {attempt + 1}/{max_retries}), waiting...")
            time.sleep(3.0)
            try:
                client.close()
                client.connect()
            except OSError:
                pass
            continue

        if dialog_count > 0:
            print(f"  Dialog still open (count={dialog_count}), waiting...")
            time.sleep(2.0)
            continue

        print("  Sending Cmd+Shift+R...")
        activate_ableton()
        time.sleep(0.5)
        send_keystroke("r", '"command down", "shift down"')

        dialog_count = poll_dialog_count(client, target=1, timeout=5.0)
        if dialog_count >= 1:
            break

        print(f"  Export dialog didn't open (attempt {attempt + 1}/{max_retries}), retrying...")
        time.sleep(2.0)
    else:
        print(f"  ASSERT FAILED: Export dialog failed to open after {max_retries} attempts")
        return

    print(f"  Export dialog opened (dialog_count={dialog_count})")

    print("  Pressing Enter (confirm export settings)...")
    activate_ableton()
    time.sleep(0.3)
    send_enter()

    dialog_count = poll_dialog_count(client, target=2, timeout=10.0)
    print(f"  After first Enter: dialog_count={dialog_count}")

    print("  Pressing Enter (confirm save location)...")
    activate_ableton()
    time.sleep(0.3)
    send_enter()

    print("  Checking for overwrite confirmation...")
    sheet_result = wait_for_sheet_and_confirm(timeout=3.0)
    print(f"  Overwrite check: {sheet_result}")


def _wait_for_render(client: RenderMonitorClient) -> bool:
    """Wait for the render to complete by monitoring dialog state."""
    print(f"  Waiting for render to complete (timeout: {EXPORT_TIMEOUT}s)...")

    def on_status(status):
        print(f"    [{status.state}] {status.message}")

    return client.wait_for_render_complete(
        timeout=EXPORT_TIMEOUT,
        poll_interval=POLL_INTERVAL,
        on_status=on_status,
        assume_started=True,
    )


def _verify_export(als_path: Path, export_dir: Path) -> bool:
    """Check if the expected export file exists."""
    stem = als_path.stem
    for ext in (".wav", ".mp3", ".aif", ".flac"):
        export_file = export_dir / f"{stem}{ext}"
        if export_file.exists():
            size_mb = export_file.stat().st_size / (1024 * 1024)
            print(f"  Export found: {export_file.name} ({size_mb:.1f} MB)")
            return True
    print(f"  WARNING: No export file found for '{stem}' in {export_dir}")
    return False


def _resolve_samples(
    tree, als_path: Path, search_paths: list[str],
) -> tuple[Path, bool]:
    """Check for missing samples and create a patched .als if needed.

    Returns:
        (render_path, is_patched) — the path to render and whether it's
        a patched copy that should be cleaned up afterward.
    """
    refs = extract_sample_refs(tree, als_path)
    missing_refs = [r for r in refs if not Path(r["path"]).exists()]

    if not missing_refs:
        print(f"  All {len(refs)} samples found")
        return als_path, False

    print(f"  {len(missing_refs)} missing samples (out of {len(refs)}):")
    for r in missing_refs:
        print(f"    - {r['filename']}  ({r['path']})")

    if not search_paths:
        print("  No search paths configured — skipping sample resolution")
        return als_path, False

    print(f"\n>> Resolving missing samples")
    resolved = resolve_missing_samples(missing_refs, search_paths)

    if not resolved:
        print("  Could not find any missing samples")
        return als_path, False

    for old_path, new_path in resolved.items():
        print(f"    Found: {Path(old_path).name} -> {new_path}")

    still_missing = len(missing_refs) - len(resolved)
    if still_missing > 0:
        print(f"    {still_missing} sample(s) still unresolved")

    print(f"\n>> Patching .als with resolved paths")
    patched_tree = patch_sample_paths(tree, resolved, als_path.parent)
    patched_path = als_path.with_name(als_path.stem + "_patched.als")
    write_als(patched_tree, patched_path)
    print(f"  Patched copy: {patched_path.name}")

    return patched_path, True
