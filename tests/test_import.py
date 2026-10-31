import argparse
import contextlib
import hashlib
import io
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


v = runpy.run_path(str(Path(__file__).resolve().parents[1] / "virter"))


def image_header(version=3, backing=0, features=0):
    header = bytearray(104 if version == 3 else 72)
    header[:4] = b"QFI\xfb"
    header[4:8] = version.to_bytes(4, "big")
    header[8:16] = backing.to_bytes(8, "big")
    if version == 3:
        header[72:80] = features.to_bytes(8, "big")
        header[100:104] = (104).to_bytes(4, "big")
    return bytes(header)


class ImportTests(unittest.TestCase):
    def test_cli_requires_valid_digest(self):
        for extra in ([], ["--sha256", "bad"], ["--sha256", "z" * 64]):
            with self.subTest(extra=extra), patch("sys.argv", ["virter", "prepare", "-i", "image", *extra]), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                v["main"]()
            self.assertEqual(error.exception.code, 2)
        self.assertEqual(v["sha256_digest"]("AB" * 32), "ab" * 32)

    def test_rejected_import_never_calls_qemu_and_removes_copy(self):
        for data, digest in ((image_header(), "0" * 64), (b"not qcow2", None),
                             (image_header(backing=104), None), (image_header(features=4), None),
                             (image_header(features=1 << 63), None), (image_header()[:80], None),
                             (image_header(version=2, backing=72), None)):
            with self.subTest(data=data, digest=digest), tempfile.TemporaryDirectory() as directory:
                cache = Path(directory)
                source = cache / "source.img"
                source.write_bytes(data)
                digest = digest or hashlib.sha256(data).hexdigest()
                with patch.dict(v["prepare_or_update"].__globals__, prepare_cache_dir=lambda: cache), \
                        patch("subprocess.run") as command, self.assertRaises(SystemExit):
                    v["prepare_or_update"](source, "base", 1024, 8192, [], digest)
                command.assert_not_called()
                self.assertFalse((cache / "base.img").exists())
                self.assertEqual(source.read_bytes(), data)

    def test_missing_source_leaves_no_base(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            with patch.dict(v["prepare_or_update"].__globals__, prepare_cache_dir=lambda: cache), \
                    patch("subprocess.run") as command, self.assertRaises(FileNotFoundError):
                v["prepare_or_update"](cache / "missing.img", "base", 1024, 8192, [], "0" * 64)
            command.assert_not_called()
            self.assertFalse((cache / "base.img").exists())

    def test_verified_standalone_import_pins_resize_format(self):
        for version in (2, 3):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                cache = Path(directory)
                source = cache / "source.img"
                data = image_header(version=version)
                source.write_bytes(data)
                with patch.dict(v["prepare_or_update"].__globals__, prepare_cache_dir=lambda: cache,
                                cloud_init_prepare=lambda *a: None, run_vm=lambda *a, **k: None), \
                        patch("subprocess.run") as command:
                    v["prepare_or_update"](source, "base", 1024, 8192, [], hashlib.sha256(data).hexdigest())
                command.assert_called_once_with(
                    ["qemu-img", "resize", "-f", "qcow2", "-q", str(cache / "base.img"), "8192M"], check=True)
                self.assertEqual((cache / "base.img").read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
