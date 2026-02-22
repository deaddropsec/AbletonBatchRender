"""Tests for sample_resolver module."""

import json
from pathlib import Path

import pytest

from src.sample_resolver import (
    load_config,
    build_file_index,
    resolve_missing_samples,
    _pick_best_match,
)


class TestLoadConfig:
    def test_loads_valid_config(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "sample_search_paths": ["/some/path"]
        }))
        config = load_config(str(config_file))
        assert config["sample_search_paths"] == ["/some/path"]

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.json")

    def test_raises_on_missing_key(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text("{}")
        with pytest.raises(ValueError, match="sample_search_paths"):
            load_config(str(config_file))

    def test_raises_on_empty_list(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"sample_search_paths": []}))
        with pytest.raises(ValueError, match="non-empty"):
            load_config(str(config_file))


class TestBuildFileIndex:
    def test_indexes_files_by_name(self, tmp_path):
        (tmp_path / "kick.wav").touch()
        (tmp_path / "snare.wav").touch()
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "kick.wav").touch()

        index = build_file_index([str(tmp_path)])
        assert "kick.wav" in index
        assert len(index["kick.wav"]) == 2
        assert "snare.wav" in index
        assert len(index["snare.wav"]) == 1

    def test_skips_nonexistent_directory(self):
        index = build_file_index(["/nonexistent/path"])
        assert index == {}

    def test_case_insensitive_keys(self, tmp_path):
        (tmp_path / "Kick.WAV").touch()
        index = build_file_index([str(tmp_path)])
        assert "kick.wav" in index


class TestResolveMissingSamples:
    def test_resolves_by_filename(self, tmp_path):
        sample = tmp_path / "kick.wav"
        sample.write_bytes(b"audio data")

        missing = [{"path": "/old/kick.wav", "filename": "kick.wav", "file_size": 0, "crc": 0}]
        resolved = resolve_missing_samples(missing, [str(tmp_path)])
        assert "/old/kick.wav" in resolved
        assert resolved["/old/kick.wav"] == sample

    def test_returns_empty_for_unfound_samples(self, tmp_path):
        missing = [{"path": "/old/nope.wav", "filename": "nope.wav", "file_size": 0, "crc": 0}]
        resolved = resolve_missing_samples(missing, [str(tmp_path)])
        assert resolved == {}


class TestPickBestMatch:
    def test_picks_by_file_size(self, tmp_path):
        small = tmp_path / "small.wav"
        small.write_bytes(b"x" * 100)
        big = tmp_path / "big.wav"
        big.write_bytes(b"x" * 500)

        result = _pick_best_match([small, big], expected_size=500)
        assert result == big

    def test_falls_back_to_first_when_no_size(self, tmp_path):
        a = tmp_path / "a.wav"
        a.touch()
        b = tmp_path / "b.wav"
        b.touch()

        result = _pick_best_match([a, b], expected_size=0)
        assert result == a
