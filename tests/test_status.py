import argparse
import io
import json
from pathlib import Path
import runpy
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

v = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'virter'))


class StatusTests(unittest.TestCase):
    def test_status_protocol(self):
        for data, expected in ((b'0\n', 0), (b'42\n', 42), (b'255\n', 255),
                               (b'', 125), (b'+0\n', 125), (b'1_0\n', 125),
                               (b'256\n', 125), (b'0\n0\n', 125), (b'0', 125),
                               (b'\xff\n', 125), (b'0\n' + b'x' * 1024, 125)):
            with self.subTest(data=data), patch('sys.stderr', new=io.StringIO()), \
                    tempfile.TemporaryDirectory() as directory:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                    path = str(Path(directory) / 'status.sock')
                    listener.bind(path)
                    listener.listen(1)
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                        client.connect(path)
                        client.sendall(data)
                    self.assertEqual(v['read_guest_status'](listener), expected)

    def test_qemu_and_guest_failures(self):
        for qemu_status, data, expected in ((0, b'0\n', 0), (0, b'17\n', 17),
                                             (0, b'', 125), (0, None, 125), (1, b'0\n', 125), (-31, b'0\n', 125)):
            with self.subTest(qemu_status=qemu_status, data=data), tempfile.TemporaryDirectory() as directory:
                temp = Path(directory)
                child = Mock()
                child.wait.return_value = qemu_status

                def start_qemu(*args, **kwargs):
                    # The listener is ready before QEMU starts; reports survive until the host reads them.
                    if data is None:
                        return child
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                        client.connect(str(temp / 'status.sock'))
                        client.sendall(data)
                    return child

                with patch('subprocess.Popen', side_effect=start_qemu) as start, \
                        patch.dict(v['run_vm'].__globals__, relay_output=Mock()), \
                        patch('sys.stderr', new=io.StringIO()):
                    def launch():
                        v['run_vm']('safe', 'uuid', temp / 'disk.img', temp, 1024,
                                    v['NetworkMode'].NONE, False, [], True, report_status=True)
                    if expected:
                        with self.assertRaises(SystemExit) as error:
                            launch()
                        self.assertEqual(error.exception.code, expected)
                    else:
                        launch()
                self.assertIn('socket,id=status,path=' + str(temp / 'status.sock') + ',server=off',
                              start.call_args.args[0])
                self.assertIn('chardev:status', start.call_args.args[0])

    def test_generated_profile_reports_command_and_setup_failures(self):
        for command, workdir, mounts, expected in (
                (['sh', '-c', 'exit 37'], None, [], 37),
                (['exit', '19'], None, [], 19),
                (['sh', '-c', 'kill -KILL $$'], None, [], 137),
                (['exec', 'sh', '-c', 'exit 23'], None, [], 23),
                (['virter-no-such-command'], None, [], 127),
                (['true'], '/virter-no-such-directory', [], 125),
                (['true'], None, [(Path('/virter-no-such-mount'), True)], 125),
                (['true'], None, [], 0),
                ([], None, [], 0)):
            with self.subTest(command=command, workdir=workdir, mounts=mounts), \
                    tempfile.TemporaryDirectory() as directory:
                temp = Path(directory)
                generate = Mock()
                args = argparse.Namespace(name='safe', base='base', memory=1024, network='none',
                                          allow_sudo=False, workdir=workdir, COMMAND=command)
                with patch.dict(v['_run'].__globals__, collect_mounts=lambda _: mounts,
                                base_image_path=lambda *_: temp / 'base.img', validate_disk_size=Mock(),
                                runtime_directory=lambda: temp, generate_cloud_init=generate, run_vm=Mock()), \
                        patch('pathlib.Path.is_file', return_value=True), patch('subprocess.run'):
                    v['_run'](args, temp)
                profile = json.loads(generate.call_args.kwargs['vendor_data'].rsplit('  content: ', 1)[1])
                status = temp / 'status'
                profile = profile.replace('/dev/ttyS2', str(status))
                # Stub terminal setup and shutdown; execute the guest shell flow without starting a VM.
                script = 'stty() { :; }; sync() { :; }; sudo() { :; };\n' + profile
                result = subprocess.run(['bash', '-c', script], capture_output=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(status.read_bytes(), str(expected).encode() + b'\n')
