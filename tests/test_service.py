import subprocess
import unittest
from unittest.mock import Mock, patch

from esurfingpy.config import Config, ROOT
from esurfingpy.service import UNIT, start, stop, status


class BackgroundServiceTests(unittest.TestCase):
    def test_keepalive_runs_as_detached_user_service_without_credentials_in_args(self):
        config = Config(username="private-user", password="private-password", mode="keepalive")
        with patch("esurfingpy.service.load_config", return_value=config), \
                patch("esurfingpy.service.unit_loaded", return_value=False), \
                patch("esurfingpy.service.subprocess.run") as run:
            self.assertEqual(start(), 0)
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["systemd-run", "--user"])
        self.assertIn(f"--unit={UNIT}", command)
        self.assertIn(f"--working-directory={ROOT}", command)
        self.assertIn("--setenv=ESURFING_PROFILE=pcie", command)
        self.assertIn("--property=Restart=always", command)
        self.assertIn("--property=RestartPreventExitStatus=2", command)
        self.assertNotIn("--pty", command)
        self.assertNotIn("--scope", command)
        self.assertNotIn(config.username, " ".join(command))
        self.assertNotIn(config.password, " ".join(command))

    def test_starting_existing_service_restarts_it_without_duplicate_process(self):
        with patch("esurfingpy.service.load_config", return_value=Config()), \
                patch("esurfingpy.service.unit_loaded", return_value=True), \
                patch("esurfingpy.service.subprocess.run") as run:
            self.assertEqual(start(), 0)
        run.assert_called_once_with(["systemctl", "--user", "restart", UNIT], check=True, timeout=30)

    def test_explicit_single_login_remains_foreground(self):
        with patch("esurfingpy.service.load_config", return_value=Config(mode="login")), \
                patch("esurfingpy.service.unit_loaded") as loaded, \
                patch("esurfingpy.service.subprocess.run", return_value=subprocess.CompletedProcess([], 7)) as run:
            self.assertEqual(start(), 7)
        loaded.assert_not_called()
        self.assertEqual(run.call_args.args[0][-1], str(ROOT / "main.py"))
        self.assertEqual(run.call_args.kwargs["env"]["ESURFING_PROFILE"], "pcie")

    def test_stop_uses_service_manager_and_does_not_touch_network_devices(self):
        with patch("esurfingpy.service.unit_loaded", return_value=True), \
                patch("esurfingpy.service.subprocess.run") as run:
            self.assertEqual(stop(), 0)
        run.assert_called_once_with(["systemctl", "--user", "stop", UNIT], check=True, timeout=30)

    def test_status_reports_stopped_service(self):
        with patch("esurfingpy.service.unit_loaded", return_value=False), \
                patch("esurfingpy.service.subprocess.run") as run:
            self.assertEqual(status(), 3)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
