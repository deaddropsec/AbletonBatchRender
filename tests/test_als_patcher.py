"""Tests for als_patcher module."""

import gzip
import tempfile
from pathlib import Path

from lxml import etree

from src.als_patcher import patch_sample_paths, write_als, _compute_relative_path


PATCHER_XML = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0">
  <LiveSet>
    <SomeDevice>
      <FileRef>
        <Path Value="/old/path/kick.wav" />
        <RelativePath Value="../../old/path/kick.wav" />
      </FileRef>
      <FileRef>
        <Path Value="/old/path/snare.wav" />
        <RelativePath Value="../../old/path/snare.wav" />
      </FileRef>
      <FileRef>
        <Path Value="/unchanged/hat.wav" />
      </FileRef>
    </SomeDevice>
  </LiveSet>
</Ableton>
"""


def _parse_xml(xml_bytes: bytes) -> etree._ElementTree:
    return etree.ElementTree(etree.fromstring(xml_bytes))


class TestPatchSamplePaths:
    def test_updates_matching_paths(self):
        tree = _parse_xml(PATCHER_XML)
        path_map = {
            "/old/path/kick.wav": Path("/new/lib/kick.wav"),
        }
        patched = patch_sample_paths(tree, path_map)
        root = patched.getroot()
        paths = [
            fr.find("Path").get("Value")
            for fr in root.iter("FileRef")
            if fr.find("Path") is not None
        ]
        assert "/new/lib/kick.wav" in paths
        assert "/old/path/snare.wav" in paths
        assert "/unchanged/hat.wav" in paths

    def test_does_not_mutate_original(self):
        tree = _parse_xml(PATCHER_XML)
        original_paths = [
            fr.find("Path").get("Value")
            for fr in tree.getroot().iter("FileRef")
            if fr.find("Path") is not None
        ]
        path_map = {"/old/path/kick.wav": Path("/new/lib/kick.wav")}
        patch_sample_paths(tree, path_map)

        after_paths = [
            fr.find("Path").get("Value")
            for fr in tree.getroot().iter("FileRef")
            if fr.find("Path") is not None
        ]
        assert original_paths == after_paths

    def test_empty_path_map_returns_copy(self):
        tree = _parse_xml(PATCHER_XML)
        patched = patch_sample_paths(tree, {})
        assert patched is not tree
        assert patched.getroot() is not tree.getroot()


class TestWriteAls:
    def test_round_trip(self):
        tree = _parse_xml(PATCHER_XML)
        tmp = tempfile.NamedTemporaryFile(suffix=".als", delete=False)
        tmp.close()
        output_path = Path(tmp.name)

        try:
            result = write_als(tree, output_path)
            assert result == output_path
            assert output_path.exists()

            with gzip.open(output_path, "rb") as f:
                data = f.read()
            roundtrip = etree.fromstring(data)
            assert roundtrip.tag == "Ableton"
        finally:
            output_path.unlink()


class TestComputeRelativePath:
    def test_simple_relative(self):
        result = _compute_relative_path(
            Path("/a/b/c"),
            Path("/a/b/d/file.wav"),
        )
        assert result == "../d/file.wav"

    def test_same_directory(self):
        result = _compute_relative_path(
            Path("/a/b"),
            Path("/a/b/file.wav"),
        )
        assert result == "file.wav"

    def test_deeply_nested(self):
        result = _compute_relative_path(
            Path("/a/b/c/d"),
            Path("/a/x/y/file.wav"),
        )
        assert result == "../../../x/y/file.wav"
