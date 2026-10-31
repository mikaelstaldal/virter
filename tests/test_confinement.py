import contextlib
import io
from pathlib import Path
import runpy
import subprocess
import unittest
from unittest.mock import patch


v = runpy.run_path(str(Path(__file__).resolve().parents[1] / "virter"))


class ConfinementTests(unittest.TestCase):
    def test_root_and_missing_bubblewrap_refused_before_work(self):
        for uid, euid, bwrap in ((0, 0, "/usr/bin/bwrap"), (1000, 0, "/usr/bin/bwrap"),
                                  (0, 1000, "/usr/bin/bwrap"), (1000, 1000, None)):
            for arguments in (["run"], ["update"], ["prepare", "-i", "image", "--sha256", "a" * 64]):
                with self.subTest(uid=uid, euid=euid, bwrap=bwrap, arguments=arguments), \
                        patch("os.getuid", return_value=uid), patch("os.geteuid", return_value=euid), \
                        patch("shutil.which", return_value=bwrap), patch("subprocess.run") as command, \
                        patch("pathlib.Path.mkdir") as mkdir, patch("sys.argv", ["virter", *arguments]), \
                        contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    v["main"]()
                self.assertEqual(error.exception.code, 2)
                command.assert_not_called()
                mkdir.assert_not_called()

    def test_preflight_failure_prevents_image_work(self):
        with patch("os.getuid", return_value=1000), patch("os.geteuid", return_value=1000), \
                patch("shutil.which", return_value="/usr/bin/bwrap"), \
                patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "bwrap", stderr="denied")), \
                patch.dict(v["main"].__globals__, run=lambda args: self.fail("run must not be called")), \
                patch("sys.argv", ["virter", "run"]), contextlib.redirect_stderr(io.StringIO()) as stderr, \
                self.assertRaises(SystemExit) as error:
            v["main"]()
        self.assertEqual(error.exception.code, 2)
        self.assertIn("confinement preflight failed: denied", stderr.getvalue())

    def test_ephemeral_launch_exposes_only_selected_images(self):
        with patch("subprocess.run") as command:
            v["run_vm"]("safe", "uuid", Path("/cache/instance/disk.img"), Path("/cache/instance"),
                        1024, v["NetworkMode"].NONE, False, [], True, Path("/cache/base.img"))
        args = command.call_args.args[0]
        self.assertEqual(args[0], "bwrap")
        for option in ("--unshare-all", "--clearenv", "--die-with-parent",
                       "--disable-userns", "--assert-userns-disabled"):
            self.assertIn(option, args)
        self.assertNotIn("--share-net", args)
        bind_sources = [args[i + 1] for i, arg in enumerate(args)
                        if arg in ("--bind", "--ro-bind", "--ro-bind-try", "--dev-bind")]
        self.assertEqual(bind_sources, ["/usr", "/lib64", "/dev/kvm", "/cache/base.img", "/cache/instance"])
        self.assertNotIn(str(Path.home()), args)
        index = args.index("/cache/base.img")
        self.assertEqual(args[index - 1:index + 2], ["--ro-bind", "/cache/base.img", "/cache/base.img"])
        self.assertIn("on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny", args)
        self.assertEqual(args[args.index("--") + 1], "/usr/bin/qemu-system-x86_64")
        self.assertTrue(command.call_args.kwargs["check"])

    def test_mount_uses_socket_without_exposing_shared_directory_to_qemu(self):
        with patch("subprocess.run") as command, patch("subprocess.Popen") as daemon, \
                patch.dict(v["run_vm"].__globals__, wait_for_socket=lambda *args: None):
            v["run_vm"]("safe", "uuid", Path("/cache/instance/disk.img"), Path("/cache/instance"),
                        1024, v["NetworkMode"].NONE, False, [(Path("/home/user/shared"), True)], True,
                        Path("/cache/base.img"))
        args = command.call_args.args[0]
        self.assertNotIn("/home/user/shared", args)
        self.assertIn("socket,id=char0,path=/cache/instance/vhostqemu0", args)
        self.assertIn("memory-backend-file,id=mem,size=1024M,mem-path=/dev/shm,share=on", args)
        self.assertIn("--readonly", daemon.call_args.args[0])
        daemon.return_value.terminate.assert_called_once()
        daemon.return_value.wait.assert_called_once()

    def test_update_exposes_writable_base_and_host_dns(self):
        args = v["qemu_confinement"](Path("/cache/base.img"), Path("/tmp/instance"),
                                       v["NetworkMode"].HOST, None)
        index = args.index("/cache/base.img")
        self.assertEqual(args[index - 1:index + 2], ["--bind", "/cache/base.img", "/cache/base.img"])
        self.assertIn("--share-net", args)
        self.assertIn("/etc/resolv.conf", args)

    def test_sandbox_failure_does_not_retry_unconfined(self):
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "bwrap")) as command, \
                self.assertRaises(subprocess.CalledProcessError):
            v["run_vm"]("safe", "uuid", Path("/cache/base.img"), Path("/tmp/instance"),
                        1024, v["NetworkMode"].NONE, False, [], False)
        command.assert_called_once()


if __name__ == "__main__":
    unittest.main()
