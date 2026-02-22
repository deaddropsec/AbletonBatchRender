"""Tests for als_parser module."""

import gzip
import tempfile
from pathlib import Path

import pytest
from lxml import etree

from src.als_parser import (
    parse_als,
    get_project_length,
    get_transport_loop,
    extract_sample_paths,
)

# Path to real demo project for integration tests
DEMO_ALS = Path(__file__).parent.parent / "DemoProject" / "Demo.als"


# --- Fixtures ---

MINIMAL_ALS_XML = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0">
  <LiveSet>
    <Tracks>
      <AudioTrack Id="1">
        <DeviceChain>
          <MainSequencer>
            <Sample>
              <ArrangerAutomation>
                <Events>
                  <AudioClip Id="1">
                    <CurrentEnd Value="128.5" />
                  </AudioClip>
                  <AudioClip Id="2">
                    <CurrentEnd Value="256.0" />
                  </AudioClip>
                </Events>
              </ArrangerAutomation>
            </Sample>
          </MainSequencer>
        </DeviceChain>
      </AudioTrack>
      <MidiTrack Id="2">
        <DeviceChain>
          <MainSequencer>
            <ClipTimeable>
              <ArrangerAutomation>
                <Events>
                  <MidiClip Id="1">
                    <CurrentEnd Value="192.0" />
                  </MidiClip>
                </Events>
              </ArrangerAutomation>
            </ClipTimeable>
          </MainSequencer>
        </DeviceChain>
      </MidiTrack>
    </Tracks>
    <Transport>
      <LoopOn Value="false" />
      <LoopStart Value="0" />
      <LoopLength Value="100" />
    </Transport>
  </LiveSet>
</Ableton>
"""

EMPTY_TRACKS_XML = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0">
  <LiveSet>
    <Tracks>
      <AudioTrack Id="1">
        <DeviceChain>
          <MainSequencer>
            <Sample>
              <ArrangerAutomation>
                <Events />
              </ArrangerAutomation>
            </Sample>
          </MainSequencer>
        </DeviceChain>
      </AudioTrack>
    </Tracks>
    <Transport>
      <LoopOn Value="false" />
      <LoopStart Value="0" />
      <LoopLength Value="0" />
    </Transport>
  </LiveSet>
</Ableton>
"""

SAMPLE_REFS_XML = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0">
  <LiveSet>
    <Tracks />
    <Transport>
      <LoopOn Value="false" />
      <LoopStart Value="0" />
      <LoopLength Value="0" />
    </Transport>
    <SomeDevice>
      <FileRef>
        <Path Value="/Users/test/samples/kick.wav" />
      </FileRef>
      <FileRef>
        <Path Value="/Users/test/samples/snare.aif" />
      </FileRef>
      <FileRef>
        <Path Value="/Users/test/samples/kick.wav" />
      </FileRef>
      <FileRef>
        <Path Value="/Applications/Ableton/Devices/EQ Eight" />
      </FileRef>
      <FileRef>
        <Path Value="/Users/test/presets/MyPreset.adg" />
      </FileRef>
      <FileRef>
        <Path Value="" />
      </FileRef>
    </SomeDevice>
  </LiveSet>
</Ableton>
"""


def _make_als_fixture(xml_bytes: bytes) -> Path:
    """Create a temporary gzipped .als file from XML bytes."""
    tmp = tempfile.NamedTemporaryFile(suffix=".als", delete=False)
    with gzip.open(tmp.name, "wb") as f:
        f.write(xml_bytes)
    return Path(tmp.name)


# --- parse_als tests ---


class TestParseAls:
    def test_parses_valid_gzipped_als(self):
        path = _make_als_fixture(MINIMAL_ALS_XML)
        tree = parse_als(path)
        assert tree.getroot().tag == "Ableton"
        path.unlink()

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError):
            parse_als(Path("/nonexistent/file.als"))

    def test_raises_on_non_gzip_file(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".als", delete=False)
        tmp.write(b"not gzip data")
        tmp.close()
        with pytest.raises(Exception):  # gzip.BadGzipFile
            parse_als(Path(tmp.name))
        Path(tmp.name).unlink()


# --- get_project_length tests ---


class TestGetProjectLength:
    def test_returns_max_clip_end(self):
        path = _make_als_fixture(MINIMAL_ALS_XML)
        tree = parse_als(path)
        length = get_project_length(tree)
        # AudioTrack has clips ending at 128.5 and 256.0
        # MidiTrack has clip ending at 192.0
        # Max is 256.0
        assert length == 256.0
        path.unlink()

    def test_returns_zero_for_empty_tracks(self):
        path = _make_als_fixture(EMPTY_TRACKS_XML)
        tree = parse_als(path)
        length = get_project_length(tree)
        assert length == 0.0
        path.unlink()

    def test_returns_zero_when_no_tracks_element(self):
        xml = b'<?xml version="1.0"?><Ableton><LiveSet></LiveSet></Ableton>'
        path = _make_als_fixture(xml)
        tree = parse_als(path)
        length = get_project_length(tree)
        assert length == 0.0
        path.unlink()


# --- get_transport_loop tests ---


class TestGetTransportLoop:
    def test_reads_loop_settings(self):
        path = _make_als_fixture(MINIMAL_ALS_XML)
        tree = parse_als(path)
        loop = get_transport_loop(tree)
        assert loop["start"] == 0.0
        assert loop["length"] == 100.0
        assert loop["on"] is False
        path.unlink()

    def test_raises_when_no_transport(self):
        xml = b'<?xml version="1.0"?><Ableton><LiveSet></LiveSet></Ableton>'
        path = _make_als_fixture(xml)
        tree = parse_als(path)
        with pytest.raises(ValueError, match="Transport element not found"):
            get_transport_loop(tree)
        path.unlink()


# --- extract_sample_paths tests ---


class TestExtractSamplePaths:
    def test_extracts_audio_files_only(self):
        path = _make_als_fixture(SAMPLE_REFS_XML)
        tree = parse_als(path)
        samples = extract_sample_paths(tree)
        # Should find kick.wav and snare.aif (deduplicated)
        # Should NOT find EQ Eight (no extension) or MyPreset.adg
        assert len(samples) == 2
        assert Path("/Users/test/samples/kick.wav") in samples
        assert Path("/Users/test/samples/snare.aif") in samples
        path.unlink()

    def test_deduplicates_paths(self):
        path = _make_als_fixture(SAMPLE_REFS_XML)
        tree = parse_als(path)
        samples = extract_sample_paths(tree)
        # kick.wav appears twice in XML but should only be returned once
        wav_count = sum(1 for s in samples if s.name == "kick.wav")
        assert wav_count == 1
        path.unlink()


# --- Integration test with real .als file ---


@pytest.mark.skipif(not DEMO_ALS.exists(), reason="Demo.als not available")
class TestWithRealAlsFile:
    def test_parse_and_get_length(self):
        tree = parse_als(DEMO_ALS)
        length = get_project_length(tree)
        assert length > 0, "Demo project should have content"

    def test_transport_loop_readable(self):
        tree = parse_als(DEMO_ALS)
        loop = get_transport_loop(tree)
        assert "start" in loop
        assert "length" in loop
        assert "on" in loop

    def test_sample_paths_extracted(self):
        tree = parse_als(DEMO_ALS)
        samples = extract_sample_paths(tree)
        assert len(samples) > 0, "Demo project should reference samples"
        # All should be audio files
        for sample in samples:
            assert sample.suffix.lower() in {
                ".wav", ".aif", ".aiff", ".mp3", ".flac",
                ".ogg", ".m4a", ".aac", ".wma",
            }
