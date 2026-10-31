import argparse
import contextlib
import io
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


v = runpy.run_path(str(Path(__file__).resolve().parents[1] / "virter"))


class NameSafetyTests(unittest.TestCase):
    def test_names(self):
        for name in ("base", "instance-123", "A", "a" * 63):
            self.assertEqual(v["logical_name"](name), name)
        for name in ("", "/tmp/x", "../x", "a/b", "a,b", "a\nhostname: x", "é", "-x", "x-", "a" * 64):
            with self.subTest(name=name), self.assertRaises(argparse.ArgumentTypeError):
                v["logical_name"](name)

    def test_all_cli_name_options_reject_traversal(self):
        for arguments in (["prepare", "-i", "missing", "-b", "../x"],
                          ["update", "-b", "../x"], ["run", "-b", "../x"], ["run", "-n", "../x"]):
            with self.subTest(arguments=arguments), patch("sys.argv", ["virter", *arguments]), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                v["main"]()
            self.assertEqual(error.exception.code, 2)

    def test_base_paths_reject_symlinks_and_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            cache.mkdir()
            (cache / "base.img").symlink_to(Path(directory) / "missing")
            for name in ("base", "../outside"):
                with self.subTest(name=name), self.assertRaises(SystemExit):
                    v["base_image_path"](cache, name)

    def test_prepare_preserves_existing_base(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            base = cache / "base.img"
            base.write_bytes(b"existing")
            source = cache / "source.img"
            source.write_bytes(b"new")
            with patch.dict(v["prepare_or_update"].__globals__, prepare_cache_dir=lambda: cache), \
                    patch("subprocess.run") as command, self.assertRaises(SystemExit):
                v["prepare_or_update"](source, "base", 1024, 8192, [])
            self.assertEqual(base.read_bytes(), b"existing")
            command.assert_not_called()

    def test_qemu_paths_escape_commas_and_omit_pidfile(self):
        with patch("subprocess.run") as command:
            v["run_vm"]("safe", "uuid", Path("/cache,a/disk.img"), Path("/tmp,b"),
                        1024, v["NetworkMode"].HOST, False, [], True)
        arguments = command.call_args.args[0]
        self.assertNotIn("-pidfile", arguments)
        self.assertIn("file=/cache,,a/disk.img,if=virtio,index=0,format=qcow2,media=disk,cache=unsafe", arguments)
        self.assertIn("file=/tmp,,b/seed.img,index=1,media=cdrom", arguments)

    def test_run_isolates_image_and_preserves_name_derived_files(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            for filename in ("base.img", "instance.img", "instance.pid"):
                (cache / filename).write_bytes(b"preserve")
            args = argparse.Namespace(name="instance", base="base", memory=1024, network="none",
                                      mount=[], mount_writable=[], current_dir=False, current_dir_writable=False,
                                      workdir=None, COMMAND=None)
            globals_ = v["run"].__globals__
            with patch.dict(globals_, prepare_cache_dir=lambda: cache, generate_cloud_init=lambda *a, **k: None,
                            run_vm=lambda *a, **k: None), patch("subprocess.run") as command:
                v["run"](args)
            image = Path(command.call_args.args[0][-1])
            self.assertEqual(image.name, "disk.img")
            self.assertEqual(image.parent.parent, cache)
            self.assertFalse(image.parent.exists())
            for filename in ("base.img", "instance.img", "instance.pid"):
                self.assertEqual((cache / filename).read_bytes(), b"preserve")


if __name__ == "__main__":
    unittest.main()
