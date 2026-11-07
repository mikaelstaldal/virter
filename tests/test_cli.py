import runpy
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


v = runpy.run_path(str(Path(__file__).resolve().parents[1] / "virter"))


class CommandBoundaryTests(unittest.TestCase):
    def parse(self, arguments):
        dispatch = Mock()
        with patch.dict(v["main"].__globals__, supervise=dispatch), \
                patch("sys.argv", ["virter", *arguments]), \
                patch("os.getuid", return_value=1000), patch("os.geteuid", return_value=1000), \
                patch("shutil.which", return_value="/usr/bin/bwrap"):
            v["main"]()
        return dispatch.call_args.args[0]

    def test_command_arguments_cannot_override_policy(self):
        injected = [
            "--network=host", "--network", "host", "--mount-writable=/home/me",
            "--mount-w=/home/me", "-n../../evil", "-b../../evil", "-m999999",
            "-w/tmp", "--timeout=86400", "--sudo", "--help", "--", "", "tail",
        ]
        for action in ("run", "update"):
            for separator in ([], ["--"]):
                for suffix in ([], ["tail"]):
                    with self.subTest(action=action, separator=separator, suffix=suffix):
                        args = self.parse([action, "--network", "none", *separator, "./test.sh",
                                           *injected, *suffix])
                        self.assertEqual(args.network, "none")
                        self.assertEqual(args.base, "base")
                        self.assertEqual(args.memory, 1024)
                        self.assertEqual(args.timeout, 3600)
                        self.assertEqual(args.COMMAND, ["./test.sh", *injected, *suffix])
                        if action == "run":
                            self.assertEqual(args.mount_writable, [])
                            self.assertIsNone(args.workdir)
                        else:
                            self.assertFalse(args.sudo)

    def test_interactive_and_explicit_separator(self):
        for action in ("run", "update"):
            for tail in ([], ["--"]):
                with self.subTest(action=action, tail=tail):
                    self.assertEqual(self.parse([action, *tail]).COMMAND, [])
            self.assertEqual(self.parse([action, "--", "--", "arg"]).COMMAND, ["--", "arg"])

    def test_empty_command_rejected_before_launch(self):
        for action in ("run", "update"):
            for separator in ([], ["--"]):
                dispatch = Mock()
                with self.subTest(action=action, separator=separator), \
                        patch("sys.argv", ["virter", action, *separator, "", "evil"]), \
                        patch("sys.stderr"), patch.dict(v["main"].__globals__, supervise=dispatch), \
                        self.assertRaises(SystemExit) as error:
                    v["main"]()
                self.assertEqual(error.exception.code, 2)
                dispatch.assert_not_called()
