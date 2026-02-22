"""Tests for keystroke module."""

from unittest.mock import patch

from src.keystroke import send_keystroke, send_enter


class TestSendKeystroke:
    @patch("src.keystroke.run_jxa")
    def test_character_keystroke(self, mock_jxa):
        mock_jxa.return_value = {"success": True, "result": "ok", "error": None}
        result = send_keystroke("r")
        assert result is True
        script = mock_jxa.call_args[0][0]
        assert 'se.keystroke("r")' in script

    @patch("src.keystroke.run_jxa")
    def test_keystroke_with_modifiers(self, mock_jxa):
        mock_jxa.return_value = {"success": True, "result": "ok", "error": None}
        result = send_keystroke("r", '"command down", "shift down"')
        assert result is True
        script = mock_jxa.call_args[0][0]
        assert 'se.keystroke("r", {using:' in script
        assert '"command down", "shift down"' in script

    @patch("src.keystroke.run_jxa")
    def test_keycode_keystroke(self, mock_jxa):
        mock_jxa.return_value = {"success": True, "result": "ok", "error": None}
        result = send_keystroke("36")
        assert result is True
        script = mock_jxa.call_args[0][0]
        assert "se.keyCode(36)" in script

    @patch("src.keystroke.run_jxa")
    def test_returns_false_on_failure(self, mock_jxa):
        mock_jxa.return_value = {"success": False, "result": None, "error": "timeout"}
        result = send_keystroke("r")
        assert result is False


class TestSendEnter:
    @patch("src.keystroke.run_jxa")
    def test_sends_keycode_36(self, mock_jxa):
        mock_jxa.return_value = {"success": True, "result": "ok", "error": None}
        result = send_enter()
        assert result is True
        script = mock_jxa.call_args[0][0]
        assert "keyCode(36)" in script
