import argparse
import http.server
import json
from pathlib import Path
import runpy
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "network" / "verify-bridge"
b = runpy.run_path(str(SCRIPT))


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.listeners = b['Listeners']({'token'})
        self.addCleanup(self.listeners.close)

    def test_probe_tells_listener_from_blocked(self):
        for proto in ('tcp', 'udp'):
            with self.subTest(proto=proto):
                port = self.listeners.add(proto, '127.0.0.1')['port']
                self.assertEqual(b['probe'](proto, '127.0.0.1', port, 'token', 1), 'echoed')
                self.assertEqual(self.listeners.hits_for('token')[-1]['proto'], proto)
                self.assertEqual(b['probe'](proto, '127.0.0.1', port, 'unknown', 0.2), 'connected' if proto == 'tcp'
                                 else 'blocked')
                self.listeners.close()
                self.assertEqual(b['probe'](proto, '127.0.0.1', port, 'token', 0.2), 'blocked')
                self.listeners.sockets = []

    def test_unknown_token_is_not_recorded_as_a_hit(self):
        port = self.listeners.add('tcp', '127.0.0.1')['port']
        b['probe']('tcp', '127.0.0.1', port, 'other', 0.2)
        self.assertEqual(self.listeners.hits, [])

    def test_probe_all_covers_every_port_at_every_target(self):
        port = self.listeners.add('tcp', '127.0.0.1')['port']
        results = b['probe_all'](['127.0.0.1', '127.0.0.2'], [['tcp', port]], 'token', 0.5)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['outcome'], 'echoed')


class TargetTests(unittest.TestCase):
    def test_peer_names_become_literal_reachable_addresses(self):
        listeners = b['Listeners']()
        self.addCleanup(listeners.close)
        port = listeners.add('tcp', '127.0.0.1')['port']
        self.assertEqual(b['resolve_peers']([('localhost', port)], 'token'), [('127.0.0.1', port)])

    def test_targets_include_mapped_slirp_and_loopback_addresses(self):
        targets = b['host_targets']([{'address': '192.168.1.5'}, {'address': '2001:db8::5'}])
        for expected in ('192.168.1.5', '::ffff:192.168.1.5', '2001:db8::5', '10.0.2.2', '10.0.2.3',
                         '127.0.0.1', '127.0.0.2', '::1'):
            self.assertIn(expected, targets)
        self.assertNotIn('::ffff:2001:db8::5', targets)

    def test_peer_parsing(self):
        self.assertEqual(b['parse_peer']('192.168.1.9:80'), ('192.168.1.9', 80))
        self.assertEqual(b['parse_peer']('[fd00::9]:80'), ('fd00::9', 80))
        with self.assertRaises(argparse.ArgumentTypeError):
            b['parse_peer']('[fe80::9%1]:80')


EGRESS = {'egress_v4': ('192.0.2.1', 443), 'egress_v6': ('2001:db8::1', 443)}


class Reports:
    def report(self, directory):
        return b['Report'](Path(directory) / 'report.json')


