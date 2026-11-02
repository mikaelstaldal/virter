import argparse
import fcntl
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

v = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'virter'))


class CacheTests(unittest.TestCase):
    def test_creation_is_private_with_permissive_umask(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, XDG_CACHE_HOME=directory):
            previous = os.umask(0)
            try:
                cache = v['prepare_cache_dir']()
            finally:
                os.umask(previous)
            self.assertEqual(cache.stat().st_mode & 0o777, 0o700)

    def test_rejects_permissive_cache_without_chmod(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, XDG_CACHE_HOME=directory):
            cache = Path(directory) / 'virter'
            cache.mkdir(mode=0o755)
            with self.assertRaises(SystemExit):
                v['prepare_cache_dir']()
            self.assertEqual(cache.stat().st_mode & 0o777, 0o755)

    def test_rejects_symlink_and_writable_ancestor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'target'
            target.mkdir()
            link = root / 'link'
            link.symlink_to(target, target_is_directory=True)
            for parent in (link, target):
                if parent == target:
                    target.chmod(0o777)
                with patch.dict(os.environ, XDG_CACHE_HOME=str(parent)), self.assertRaises(SystemExit):
                    v['prepare_cache_dir']()
            self.assertFalse((target / 'virter').exists())

    def test_locks_allow_readers_and_exclude_writers(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            for exclusive in (False, True):
                with self.subTest(exclusive=exclusive), v['base_lock'](cache, 'base', exclusive):
                    fd = os.open(cache / 'base.lock', os.O_RDWR)
                    try:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        if exclusive:
                            with self.assertRaises(BlockingIOError):
                                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                        else:
                            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    finally:
                        os.close(fd)
            with v['base_lock'](cache, 'base', True):
                pass
            self.assertTrue((cache / 'base.lock').exists())

    def test_rejects_symlink_lock_and_hardlinked_base(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            target = cache / 'target'
            target.write_bytes(b'preserve')
            (cache / 'base.lock').symlink_to(target)
            with self.assertRaises(OSError):
                with v['base_lock'](cache, 'base', True):
                    self.fail('symlink accepted')
            (cache / 'base.img').hardlink_to(target)
            with self.assertRaises(SystemExit):
                v['base_image_path'](cache, 'base')
            self.assertEqual(target.read_bytes(), b'preserve')

    def test_rejects_foreign_cache_owner(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, XDG_CACHE_HOME=directory):
            v['prepare_cache_dir']()
            with patch('os.getuid', return_value=os.getuid() + 1), self.assertRaises(SystemExit):
                v['prepare_cache_dir']()

    def test_callers_hold_correct_lock_during_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            for function, worker, arguments, exclusive in (
                    ('run', '_run', (argparse.Namespace(base='base'),), False),
                    ('prepare_or_update', '_prepare_or_update', (None, 'base', 1024, None, []), True),
                    ('prepare_or_update', '_prepare_or_update', (cache / 'source', 'base', 1024, 8192, []), True)):
                def check(*args, **kwargs):
                    fd = os.open(cache / 'base.lock', os.O_RDWR)
                    try:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        if exclusive:
                            with self.assertRaises(BlockingIOError):
                                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                        else:
                            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    finally:
                        os.close(fd)
                with self.subTest(function=function, exclusive=exclusive), patch.dict(
                        v[function].__globals__, prepare_cache_dir=lambda: cache, **{worker: check}):
                    v[function](*arguments)
                with v['base_lock'](cache, 'base', True):
                    pass
