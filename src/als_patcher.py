"""Patch and write Ableton Live Set (.als) files.

Creates modified copies of .als files with updated sample paths.
All operations are immutable — the original tree is never mutated.
"""

import gzip
from copy import deepcopy
from pathlib import Path

from lxml import etree

from src.als_parser import AUDIO_EXTENSIONS


def patch_sample_paths(
    tree: etree._ElementTree,
    path_map: dict[str, Path],
    als_dir: Path | None = None,
) -> etree._ElementTree:
    """Create a patched copy of the .als tree with updated sample paths.

    Args:
        tree: Original parsed .als XML tree (not mutated).
        path_map: Mapping of old absolute path strings to new Path objects.
        als_dir: Directory of the output .als file, used to compute
            relative paths. If None, relative paths are cleared.

    Returns:
        New ElementTree with updated FileRef elements.
    """
    patched = deepcopy(tree)
    root = patched.getroot()
    patched_count = 0

    for fileref in root.iter("FileRef"):
        path_elem = fileref.find("Path")
        if path_elem is None:
            continue

        old_path = path_elem.get("Value", "")
        if old_path not in path_map:
            continue

        new_path = path_map[old_path]

        # Update absolute path
        path_elem.set("Value", str(new_path))

        # Update relative path
        rel_path_elem = fileref.find("RelativePath")
        if rel_path_elem is not None and als_dir is not None:
            try:
                relative = new_path.relative_to(als_dir)
                rel_path_elem.set("Value", str(relative))
            except ValueError:
                # new_path is not under als_dir — use ../ segments
                try:
                    relative = _compute_relative_path(als_dir, new_path)
                    rel_path_elem.set("Value", relative)
                except ValueError:
                    rel_path_elem.set("Value", "")

        patched_count += 1

    return patched


def write_als(tree: etree._ElementTree, output_path: Path) -> Path:
    """Serialize an XML tree to a gzip-compressed .als file.

    Args:
        tree: The ElementTree to write.
        output_path: Destination path for the .als file.

    Returns:
        The output path.
    """
    output_path = Path(output_path)
    xml_bytes = etree.tostring(
        tree,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=False,
    )

    with gzip.open(output_path, "wb") as f:
        f.write(xml_bytes)

    return output_path


def _compute_relative_path(from_dir: Path, to_file: Path) -> str:
    """Compute a relative path using ../ segments.

    Args:
        from_dir: The directory to start from.
        to_file: The file to reach.

    Returns:
        Relative path string like "../../other/dir/file.wav".
    """
    from_parts = from_dir.resolve().parts
    to_parts = to_file.resolve().parts

    # Find common prefix length
    common = 0
    for a, b in zip(from_parts, to_parts):
        if a != b:
            break
        common += 1

    if common == 0:
        raise ValueError(f"No common path between {from_dir} and {to_file}")

    ups = len(from_parts) - common
    remainder = to_parts[common:]

    segments = [".."] * ups + list(remainder)
    return "/".join(segments)
