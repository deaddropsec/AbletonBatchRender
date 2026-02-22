"""Resolve missing audio samples by searching configured directories.

Builds a filename index with a single `rg --files` pass across all
search paths, then resolves missing samples via in-memory lookup.
Falls back to BSD find if rg is not available.
"""

import json
import subprocess
from collections import defaultdict
from pathlib import Path


def load_config(config_path: str = "config.json") -> dict:
    """Load and validate the project configuration.

    Args:
        config_path: Path to the JSON config file.

    Returns:
        Parsed config dict.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValueError: If required keys are missing.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(path) as f:
        config = json.load(f)

    if "sample_search_paths" not in config:
        raise ValueError("Config missing 'sample_search_paths' key")

    search_paths = config["sample_search_paths"]
    if not isinstance(search_paths, list) or not search_paths:
        raise ValueError("'sample_search_paths' must be a non-empty list")

    return config


def build_file_index(search_paths: list[str]) -> dict[str, list[Path]]:
    """Build a filename -> [paths] index from search directories.

    Runs a single `rg --files` pass per search directory to list all
    files, then indexes them by filename for O(1) lookup.

    Args:
        search_paths: Directories to scan recursively.

    Returns:
        Dict mapping lowercase filename to list of absolute Paths.
    """
    index = defaultdict(list)

    for search_dir in search_paths:
        if not Path(search_dir).is_dir():
            continue

        file_list = _list_files_rg(search_dir)
        if file_list is None:
            file_list = _list_files_find(search_dir)

        for file_path in file_list:
            index[file_path.name.lower()].append(file_path)

    return dict(index)


def resolve_missing_samples(
    missing_refs: list[dict],
    search_paths: list[str],
) -> dict[str, Path]:
    """Resolve missing sample paths by searching configured directories.

    Builds a file index once, then looks up each missing sample by
    filename. Disambiguates multiple matches by file size when available.

    Args:
        missing_refs: List of sample ref dicts from extract_sample_refs()
            that have been confirmed missing. Each dict has keys:
            path, filename, file_size, crc.
        search_paths: Directories to search recursively.

    Returns:
        Mapping of original_path_str -> resolved_Path for samples
        that were found. Missing samples that couldn't be found
        are omitted from the result.
    """
    index = build_file_index(search_paths)
    resolved = {}

    for ref in missing_refs:
        original_path = ref["path"]
        filename = ref["filename"]
        expected_size = ref["file_size"]

        candidates = index.get(filename.lower(), [])

        if not candidates:
            continue

        if len(candidates) == 1:
            resolved[original_path] = candidates[0]
            continue

        # Multiple matches — try to disambiguate by file size
        best = _pick_best_match(candidates, expected_size)
        resolved[original_path] = best

    return resolved


def _list_files_rg(search_dir: str) -> list[Path] | None:
    """List all files using ripgrep. Returns None if rg is not available."""
    try:
        result = subprocess.run(
            ["rg", "--files", "--no-ignore", search_dir],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return []

    if result.returncode not in (0, 1):
        return None

    return [
        Path(line)
        for line in result.stdout.strip().splitlines()
        if line
    ]


def _list_files_find(search_dir: str) -> list[Path]:
    """Fallback: list all files using BSD find."""
    try:
        result = subprocess.run(
            ["find", search_dir, "-type", "f"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    return [
        Path(line)
        for line in result.stdout.strip().splitlines()
        if line
    ]


def _pick_best_match(candidates: list[Path], expected_size: int) -> Path:
    """Pick the best match from multiple candidates.

    If expected_size > 0, prefer the candidate whose file size matches.
    Otherwise, return the first candidate.
    """
    if expected_size > 0:
        for candidate in candidates:
            try:
                if candidate.stat().st_size == expected_size:
                    return candidate
            except OSError:
                continue

    return candidates[0]
