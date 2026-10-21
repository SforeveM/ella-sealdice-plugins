from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from autocard.service import AutocardServer, Handler, disable_windows_console_quick_edit


class _ResettingWriter:
    def write(self, _payload: bytes) -> None:
        raise ConnectionResetError(10054, "client closed")


class ServiceResilienceTests(unittest.TestCase):
    def test_quick_edit_guard_never_raises(self) -> None:
        self.assertIsInstance(disable_windows_console_quick_edit(), bool)

    def test_access_log_is_disabled_by_default(self) -> None:
        previous_data = os.environ.get("AUTOCARD_DATA_DIR")
        previous_log = os.environ.pop("AUTOCARD_ACCESS_LOG", None)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.environ["AUTOCARD_DATA_DIR"] = str(Path(temp_dir) / "pending")
                server = AutocardServer(("127.0.0.1", 0), Handler)
                try:
                    self.assertFalse(server.access_log)
                    self.assertTrue(server.daemon_threads)
                finally:
                    server.server_close()
        finally:
            if previous_data is None:
                os.environ.pop("AUTOCARD_DATA_DIR", None)
            else:
                os.environ["AUTOCARD_DATA_DIR"] = previous_data
            if previous_log is not None:
                os.environ["AUTOCARD_ACCESS_LOG"] = previous_log

    def test_json_response_ignores_client_reset(self) -> None:
        handler = object.__new__(Handler)
        handler.close_connection = False
        handler.wfile = _ResettingWriter()
        handler.send_response = lambda _status: None
        handler.send_header = lambda _name, _value: None
        handler.end_headers = lambda: None
        handler._json(200, {"ok": True})
        self.assertTrue(handler.close_connection)

    def test_json_payload_is_still_valid_before_write(self) -> None:
        captured: list[bytes] = []

        class Writer:
            def write(self, payload: bytes) -> None:
                captured.append(payload)

        handler = object.__new__(Handler)
        handler.close_connection = False
        handler.wfile = Writer()
        handler.send_response = lambda _status: None
        handler.send_header = lambda _name, _value: None
        handler.end_headers = lambda: None
        handler._json(200, {"ok": True, "message": "正常"})
        self.assertEqual(json.loads(captured[0].decode("utf-8"))["message"], "正常")


if __name__ == "__main__":
    unittest.main()
