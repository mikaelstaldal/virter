import argparse
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
