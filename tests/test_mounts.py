import argparse
import contextlib
import io
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch


v = runpy.run_path(str(Path(__file__).resolve().parents[1] / "virter"))


def mounts(readonly=(), writable=(), current_dir=False, current_dir_writable=False):
    return v["collect_mounts"](argparse.Namespace(
        mount=list(readonly), mount_writable=list(writable), current_dir=current_dir,
        current_dir_writable=current_dir_writable))


class MountSafetyTests(unittest.TestCase):
    def setUp(self):
        runtime = tempfile.TemporaryDirectory()
        self.addCleanup(runtime.cleanup)
        self.runtime = Path(runtime.name)
        runtime_patch = patch.dict(v['main'].__globals__, runtime_directory=lambda: self.runtime)
        runtime_patch.start()
        self.addCleanup(runtime_patch.stop)

    def test_runtime_is_protected_in_both_modes_and_through_aliases(self):
        alias = self.runtime.parent / (self.runtime.name + '-alias')
        alias.symlink_to(self.runtime, target_is_directory=True)
        self.addCleanup(alias.unlink)
        child = self.runtime / 'other-invocation'
        child.mkdir()
        for path in (self.runtime.parent, self.runtime, child, alias):
            for readonly in (True, False):
                with self.subTest(path=path, readonly=readonly), self.assertRaisesRegex(SystemExit, "Refusing"):
                    mounts([path] if readonly else [], [] if readonly else [path])

    def test_allowed_mounts_do_not_print_warnings(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            inputs = parent / "inputs"
            inputs.mkdir()
            output_dir = parent / "output"
            output_dir.mkdir()
            for writable, current in ((True, False), (False, True), (False, False)):
                args = argparse.Namespace(
                    name="instance", base="base", memory=1024, network="none", allow_sudo=False,
                    mount=[] if current else [inputs],
                    mount_writable=[output_dir] if writable else [],
                    current_dir=False, current_dir_writable=current)
                output = io.StringIO()
                with self.subTest(writable=writable, current=current), \
                        patch.dict(v["run"].__globals__, prepare_cache_dir=unittest.mock.Mock(
                            side_effect=SystemExit("stop before image access"))), \
                        contextlib.redirect_stderr(output), self.assertRaisesRegex(SystemExit, "stop before"):
                    v["run"](args)
                self.assertEqual(output.getvalue(), "")

    def test_home_and_cache_mount_restrictions_include_current_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            home = parent / "home" / "user"
            home.mkdir(parents=True)
            cache_home = parent / "cache"
            cache = cache_home / "virter"
            instance = cache / "instance"
            instance.mkdir(parents=True)
            alias = parent / "alias"
            alias.symlink_to(cache, target_is_directory=True)
            with patch("pathlib.Path.home", return_value=home), \
                    patch.dict("os.environ", XDG_CACHE_HOME=str(cache_home)):
                for path in (Path("/"), parent, home.parent, home, cache_home, cache, instance, alias):
                    with self.subTest(path=path):
                        with self.assertRaisesRegex(SystemExit, "Refusing .*mount"):
                            mounts(writable=[path])
                        with patch("os.getcwd", return_value=str(path.resolve())), \
                                self.assertRaisesRegex(SystemExit, "Refusing .*mount"):
                            mounts(current_dir_writable=True)
                        if home.is_relative_to(path.resolve()):
                            with self.assertRaisesRegex(SystemExit, "exposes the home directory"):
                                mounts([path])
                            with patch("os.getcwd", return_value=str(path.resolve())), \
                                    self.assertRaisesRegex(SystemExit, "exposes the home directory"):
                                mounts(current_dir=True)
                        else:
                            with self.assertRaisesRegex(SystemExit, "exposes the virter cache"):
                                mounts([path])
                            with patch("os.getcwd", return_value=str(path.resolve())), \
                                    self.assertRaisesRegex(SystemExit, "exposes the virter cache"):
                                mounts(current_dir=True)
                work = home / "work"
                work.mkdir()
                self.assertEqual(mounts(writable=[work]), [(work, False)])
                self.assertEqual(mounts([work]), [(work, True)])
                with patch("os.getcwd", return_value=str(work)):
                    self.assertEqual(mounts(current_dir_writable=True), [(work, False)])
                    self.assertEqual(mounts(current_dir=True), [(work, True)])

    def test_default_cache_and_symlinked_home_are_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            home = parent / "home"
            cache = home / ".cache" / "virter"
            cache.mkdir(parents=True)
            alias = parent / "alias"
            alias.symlink_to(home, target_is_directory=True)
            with patch("pathlib.Path.home", return_value=alias), patch.dict("os.environ", {}, clear=True):
                for path in (home, alias, cache):
                    with self.subTest(path=path), self.assertRaisesRegex(SystemExit, "Refusing .*mount"):
                        mounts(writable=[path])
                for path in (home, alias):
                    with self.subTest(readonly=path), self.assertRaisesRegex(SystemExit, "exposes the home directory"):
                        mounts([path])

    def test_conflicting_nested_exports_are_rejected_in_both_orders(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            child = parent / "secrets"
            child.mkdir()
            for readonly, writable in ((child, parent), (parent, child)):
                with self.subTest(readonly=readonly), self.assertRaisesRegex(SystemExit, "conflicting mount"):
                    mounts([readonly], [writable])

    def test_resolved_symlink_alias_cannot_bypass_conflict_check(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            child = parent / "secrets"
            child.mkdir()
            alias = parent / "alias"
            alias.symlink_to(child, target_is_directory=True)
            with self.assertRaisesRegex(SystemExit, "conflicting mount"):
                mounts([alias], [parent])

    def test_current_directory_export_is_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            child = parent / "secrets"
            child.mkdir()
            with patch("os.getcwd", return_value=str(parent)):
                with self.assertRaisesRegex(SystemExit, "conflicting mount"):
                    mounts([child], current_dir_writable=True)
                with self.assertRaisesRegex(SystemExit, "conflicting mount"):
                    mounts(writable=[child], current_dir=True)

    def test_same_mode_nesting_and_disjoint_mixed_modes_are_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            child = parent / "child"
            sibling = parent / "child-other"
            child.mkdir()
            sibling.mkdir()
            self.assertEqual(mounts([child, parent]), [(parent, True), (child, True)])
            self.assertEqual(mounts(writable=[child, parent]), [(parent, False), (child, False)])
            self.assertEqual(dict(mounts([child], [sibling])), {child: True, sibling: False})
