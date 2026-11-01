import configparser
from pathlib import Path
import runpy
import subprocess
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
v = runpy.run_path(str(ROOT / "virter"))


def unit(name):
    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str
    config.read_string((ROOT / "network" / name).read_text().replace("\\\n", " "))
    return config


class BridgeTests(unittest.TestCase):
    def launch(self):
        v['run_vm']('safe', 'uuid', Path('/cache/instance/disk.img'), Path('/cache/instance'),
                    1024, v['NetworkMode'].BRIDGE, False, [], True, Path('/cache/base.img'))

    def test_qemu_gets_only_the_connected_backend_socket(self):
        qemu = Mock()
        qemu.wait.return_value = 0
        with patch.dict(v['run_vm'].__globals__, relay_output=Mock()), \
                patch('subprocess.Popen', return_value=qemu) as start, \
                patch('socket.socket') as sock:
            connection = sock.return_value
            connection.__enter__.return_value = connection
            connection.fileno.return_value = 42
            start.side_effect = lambda *args, **kwargs: (connection.close.assert_not_called(), qemu)[1]
            self.launch()
        connection.connect.assert_called_once_with('/run/virter-passt.sock')
        start.assert_called_once()
        command = start.call_args.args[0]
        self.assertEqual(start.call_args.kwargs['pass_fds'], (42,))
        self.assertIn('stream,id=net0,addr.type=fd,addr.str=42', command)
        self.assertIn('virtio-net-pci,netdev=net0', command)
        self.assertNotIn('--share-net', command)
        self.assertNotIn('/etc/resolv.conf', command)
        self.assertIn('--disable-userns', command)
        self.assertNotIn('-nic', command)
        connection.close.assert_called()

    def test_other_network_modes_pass_no_descriptors(self):
        for network in (v['NetworkMode'].NONE, v['NetworkMode'].HOST):
            qemu = Mock()
            qemu.wait.return_value = 0
            with self.subTest(network=network), \
                    patch.dict(v['run_vm'].__globals__, relay_output=Mock()), \
                    patch('subprocess.Popen', return_value=qemu) as start, \
                    patch('socket.socket') as sock:
                v['run_vm']('safe', 'uuid', Path('/cache/instance/disk.img'), Path('/cache/instance'),
                            1024, network, False, [], True, Path('/cache/base.img'))
                sock.assert_not_called()
                self.assertEqual(start.call_args.kwargs['pass_fds'], ())

    def test_unavailable_backend_aborts_before_any_child(self):
        for error in (FileNotFoundError(), PermissionError(), ConnectionRefusedError(), TimeoutError()):
            with self.subTest(error=error), patch('subprocess.Popen') as start, \
                    patch('socket.socket') as sock, self.assertRaises(SystemExit) as caught:
                sock.return_value.connect.side_effect = error
                self.launch()
            self.assertIn('NETWORKING.md', str(caught.exception))
            sock.return_value.close.assert_called()
            start.assert_not_called()

    def test_qemu_start_failure_closes_backend_socket(self):
        with patch('subprocess.Popen', side_effect=OSError('no qemu')), \
                patch('socket.socket') as sock, self.assertRaises(OSError):
            sock.return_value.__enter__.return_value = sock.return_value
            self.launch()
        sock.return_value.__exit__.assert_called_once()

    def test_socket_restricts_access_and_spawns_per_connection(self):
        socket_unit = unit('virter-passt.socket')['Socket']
        self.assertEqual(socket_unit['ListenStream'], v['BRIDGE_SOCKET'])
        self.assertEqual(socket_unit['Accept'], 'yes')
        self.assertEqual(socket_unit['SocketGroup'], 'virter-bridge')
        self.assertEqual(socket_unit['SocketMode'], '0660')

    def test_service_installs_policy_before_passt_as_dedicated_account(self):
        service = unit('virter-passt@.service')['Service']
        self.assertEqual(service['User'], 'virter-passt')
        self.assertNotIn('AppArmorProfile', service)
        self.assertNotIn('StandardInput', service)
        self.assertEqual(service['ExecStartPre'],
                         '+/usr/sbin/nft -f /usr/local/share/virter/virter-bridge.nft')

    def test_passt_disables_host_aliases_and_inbound_forwarding(self):
        args = unit('virter-passt@.service')['Service']['ExecStart'].split()
        # Accept=yes passes the connection as fd 3; passt refuses fd 0.
        self.assertEqual(args[:5], ['/usr/bin/passt', '--foreground', '--one-off', '--fd', '3'])
        for option in ('--map-host-loopback', '--map-guest-addr', '--tcp-ports', '--udp-ports'):
            self.assertEqual(args[args.index(option) + 1], 'none')
        self.assertIn('--no-map-gw', args)
        self.assertIn('--no-dhcp-search', args)
        self.assertEqual(args[args.index('--dns') + 1], '1.1.1.1')

    def test_policy_replaces_table_atomically(self):
        lines = [line.strip() for line in (ROOT / 'network' / 'virter-bridge.nft').read_text().splitlines()
                 if line.strip() and not line.startswith('#')]
        self.assertEqual(lines[:2], ['destroy table inet virter_bridge', 'table inet virter_bridge {'])
        self.assertIn('meta skuid "virter-passt" fib daddr type local drop', lines)
        self.assertIn('meta skuid "virter-passt" meta mark set 0x76527472', lines)
        self.assertIn('meta mark 0x76527472 drop', lines)


if __name__ == '__main__':
    unittest.main()
