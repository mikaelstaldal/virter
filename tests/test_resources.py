import argparse
import contextlib
import io
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import Mock, patch

v = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'virter'))


class ResourceTests(unittest.TestCase):
    def test_resource_values_are_bounded_before_work(self):
        for options in (['run', '-m', '0'], ['update', '-m', '8193'],
                        ['prepare', '-i', 'image', '--sha256', 'a' * 64, '-d', '-1'],
                        ['run', '--timeout', '0'], ['run', '--timeout', '86401']):
            with self.subTest(options=options), patch('sys.argv', ['virter', *options]), \
                    contextlib.redirect_stderr(io.StringIO()), patch('subprocess.run') as run, \
                    self.assertRaises(SystemExit) as error:
                v['main']()
            self.assertEqual(error.exception.code, 2)
            run.assert_not_called()

    def test_scope_preserves_literal_arguments_and_covers_launcher(self):
        with patch('sys.argv', ['virter', 'run', '--', 'echo', '$HOME']), patch('os.execvp') as execute:
            v['supervise'](argparse.Namespace(memory=1024, timeout=60))
        command = execute.call_args.args[1]
        self.assertIn('--scope', command)
        self.assertIn(f'--property=CPUQuota={v["VM_CPUS"] * 100}%', command)
        self.assertIn('--expand-environment=no', command)
        self.assertIn('--property=MemoryMax=2048M', command)
        self.assertIn('--property=RuntimeMaxSec=60', command)
        self.assertEqual(command[-4:], ['run', '--', 'echo', '$HOME'])

    def test_output_cap_stops_forwarding(self):
        stream = Mock()
        stream.read1.side_effect = [b'ab', b'cd']
        with patch.dict(v['relay_output'].__globals__, MAX_OUTPUT_BYTES=3), patch('sys.stdout') as output:
            with self.assertRaises(SystemExit):
                v['relay_output'](stream)
        output.buffer.write.assert_called_once_with(b'ab')

    def test_cgroup_limit_failure_prevents_lock_and_work(self):
        valid = {'memory.max': '2147483648', 'memory.swap.max': '0',
                 'pids.max': '128', 'cpu.max': f'{v["VM_CPUS"] * 100000} 100000'}
        for filename, value in (('memory.max', 'max'), ('memory.max', '999999999999'),
                                ('memory.swap.max', '1'), ('pids.max', 'max'),
                                ('pids.max', '129'), ('cpu.max', 'max 100000'),
                                ('cpu.max', f'{(v["VM_CPUS"] + 1) * 100000} 100000')):
            def read(path):
                if str(path) == '/proc/self/cgroup':
                    return '0::/user.slice/test.scope'
                return value if path.name == filename else valid[path.name]
            with self.subTest(filename=filename, value=value), patch('pathlib.Path.read_text', read), \
                    patch('os.open') as opened, self.assertRaises(SystemExit):
                with v['resource_limits'](argparse.Namespace(memory=1024, _supervised='test.scope')):
                    self.fail('must fail closed')
            opened.assert_not_called()

    def test_concurrency_lock_rejects_third_invocation_and_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            def read(path):
                return {'/proc/self/cgroup': '0::/test.scope',
                        '/sys/fs/cgroup/test.scope/memory.max': '2147483648',
                        '/sys/fs/cgroup/test.scope/memory.swap.max': '0',
                        '/sys/fs/cgroup/test.scope/pids.max': '128',
                        '/sys/fs/cgroup/test.scope/cpu.max': f'{v["VM_CPUS"] * 100000} 100000'}[str(path)]
            real_open = __import__('os').open

            def open_lock(path, flags, mode):
                return real_open(Path(directory) / path.name, flags, mode)

            with patch('pathlib.Path.read_text', read), \
                    patch('pathlib.Path.stat', return_value=argparse.Namespace(st_uid=1000, st_mode=0o40700)), \
                    patch('os.getuid', return_value=1000), patch('os.open', side_effect=open_lock), \
                    patch('resource.setrlimit') as limit:
                args = argparse.Namespace(memory=1024, _supervised='test.scope')
                with v['resource_limits'](args):
                    with v['resource_limits'](args):
                        with self.assertRaises(SystemExit):
                            with v['resource_limits'](args):
                                self.fail('third invocation admitted')
                    with v['resource_limits'](args):
                        pass
                self.assertTrue(limit.called)

    def test_existing_oversized_virtual_disk_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'base.img'
            header = bytearray(32)
            header[:4] = b"QFI\xfb"
            header[24:32] = (17 * 1024 ** 3).to_bytes(8, 'big')
            image.write_bytes(header)
            with self.assertRaises(SystemExit):
                v['validate_disk_size'](image)

    def test_main_dispatches_outer_and_supervised_launches(self):
        for supervised in (False, True):
            arguments = ['virter'] + (['--_supervised=test.scope'] if supervised else []) + ['run']
            supervise, run = Mock(), Mock()
            limits = Mock(return_value=contextlib.nullcontext())
            with patch('sys.argv', arguments), patch('os.getuid', return_value=1000), \
                    patch('os.geteuid', return_value=1000), patch('shutil.which', return_value='/usr/bin/bwrap'), \
                    patch('subprocess.run') as preflight, patch.dict(v['main'].__globals__, supervise=supervise,
                                                       resource_limits=limits, run=run):
                v['main']()
            self.assertEqual(preflight.call_count, int(supervised))
            self.assertEqual(supervise.call_count, int(not supervised))
            self.assertEqual(limits.call_count, int(supervised))
            self.assertEqual(run.call_count, int(supervised))

    def test_output_limit_reaps_qemu(self):
        child = Mock()
        child.poll.return_value = None
        child.stdout = io.BufferedReader(io.BytesIO(b'too much output'))
        with patch('subprocess.Popen', return_value=child), patch('sys.stdout'), \
                patch.dict(v['run_vm'].__globals__, MAX_OUTPUT_BYTES=1), self.assertRaises(SystemExit):
            v['run_vm']('safe', 'uuid', Path('/cache/disk.img'), Path('/tmp/vm'),
                        1024, v['NetworkMode'].NONE, False, [], True)
        child.terminate.assert_called_once()
        child.wait.assert_called_once_with(timeout=5)
        self.assertTrue(child.stdout.closed)
