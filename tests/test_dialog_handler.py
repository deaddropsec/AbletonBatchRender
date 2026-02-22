"""Tests for dialog_handler module."""

from unittest.mock import MagicMock, patch

from src.dialog_handler import dismiss_blocking_dialog, poll_dialog_count


class TestDismissBlockingDialog:
    def _make_client(self, dialog_count=0, dialog_message=""):
        client = MagicMock()
        def get_property_side_effect(path):
            if path == "app.open_dialog_count":
                return str(dialog_count)
            if path == "app.current_dialog_message":
                return dialog_message
            return ""
        client.get_property.side_effect = get_property_side_effect
        return client

    @patch("src.dialog_handler.activate_ableton")
    @patch("src.dialog_handler.send_keystroke")
    @patch("src.dialog_handler.time")
    def test_returns_none_when_no_dialog(self, mock_time, mock_key, mock_activate):
        client = self._make_client(dialog_count=0)
        result = dismiss_blocking_dialog(client)
        assert result is None
        mock_key.assert_not_called()

    @patch("src.dialog_handler.activate_ableton")
    @patch("src.dialog_handler.send_keystroke")
    @patch("src.dialog_handler.time")
    def test_dismisses_save_dialog(self, mock_time, mock_key, mock_activate):
        client = self._make_client(dialog_count=1, dialog_message="Projekt sichern?")
        result = dismiss_blocking_dialog(client)
        assert result == "save"
        mock_key.assert_called_once_with("n")

    @patch("src.dialog_handler.activate_ableton")
    @patch("src.dialog_handler.send_enter")
    @patch("src.dialog_handler.time")
    def test_dismisses_sample_loading_dialog(self, mock_time, mock_enter, mock_activate):
        client = self._make_client(dialog_count=1, dialog_message="Samples werden dekodiert")
        result = dismiss_blocking_dialog(client)
        assert result == "sample_loading"
        mock_enter.assert_called_once()

    @patch("src.dialog_handler.activate_ableton")
    @patch("src.dialog_handler.send_enter")
    @patch("src.dialog_handler.time")
    def test_dismisses_unknown_dialog_with_enter(self, mock_time, mock_enter, mock_activate):
        client = self._make_client(dialog_count=1, dialog_message="Something unexpected")
        result = dismiss_blocking_dialog(client)
        assert result == "unknown"
        mock_enter.assert_called_once()

    def test_returns_none_on_connection_error(self):
        client = MagicMock()
        client.get_property.side_effect = OSError("connection lost")
        result = dismiss_blocking_dialog(client)
        assert result is None


class TestPollDialogCount:
    def test_returns_immediately_when_target_met(self):
        client = MagicMock()
        client.get_property.return_value = "2"
        result = poll_dialog_count(client, target=1, timeout=5.0)
        assert result == 2

    def test_returns_negative_on_persistent_error(self):
        client = MagicMock()
        client.get_property.side_effect = OSError("gone")
        result = poll_dialog_count(client, target=1, timeout=0.3)
        assert result == -1
