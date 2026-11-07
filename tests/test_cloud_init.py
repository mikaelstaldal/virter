import argparse
import json
from pathlib import Path
import runpy
import shlex
import tempfile
import unittest
from unittest.mock import Mock, patch

v = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'virter'))


class CloudInitEncodingTests(unittest.TestCase):
    def test_mount_arguments_and_multiline_profile_remain_data(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache / 'base.qcow2').touch()
            paths = [cache / 'a "quote" $(touch oops) `id`\n: []', cache / 'writable']
            command = ['printf', '%s', 'one\ntwo\r\n\n', '$(id) `id` "quoted"', '日本語']
            workdir = 'work\nnext "$(id)"'
            username = 'a"user'
            generate = Mock()
            args = argparse.Namespace(name='instance', base='base', memory=1024, network='none', allow_sudo=False,
                                      workdir=workdir, COMMAND=command)
            with patch.dict(v['_run'].__globals__, collect_mounts=lambda _: [(paths[0], True), (paths[1], False)],
                            base_image_path=lambda *_: cache / 'base.qcow2', validate_disk_size=Mock(),
                            generate_cloud_init=generate, run_vm=Mock()), \
                    patch('subprocess.run'), patch('getpass.getuser', return_value=username):
                v['_run'](args, cache)
            data = generate.call_args.kwargs['vendor_data']
        boot, files = data.split('bootcmd:\n')[1].split('write_files:\n')
        self.assertEqual([json.loads(line[2:]) for line in boot.splitlines()][1:], [
            ['mkdir', '-p', '--', str(paths[0])],
            ['mount', '-t', 'virtiofs', '-o', 'ro', 'virtiofs0', str(paths[0])],
            ['mkdir', '-p', '--', str(paths[1])],
            ['mount', '-t', 'virtiofs', 'virtiofs1', str(paths[1])]])
        setup = json.loads(boot.splitlines()[0][2:])
        self.assertIn(shlex.join(['usermod', '-G', '', '--', username]), setup[2])
        script = json.loads(files.rsplit('  content: ', 1)[1].strip())
        self.assertIn('cd ' + shlex.quote(workdir) + '\n', script)
        self.assertIn(shlex.join(command) + '\n', script)
        self.assertIn('- path: ' + json.dumps(f'/home/{username}/.profile') + '\n', files)
        self.assertIn('- path: ' + json.dumps(f'/home/{username}/.hushlogin') + '\n', files)

    def test_metadata_scalars_are_encoded(self):
        name = 'false: "quoted"\nnew-key: value'
        with tempfile.TemporaryDirectory() as directory, patch('subprocess.run'):
            v['generate_cloud_init'](name, Path(directory), '#cloud-config\n')
            lines = (Path(directory) / 'meta-data').read_text().splitlines()
        metadata = dict(line.split(': ', 1) for line in lines[1:])
        self.assertEqual(json.loads(metadata['local-hostname']), name)
        self.assertTrue(json.loads(metadata['instance-id']).startswith(name + '-'))

    def test_yaml_encoding_preserves_unicode_and_yaml_line_breaks(self):
        value = "emoji 😀\n\r\u2028\u2029\ufffe\uffff" + "".join(map(chr, range(0x7f, 0xa0)))
        encoded = v['yaml_encode'](value)
        self.assertEqual(json.loads(encoded), value)
        self.assertIn('😀', encoded)
        for character in (*map(chr, range(0x7f, 0xa0)), '\u2028', '\u2029', '\ufffe', '\uffff'):
            self.assertNotIn(character, encoded)

    def test_locale_content_cannot_add_yaml_entries(self):
        value = "x\r- path: /injected\r  content: bad\r#\u0085\u2028😀"
        with patch.dict('os.environ', {'LANG': value}, clear=True), \
                patch.dict(v['guest_localization'].__globals__, read_timezone=lambda: ''):
            data = v['guest_localization']('#cloud-config\n')
        lines = data.splitlines()
        self.assertEqual(lines[:3], ['#cloud-config', 'write_files:',
                                     '- path: /etc/profile.d/virter-locale.sh'])
        self.assertEqual(len(lines), 4)
        self.assertEqual(json.loads(lines[3].removeprefix('  content: ')),
                         'export LANG=' + shlex.quote(value) + '\n')


class GuestPrivilegeTests(unittest.TestCase):
    def test_run_privileges_and_shutdown(self):
        for root in (False, True):
            with self.subTest(allow_sudo=root), tempfile.TemporaryDirectory() as directory:
                cache = Path(directory)
                base = cache / 'base.img'
                base.touch()
                generate = Mock()
                args = argparse.Namespace(name='instance', base='base', memory=1024, network='none',
                                          allow_sudo=root, workdir=None, COMMAND=['true'])
                with patch.dict(v['_run'].__globals__, collect_mounts=lambda _: [],
                                base_image_path=lambda *_: base, validate_disk_size=Mock(),
                                generate_cloud_init=generate, run_vm=Mock()), \
                        patch('subprocess.run'), patch('getpass.getuser', return_value='tester'), \
                        patch('os.getuid', return_value=1234):
                    v['_run'](args, cache)
                data = generate.call_args.kwargs['vendor_data']
                self.assertEqual('bootcmd:' in data, not root)
                self.assertEqual('/etc/sudoers.d/90-cloud-init-users' in data, not root)
                self.assertEqual('/etc/sudoers.d/virter-poweroff' in data, not root)
                if not root:
                    commands = data.split('bootcmd:\n')[1].split('write_files:\n')[0]
                    setup, = [json.loads(line[2:]) for line in commands.splitlines()]
                    self.assertEqual(setup[:2], ['sh', '-c'])
                    self.assertIn("if ! usermod -G '' -- tester || ! rm -f /etc/sudoers.d/90-cloud-init-users", setup[2])
                    self.assertIn('systemctl mask --runtime --now serial-getty@ttyS1.service', setup[2])
                    self.assertIn('/usr/sbin/poweroff -ff; exit 1', setup[2])
                    self.assertIn("permissions: '0440'", data)
                    rule = json.loads(data.split('  content: ', 1)[1].splitlines()[0])
                    self.assertEqual(rule, '#1234 ALL=(root) NOPASSWD: /usr/sbin/poweroff -ff\n')
                profile = json.loads(data.rsplit('  content: ', 1)[1].strip())
                self.assertIn('sudo -n /usr/sbin/poweroff -ff', profile)

    def test_preparation_retains_sudo_and_uid(self):
        generate = Mock()
        with patch.dict(v['cloud_init_prepare'].__globals__, generate_cloud_init=generate), \
                patch('os.getuid', return_value=1234), patch('getpass.getuser', return_value='tester'):
            v['cloud_init_prepare']('base', Path('/unused'), [])
        data = generate.call_args.args[2]
        self.assertIn('NOPASSWD:ALL', data)
        self.assertIn('uid: "1234"', data)
