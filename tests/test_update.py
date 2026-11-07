import argparse
import json
import runpy
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

v = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'virter'))


class UpdateTests(unittest.TestCase):
    def test_update_passes_command_to_persistent_image_setup(self):
        setup = Mock()
        with patch.dict(v['update'].__globals__, prepare_or_update=setup):
            v['update'](argparse.Namespace(base='custom', memory=2048, COMMAND='echo',
                                           ARG=['hello world'], sudo=False, network='host'))
        setup.assert_called_once_with(None, 'custom', 2048, None, [], command=['echo', 'hello world'], sudo=False,
                                      network=v['NetworkMode'].HOST)

    def test_cli_accepts_command_arguments_after_separator(self):
        dispatch = Mock()
        with patch.dict(v['main'].__globals__, supervise=dispatch), \
                patch('sys.argv', ['virter', 'update', '-b', 'custom', '--', 'echo', '-n', 'hello world']), \
                patch('os.getuid', return_value=1000), patch('os.geteuid', return_value=1000), \
                patch('shutil.which', return_value='/usr/bin/bwrap'):
            v['main']()
        args = dispatch.call_args.args[0]
        self.assertEqual((args.base, args.COMMAND, args.ARG), ('custom', 'echo', ['-n', 'hello world']))

    def test_command_seed_is_transient_quoted_and_shuts_down_orderly(self):
        command = ['printf', '%s', 'hello world', "a; $(touch /oops)\n'quoted'", "😀"]
        with tempfile.TemporaryDirectory() as directory, patch('subprocess.run'), \
                patch('getpass.getuser', return_value='tester'):
            v['cloud_init_update']('base', Path(directory), command)
            data = (Path(directory) / 'vendor-data').read_text()
        setup = next(json.loads(line[2:])[2] for line in data.splitlines() if line.startswith('- ["sh",'))
        tokens = shlex.split(setup)
        script = tokens[tokens.index('printf') + 2]
        self.assertEqual(shlex.split(script.split('\n', 1)[1]), command)
        self.assertIn('/run/systemd/system/serial-getty@ttyS1.service.d/zz-command.conf', setup)
        self.assertIn('ExecStart=-/usr/bin/sudo -i -u tester -- /bin/bash /run/virter-command.sh', setup)
        self.assertIn('ExecStart=/sbin/shutdown -h --no-wall now', setup)
        self.assertNotIn('poweroff -ff', data)
        self.assertNotIn('.profile', data)
        self.assertNotIn('write_files:', data.replace('write_files:\n', '', 1))
        self.assertTrue(setup.endswith('&& systemctl daemon-reload'))
        self.assertIn('😀', data)

    def test_interactive_seed_keeps_existing_login(self):
        generate = Mock()
        with patch.dict(v['cloud_init_update'].__globals__, generate_cloud_init=generate):
            v['cloud_init_update']('base', Path('/seed'))
        self.assertEqual(generate.call_args.args[2], v['CLOUD_CONFIG_HEADER'] + 'users: []\n')

    def test_sudo_runs_guest_command_as_root(self):
        generate = Mock()
        with patch.dict(v['cloud_init_update'].__globals__, generate_cloud_init=generate):
            v['cloud_init_update']('base', Path('/seed'), ['sh', '-c', 'apt update && apt -y upgrade'], sudo=True)
        self.assertIn('ExecStart=-/usr/bin/sudo -i -u root -- /bin/bash /run/virter-command.sh',
                      generate.call_args.args[2])

    def test_cli_passes_sudo_to_update(self):
        setup = Mock()
        with patch.dict(v['main'].__globals__, supervise=Mock(), prepare_or_update=setup), \
                patch('sys.argv', ['virter', 'update', '--sudo', '--', 'sh', '-c', 'apt update && apt -y upgrade']), \
                patch('os.getuid', return_value=1000), patch('os.geteuid', return_value=1000), \
                patch('shutil.which', return_value='/usr/bin/bwrap'):
            # Dispatch via the same Namespace the supervisor forwards to the child.
            supervise = v['main'].__globals__['supervise']
            supervise.side_effect = v['update']
            v['main']()
        self.assertEqual(setup.call_args.kwargs,
                         {'command': ['sh', '-c', 'apt update && apt -y upgrade'], 'sudo': True,
                          'network': v['NetworkMode'].HOST})

    def test_sudo_requires_command(self):
        with patch('sys.argv', ['virter', 'update', '--sudo']), patch('sys.stderr'), \
                self.assertRaises(SystemExit) as error:
            v['main']()
        self.assertEqual(error.exception.code, 2)

    def test_prepare_and_update_network_selection_reaches_qemu(self):
        for action in ('prepare', 'update'):
            for network in ('host', 'bridge', 'none', None):
                with self.subTest(action=action, network=network), tempfile.TemporaryDirectory() as directory:
                    cache = Path(directory)
                    source = cache / 'source.img'
                    source.touch()
                    (cache / 'base.img').touch()
                    argv = ['virter', action]
                    if action == 'prepare':
                        argv += ['-i', str(source), '--sha256', '0' * 64]
                    if network is not None:
                        argv += ['--network', network]
                    vm = Mock()
                    with patch.dict(v['main'].__globals__, supervise=lambda args: args.func(args),
                                    prepare_cache_dir=lambda: cache, base_lock=MagicMock(),
                                    base_image_path=lambda *args: cache / ('new.img' if action == 'prepare' else 'base.img'),
                                    validate_disk_size=Mock(), validate_import=Mock(),
                                    cloud_init_prepare=Mock(), cloud_init_update=Mock(), run_vm=vm), \
                            patch('sys.argv', argv), patch('subprocess.run'), \
                            patch('os.getuid', return_value=1000), patch('os.geteuid', return_value=1000), \
                            patch('shutil.which', return_value='/usr/bin/bwrap'):
                        v['main']()
                    self.assertEqual(vm.call_args.args[5], v['NetworkMode'](network or 'host'))
