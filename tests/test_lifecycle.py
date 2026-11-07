import argparse
from contextlib import nullcontext
import runpy
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

v = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'virter'))


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        runtime = tempfile.TemporaryDirectory()
        self.addCleanup(runtime.cleanup)
        self.runtime = Path(runtime.name)
        runtime_patch = patch.dict(v['main'].__globals__, runtime_directory=lambda: self.runtime)
        runtime_patch.start()
        self.addCleanup(runtime_patch.stop)
        patcher = patch.dict(v["run_vm"].__globals__, relay_output=lambda stream: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_shutdown_escalates_and_reaps_all_children(self):
        first, second = Mock(), Mock()
        first.poll.return_value = second.poll.return_value = None
        second.wait.side_effect = [subprocess.TimeoutExpired('child', 5), 0]
        with patch('subprocess.Popen', side_effect=[first, second]):
            with v['vm_children']() as start:
                start(['first'])
                start(['second'])
        first.terminate.assert_called_once()
        second.terminate.assert_called_once()
        second.kill.assert_called_once()
        self.assertEqual(second.wait.call_count, 2)
        first.wait.assert_called_once_with(timeout=5)

    def test_start_failure_reaps_existing_child(self):
        child = Mock()
        child.poll.return_value = None
        with patch('subprocess.Popen', side_effect=[child, OSError('startup failed')]):
            with self.assertRaises(OSError):
                with v['vm_children']() as start:
                    start(['first'])
                    start(['second'])
        child.terminate.assert_called_once()
        child.wait.assert_called_once_with(timeout=5)

    def test_signal_during_spawn_registers_child_before_cancellation(self):
        child = Mock()
        child.poll.return_value = None
        previous = signal.getsignal(signal.SIGTERM)

        def spawn(command):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            return child

        with patch('subprocess.Popen', side_effect=spawn):
            with self.assertRaises(SystemExit) as error:
                with v['vm_children']() as start:
                    start(['child'])
        self.assertEqual(error.exception.code, 128 + signal.SIGTERM)
        child.terminate.assert_called_once()
        child.wait.assert_called_once_with(timeout=5)
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def test_cleanup_error_still_reaps_other_children(self):
        first, second = Mock(), Mock()
        first.poll.return_value = second.poll.return_value = None
        second.wait.side_effect = OSError('cannot wait')
        with patch('subprocess.Popen', side_effect=[first, second]):
            with self.assertRaises(v['ChildCleanupError']):
                with v['vm_children']() as start:
                    start(['first'])
                    start(['second'])
        first.wait.assert_called_once_with(timeout=5)

    def test_unreaped_child_has_bounded_wait_and_retains_files(self):
        child = Mock()
        child.poll.return_value = None
        child.wait.side_effect = subprocess.TimeoutExpired('child', 5)
        with patch('subprocess.Popen', return_value=child):
            with self.assertRaises(v['ChildCleanupError']):
                with v['vm_children']() as start:
                    start(['child'])
        child.kill.assert_called_once()
        self.assertEqual(child.wait.call_count, 2)
        child.wait.assert_called_with(timeout=5)

    def test_callers_retain_resources_if_reaping_fails(self):
        args = argparse.Namespace(name='instance', base='base', memory=1024, network='none', allow_sudo=False,
                                  mount=[], mount_writable=[], current_dir=False, current_dir_writable=False,
                                  workdir=None, COMMAND=None)
        for function, arguments in ((v['run'], (args,)),
                                    (v['prepare_or_update'], (None, 'base', 1024, None, []))):
            with self.subTest(function=function.__name__), \
                    patch.dict(function.__globals__, prepare_cache_dir=lambda: Path('/cache'),
                               base_lock=lambda *a, **k: nullcontext(),
                               generate_cloud_init=Mock(), cloud_init_update=Mock(), validate_disk_size=Mock(),
                               run_vm=Mock(side_effect=v['ChildCleanupError']('unreaped'))), \
                    patch('pathlib.Path.is_file', return_value=True), \
                    patch('tempfile.mkdtemp', side_effect=['/runtime/seed', '/cache/disk']), \
                    patch('subprocess.run'), patch('shutil.rmtree') as remove:
                with self.assertRaises(v['ChildCleanupError']):
                    function(*arguments)
                remove.assert_not_called()

    def test_signal_during_qemu_wait_reaps_vm_and_daemon_and_resets_terminal(self):
        daemon, qemu = Mock(), Mock()
        daemon.poll.return_value = qemu.poll.return_value = None

        def cancelled_wait(timeout=None):
            if timeout is None:
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            return 0

        qemu.wait.side_effect = cancelled_wait
        with patch('subprocess.Popen', side_effect=[daemon, qemu]), \
                patch.dict(v['run_vm'].__globals__, wait_for_socket=Mock()), \
                patch('sys.stdout') as output:
            output.isatty.return_value = True
            with self.assertRaises(SystemExit):
                v['run_vm']('safe', 'uuid', Path('/cache/disk.img'), Path('/cache/temp'),
                            1024, v['NetworkMode'].NONE, False, [(Path('/shared'), True)], True)
        for child in (daemon, qemu):
            child.terminate.assert_called_once()
            child.wait.assert_any_call(timeout=5)
        output.write.assert_called_once_with('\x1b\\')
        output.flush.assert_called_once()

    def test_signal_during_failed_spawn_preserves_cancellation(self):
        def spawn(command):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            raise OSError('startup failed')

        with patch('subprocess.Popen', side_effect=spawn):
            with self.assertRaises(SystemExit) as error:
                with v['vm_children']() as start:
                    start(['child'])
        self.assertEqual(error.exception.code, 128 + signal.SIGTERM)
