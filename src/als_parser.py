"""Parse Ableton Live Set (.als) files.

.als files are gzip-compressed XML. This module handles decompression,
parsing, and extraction of project metadata like track lengths and
sample references.
"""

import gzip
from copy import deepcopy
from pathlib import Path

from lxml import etree


# XPaths for clip end positions (determines actual content length)
MIDI_CLIP_ENDS = (
    "DeviceChain/MainSequencer/ClipTimeable/"
    "ArrangerAutomation/Events//MidiClip/CurrentEnd"
)
AUDIO_CLIP_ENDS = (
    "DeviceChain/MainSequencer/Sample/"
    "ArrangerAutomation/Events//AudioClip/CurrentEnd"
)

# Audio file extensions we consider as sample references
AUDIO_EXTENSIONS = frozenset({
    ".wav", ".aif", ".aiff", ".mp3", ".flac",
    ".ogg", ".m4a", ".aac", ".wma",
})


def parse_als(path: Path) -> etree._ElementTree:
    """Decompress and parse an .als file into an XML tree.

    Args:
        path: Path to the .als file.

    Returns:
        Parsed XML ElementTree.

    Raises:
        FileNotFoundError: If the .als file doesn't exist.
        gzip.BadGzipFile: If the file is not valid gzip.
        etree.XMLSyntaxError: If the decompressed content is not valid XML.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    parser = etree.XMLParser(huge_tree=True)
    with gzip.open(path, "rb") as f:
        return etree.parse(f, parser)


def get_project_length(tree: etree._ElementTree) -> float:
    """Calculate the actual content length of a project.

    Traverses all audio and MIDI tracks, finding the maximum
    CurrentEnd value across all clips. This represents the true
    end of content in the arrangement.

    Args:
        tree: Parsed .als XML tree.

    Returns:
        The furthest clip end position in beats. Returns 0.0 if
        no clips are found.
    """
    root = tree.getroot()
    tracks = root.find(".//Tracks")
    if tracks is None:
        return 0.0

    max_end = 0.0

    for track in tracks:
        clip_ends = _get_clip_ends(track)
        for end_value in clip_ends:
            if end_value > max_end:
                max_end = end_value

    return max_end


def get_transport_loop(tree: etree._ElementTree) -> dict:
    """Read the current transport loop settings.

    Args:
        tree: Parsed .als XML tree.

    Returns:
        Dict with 'start', 'length', and 'on' keys.

    Raises:
        ValueError: If Transport element is not found.
    """
    root = tree.getroot()
    transport = root.find(".//Transport")
    if transport is None:
        raise ValueError("Transport element not found in .als file")

    loop_start = transport.find("LoopStart")
    loop_length = transport.find("LoopLength")
    loop_on = transport.find("LoopOn")

    return {
        "start": float(loop_start.get("Value", "0")) if loop_start is not None else 0.0,
        "length": float(loop_length.get("Value", "0")) if loop_length is not None else 0.0,
        "on": loop_on.get("Value", "false") == "true" if loop_on is not None else False,
    }


def extract_sample_paths(tree: etree._ElementTree) -> list[Path]:
    """Extract audio sample file paths from the project.

    Filters out Ableton built-in device/preset references and only
    returns paths to actual audio sample files.

    Args:
        tree: Parsed .als XML tree.

    Returns:
        List of unique absolute Paths to audio samples.
    """
    root = tree.getroot()
    seen = set()
    paths = []

    for fileref in root.iter("FileRef"):
        path_elem = fileref.find("Path")
        if path_elem is None:
            continue

        path_str = path_elem.get("Value", "")
        if not path_str:
            continue

        file_path = Path(path_str)

        # Only include actual audio files, not devices/presets
        if file_path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue

        if path_str not in seen:
            seen.add(path_str)
            paths.append(file_path)

    return paths


def extract_sample_refs(
    tree: etree._ElementTree, als_path: Path | None = None,
) -> list[dict]:
    """Extract full FileRef metadata for audio samples.

    Handles two Ableton FileRef formats:
      - Modern: <Path Value="/absolute/path.wav"/>
      - Legacy: <Name Value="file.wav"/> + <RelativePath> with
        <RelativePathElement Dir="..."/> children (common in projects
        created on Windows or older Ableton versions).

    Args:
        tree: Parsed .als XML tree.
        als_path: Path to the .als file. Required to resolve legacy
            relative paths. If None, legacy refs are resolved best-effort.

    Returns:
        List of dicts with keys: path (str), filename (str),
        file_size (int), crc (int). Deduplicated by path.
    """
    project_dir = als_path.resolve().parent if als_path else None
    root = tree.getroot()
    seen = set()
    refs = []

    for fileref in root.iter("FileRef"):
        ref = _parse_fileref(fileref, project_dir)
        if ref is None:
            continue

        if ref["path"] in seen:
            continue
        seen.add(ref["path"])
        refs.append(ref)

    return refs


def _parse_fileref(fileref, project_dir: Path | None) -> dict | None:
    """Parse a single FileRef element into a sample ref dict.

    Returns None if the FileRef is not an audio sample.
    """
    # Try modern format first: <Path Value="..."/>
    path_elem = fileref.find("Path")
    if path_elem is not None:
        path_str = path_elem.get("Value", "")
        if path_str:
            file_path = Path(path_str)
            if file_path.suffix.lower() not in AUDIO_EXTENSIONS:
                return None

            size_elem = fileref.find("OriginalFileSize")
            crc_elem = fileref.find("OriginalCrc")
            return {
                "path": path_str,
                "filename": file_path.name,
                "file_size": int(size_elem.get("Value", "0")) if size_elem is not None else 0,
                "crc": int(crc_elem.get("Value", "0")) if crc_elem is not None else 0,
            }

    # Legacy format: <Name> + <RelativePath> with RelativePathElement children
    name_elem = fileref.find("Name")
    if name_elem is None:
        return None

    filename = name_elem.get("Value", "")
    if not filename:
        return None

    if Path(filename).suffix.lower() not in AUDIO_EXTENSIONS:
        return None

    # Skip folder refs
    refers_to_folder = fileref.find("RefersToFolder")
    if refers_to_folder is not None and refers_to_folder.get("Value") == "true":
        return None

    # Build path from RelativePathElement children
    resolved_path = _resolve_legacy_path(fileref, filename, project_dir)

    # Get file size / crc from SearchHint
    search_hint = fileref.find("SearchHint")
    file_size = 0
    crc = 0
    if search_hint is not None:
        size_elem = search_hint.find("FileSize")
        crc_elem = search_hint.find("Crc")
        if size_elem is not None:
            file_size = int(size_elem.get("Value", "0"))
        if crc_elem is not None:
            crc = int(crc_elem.get("Value", "0"))

    return {
        "path": resolved_path,
        "filename": filename,
        "file_size": file_size,
        "crc": crc,
    }


def _resolve_legacy_path(
    fileref, filename: str, project_dir: Path | None,
) -> str:
    """Resolve a legacy FileRef to an absolute path string.

    Tries RelativePath elements relative to the project directory.
    Falls back to just the filename if resolution fails.
    """
    rel_path_elem = fileref.find("RelativePath")

    if rel_path_elem is not None and project_dir is not None:
        segments = [
            elem.get("Dir", "")
            for elem in rel_path_elem.findall("RelativePathElement")
            if elem.get("Dir", "")
        ]
        if segments:
            resolved = project_dir / Path(*segments) / filename
            return str(resolved)

    # Fallback: just filename (will be treated as missing → search)
    return filename


def _get_clip_ends(track: etree._Element) -> list[float]:
    """Extract all clip CurrentEnd values from a track element."""
    ends = []

    if track.tag == "MidiTrack":
        xpath = MIDI_CLIP_ENDS
    elif track.tag == "AudioTrack":
        xpath = AUDIO_CLIP_ENDS
    else:
        return ends

    for elem in track.findall(xpath):
        try:
            ends.append(float(elem.get("Value", "0")))
        except (ValueError, TypeError):
            continue

    return ends
