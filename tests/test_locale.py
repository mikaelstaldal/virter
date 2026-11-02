import json
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def decoded_content(data):
    return data + '\n' + '\n'.join(json.loads(line.removeprefix('  content: '))
                                       for line in data.splitlines() if line.startswith('  content: "'))


v = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'virter'))


class LocaleTests(unittest.TestCase):
    def test_locale_categories_language_and_timezone_are_serialized(self):
        environment = {'LANG': 'sv_SE.UTF-8', 'LANGUAGE': 'sv:en',
                       'LC_TIME': 'de_DE.UTF-8', 'LC_ALL': 'fr_FR.UTF-8', 'TZ': 'Europe/Stockholm'}
        with patch.dict(os.environ, environment, clear=True), \
                patch.dict(v['guest_localization'].__globals__, read_timezone=lambda: 'Europe/Stockholm'):
            data = v['guest_localization'](
                '#cloud-config\nwrite_files:\n- path: /existing\nbootcmd:\n- echo existing\n', generate_locales=True)
        for key, value in environment.items():
            self.assertIn(f'export {key}={value}\n', decoded_content(data))
        self.assertIn('timezone: "Europe/Stockholm"', data)
        self.assertIn(json.dumps(['locale-gen', 'de_DE.UTF-8', 'fr_FR.UTF-8', 'sv_SE.UTF-8']), data)
        self.assertEqual(data.count('write_files:\n'), 1)
        self.assertEqual(data.count('bootcmd:\n'), 1)
        self.assertIn('- path: /existing', data)
        self.assertIn('- echo existing', data)

    def test_empty_environment_uses_portable_locale(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.dict(v['guest_localization'].__globals__, read_timezone=lambda: ''):
            data = v['guest_localization']('#cloud-config\nusers: []\n')
        self.assertIn('export LANG=C.UTF-8', decoded_content(data))
        self.assertNotIn('locale-gen', data)
        self.assertNotIn('timezone:', data)

    def test_shell_values_are_quoted_and_only_locale_variables_are_forwarded(self):
        with patch.dict(os.environ, {'LANG': 'C', 'LANGUAGE': 'sv; touch /tmp/oops',
                                     'SECRET': 'hidden', 'TZ': ''}, clear=True):
            data = v['guest_localization']('#cloud-config\n')
        self.assertIn("export LANGUAGE='sv; touch /tmp/oops'", decoded_content(data))
        self.assertIn("export TZ=''", decoded_content(data))
        self.assertNotIn('SECRET', data)

    def test_timezone_override_and_system_fallback(self):
        for override in ('Europe/Paris', ':Europe/Paris', ':/usr/share/zoneinfo/Europe/Paris'):
            with self.subTest(override=override), patch.dict(os.environ, {'TZ': override}, clear=True), \
                    patch('pathlib.Path.is_file', return_value=True):
                self.assertEqual(v['read_timezone'](), 'Europe/Paris')
        with patch.dict(os.environ, {}, clear=True), \
                patch('os.readlink', return_value='../usr/share/zoneinfo/Europe/Stockholm'):
            self.assertEqual(v['read_timezone'](), 'Europe/Stockholm')
        with patch.dict(os.environ, {}, clear=True), patch('os.readlink', side_effect=OSError), \
                patch('pathlib.Path.read_text', return_value='Etc/UTC\n'):
            self.assertEqual(v['read_timezone'](), 'Etc/UTC')

    def test_every_seed_contains_current_settings(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {'LANG': 'de_DE.UTF-8'}, clear=True), patch('subprocess.run'):
            directory = Path(directory)
            for generates_locales, generate in (
                    (True, lambda: v['cloud_init_prepare']('base', directory, [])),
                    (True, lambda: v['cloud_init_update']('base', directory)),
                    (False, lambda: v['generate_cloud_init']('run', directory, '#cloud-config\nusers: []\n'))):
                generate()
                first_metadata = (directory / 'meta-data').read_text()
                generate()
                self.assertNotEqual(first_metadata, (directory / 'meta-data').read_text())
                data = (directory / 'vendor-data').read_text()
                self.assertIn('export LANG=de_DE.UTF-8', decoded_content(data))
                if generates_locales:
                    commands = data.split('bootcmd:\n', 1)[1].splitlines()
                    self.assertTrue(commands)
                    self.assertTrue(all(line.startswith('- ') for line in commands))
                    self.assertIn('["locale-gen", "de_DE.UTF-8"]', data)
                else:
                    self.assertNotIn('locale-gen', data)
                    self.assertNotIn('bootcmd:', data)

    def test_indented_user_content_is_not_a_cloud_config_key(self):
        with patch.dict(os.environ, {'LANG': 'sv_SE.UTF-8'}, clear=True):
            data = v['guest_localization'](
                '#cloud-config\nwrite_files:\n- path: /home/user/.profile\n  content: |\n'
                '    bootcmd:\n    write_files:\n    runcmd:\n', generate_locales=True)
        self.assertIn('    bootcmd:\n    write_files:\n    runcmd:\n', data)
        self.assertIn('\nbootcmd:\n- ["locale-gen", "sv_SE.UTF-8"]\n', data)
