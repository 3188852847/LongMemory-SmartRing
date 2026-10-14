"""标准库合成测试；不读真实 Otto 素材、个人配置或日用端口。"""
import base64
import importlib.util
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[3]
TEMP_ROOT = ROOT / "data/test-tmp/otto-preview"
spec = importlib.util.spec_from_file_location("otto_preview", ROOT / "scripts/development/otto_preview/serve.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    def test_import_is_from_this_worktree(self):
        self.assertEqual(Path(preview.__file__).resolve().parents[3], ROOT)

    def test_manifest_fixed_set_and_budget(self):
        self.assertEqual(len(preview.NAMES), 21)
        self.assertEqual(sum(preview.RECORDS[f"gifs/{n}.gif"]["bytes"] for n in preview.NAMES), 1609459)

    def test_missing_unknown_and_corrupt_resources(self):
        with tempfile.TemporaryDirectory(prefix="unit-", dir=TEMP_ROOT) as directory:
            root = Path(directory)
            self.assertEqual(preview.inventory(root)["valid_count"], 0)
            with self.assertRaises(ValueError):
                preview.asset_bytes(root, "../../outside")
            (root / "gifs").mkdir()
            (root / "gifs/neutral.gif").write_bytes(b"broken GIF")
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                preview.asset_bytes(root, "neutral")

    def test_gif_structure_and_truncation(self):
        # Synthetic 1px GIF header resized solely to exercise structure parsing.
        # It is never shown as Otto or treated as actual pixel decode evidence.
        data = bytearray(base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"))
        data[6:10] = b"\xf0\x00\xf0\x00"
        self.assertEqual(preview.gif_info(data)["frames"], 1)
        for cut in (0, 10, len(data)-1):
            with self.assertRaises(ValueError):
                preview.gif_info(data[:cut])

    def test_http_allowlist_and_write_rejection(self):
        with tempfile.TemporaryDirectory(prefix="http-", dir=TEMP_ROOT) as directory:
            server = preview.ThreadingHTTPServer(("127.0.0.1", 0), preview.make_handler(Path(directory)))
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                origin = f"http://127.0.0.1:{server.server_port}"
                with urlopen(origin + "/api/assets") as response:
                    self.assertIn(b'"valid_count": 0', response.read())
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                with urlopen(origin + "/") as response:
                    self.assertIn(b"Otto", response.read())
                for path in ("/../AGENTS.md", "/upstream.zip", "/gifs/../../LICENSE.gif", "/gifs/neutral.gif"):
                    with self.assertRaises(HTTPError) as failure:
                        urlopen(origin + path)
                    self.assertEqual(failure.exception.code, 404)
                from urllib.request import Request
                with self.assertRaises(HTTPError) as failure:
                    urlopen(Request(origin + "/api/assets", data=b"x", method="POST"))
                self.assertEqual(failure.exception.code, 501)
            finally:
                server.shutdown(); server.server_close(); worker.join()


if __name__ == "__main__":
    unittest.main()