class HostCheckTests(unittest.TestCase, Reports):
    def statuses(self, report):
        return [entry['status'] for entry in report.entries]

    def test_failed_service_listing_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch('subprocess.run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='no bus')):
            report = self.report(directory)
            self.assertFalse(b['no_backend_remains'](report))
            self.assertEqual(self.statuses(report), ['FAIL'])

    def test_expected_dns_failure_ignores_the_resolver_cache(self):
        for expect, flush in ((False, True), (True, False)):
            vm = Mock()
            vm.do.side_effect = [{'ok': expect}, {'ok': expect}]
            with self.subTest(expect=expect), tempfile.TemporaryDirectory() as directory:
                b['connectivity'](vm, SimpleNamespace(dns_name='name', https_url='url'), self.report(directory),
                                  'label', expect)
                self.assertEqual(vm.do.call_args_list[0].args[0]['flush'], flush)

    def test_dns_flush_refuses_to_run_outside_a_vm(self):
        with patch('subprocess.run', return_value=SimpleNamespace(returncode=1)) as run:
            self.assertIn('guest_error', b['perform_safely']({'type': 'resolve', 'name': 'name', 'flush': True}))
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][0], 'systemd-detect-virt')

    def test_backend_must_be_running_while_connected(self):
        for stdout, expected in (('virter-passt@0.service loaded active running\n', 'PASS'), ('', 'FAIL')):
            with self.subTest(stdout=stdout), tempfile.TemporaryDirectory() as directory, patch('time.sleep'), \
                    patch('subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=stdout)):
                report = self.report(directory)
                b['check_backend_runs'](report)
                self.assertEqual(self.statuses(report), [expected])

    def test_guest_failure_is_raised_rather_than_read_as_empty(self):
        with patch('subprocess.run', return_value=SimpleNamespace(returncode=1, stdout='', stderr='broken')):
            self.assertIn('guest_error', b['perform_safely']({'type': 'facts'}))
        vm = object.__new__(b['Vm'])
        vm.step, vm.directory = 0, Path('/nonexistent')
        with patch.dict(b['Vm'].do.__globals__, write_json=Mock()), \
                patch.object(b['Vm'], 'wait_for', return_value=[{'guest_error': 'facts: broken'}]), \
                self.assertRaises(RuntimeError):
            vm.do({'type': 'facts'})

    def test_relocation_without_egress_gives_no_isolation_results(self):
        vm = Mock()
        vm.do.side_effect = [{'ok': True}, {'reached': []}]
        with tempfile.TemporaryDirectory() as directory:
            report = self.report(directory)
            b['relocated_round'](vm, SimpleNamespace(must_block=[], **EGRESS), Mock(), report, 'token', [],
                                 Path(directory))
            self.assertEqual(self.statuses(report), ['PASS', 'FAIL'])
        self.assertEqual(vm.do.call_count, 2)

    def test_lost_ipv6_egress_is_not_reported_as_tested(self):
        vm = Mock()
        vm.do.side_effect = [{'reached': [{'address': '192.0.2.1'}]}, {'count': 0, 'reached': []}]
        listeners = Mock()
        listeners.hits_for.return_value = []
        with tempfile.TemporaryDirectory() as directory, patch.dict(b['egressing_isolation_round'].__globals__,
                                                                    probe=Mock(return_value='connected')):
            report = self.report(directory)
            b['egressing_isolation_round'](vm, SimpleNamespace(**EGRESS), listeners, report, 'token', 'label', [])
            self.assertIn('FAIL', self.statuses(report))

    def test_relocation_rechecks_must_block_services(self):
        vm = Mock()
        vm.do.side_effect = [{'ok': True}, {'reached': [{'address': '192.0.2.1'}, {'address': '2001:db8::1'}]},
                             {'count': 0, 'reached': []}, {'reached': [{'outcome': 'connected'}]}]
        listeners = Mock()
        listeners.hits_for.return_value = []
        with tempfile.TemporaryDirectory() as directory:
            report = self.report(directory)
            b['relocated_round'](vm, SimpleNamespace(must_block=[('192.168.1.5', 8080)], **EGRESS), listeners,
                                 report, 'token', [], Path(directory))
            self.assertEqual(report.entries[-1]['status'], 'FAIL')
            self.assertIn('192.168.1.5:8080', report.entries[-1]['check'])

    def test_restore_is_offered_when_a_failure_case_breaks(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(b['case_invalid_policy'].__globals__, Vm=Mock(side_effect=RuntimeError('boot'))), \
                patch('builtins.input', return_value=''), patch('builtins.print') as output, \
                self.assertRaises(RuntimeError):
            b['case_invalid_policy'](Mock(), Path(directory), self.report(directory))
        self.assertTrue(any('sudo mv' in str(call) for call in output.call_args_list))

    def test_prompt_does_not_block_while_terminating(self):
        with patch.dict(b['prompt'].__globals__, terminating=True), patch('builtins.input') as read, \
                patch('builtins.print'):
            self.assertFalse(b['prompt']('Restore it:', ['command']))
        read.assert_not_called()

    def test_port_53_gaps_are_reported(self):
        listeners = b['Listeners']()
        self.addCleanup(listeners.close)
        listeners.dns_missing.append('udp 127.0.0.1: Permission denied')
        with tempfile.TemporaryDirectory() as directory:
            report = self.report(directory)
            b['report_dns_coverage'](listeners, report)
            self.assertEqual(self.statuses(report), ['MANUAL'])
            self.assertIn('udp 127.0.0.1', report.entries[0]['detail'])


class Quiet(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


class EndToEndTests(unittest.TestCase):
    """Run the host side with a fake virter that runs the guest side on this machine, with no isolation."""

    def run_host(self, directory, url, egress=9):
        fake = Path(directory) / 'virter'
        fake.write_text(textwrap.dedent(f"""\
            #!{sys.executable}
            import os, sys
            args = sys.argv[sys.argv.index('--') + 1:]
            os.execv(sys.executable, [sys.executable, '-B', *args[1:]])
            """))
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        return subprocess.run(
            [sys.executable, '-B', str(SCRIPT), 'run', '--virter', str(fake), '--output-dir', directory, '--yes',
             '--force', '--skip', 'none', '--skip', 'host', '--no-secondary', '--no-relocate',
             '--https-url', url, '--dns-name', 'localhost',
             '--egress-v4', f'127.0.0.1:{egress}', '--egress-v6', '[::1]:9'],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)

    def test_reachable_host_listener_is_reported_as_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Quiet)
            self.addCleanup(server.server_close)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.shutdown)
            url = f'http://127.0.0.1:{server.server_port}/'
            result = self.run_host(directory, url, server.server_port)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            report = json.loads(next(Path(directory).glob('virter-verify-*/report.json')).read_text())
            failed = [entry['check'] for entry in report if entry['status'] == 'FAIL']
            self.assertTrue(any('host listeners unreachable' in check for check in failed), failed)
            self.assertTrue(any('received no guest request' in check for check in failed), failed)

    def test_guest_without_egress_gets_no_isolation_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_host(directory, 'http://127.0.0.1:9/')
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            report = json.loads(next(Path(directory).glob('virter-verify-*/report.json')).read_text())
            self.assertFalse([entry for entry in report if 'host listeners' in entry['check']
                              and 'from the host' not in entry['check']])
            self.assertIn('bridge isolation', [entry['check'] for entry in report if entry['status'] == 'SKIP'])


if __name__ == '__main__':
    unittest.main()
