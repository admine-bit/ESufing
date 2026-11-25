import logging
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from esurfingpy.campus import connect_until_ready, prioritize_campus
from esurfingpy.config import Config
from esurfingpy.log import PrivateRotatingFileHandler


def reply(value):
    return subprocess.CompletedProcess([], 0, stdout=value, stderr="")


class CampusRouteTests(unittest.TestCase):
    def test_only_authenticated_campus_profile_is_promoted(self):
        config = Config(interface="pcie-test", ssid="campus-test", route_metric=100)
        with patch("esurfingpy.campus.nmcli", side_effect=[reply("campus-uuid"), reply("campus-test"),
                                                          reply("2000"), reply(""), reply("")]) as nm:
            prioritize_campus(config)
        self.assertEqual([call.args for call in nm.call_args_list if call.args[0] != "-g"], [
            ("connection", "modify", "uuid", "campus-uuid", "ipv4.route-metric", "100"),
            ("device", "reapply", "pcie-test"),
        ])

    def test_other_wifi_is_never_modified(self):
        config = Config(interface="pcie-test", ssid="campus-test")
        with patch("esurfingpy.campus.nmcli", side_effect=[reply("hotspot-uuid"), reply("MyHotspot")]) as nm:
            with self.assertRaises(requests.ConnectionError):
                prioritize_campus(config)
        self.assertTrue(all(call.args[0] == "-g" for call in nm.call_args_list))

    def test_existing_metric_needs_no_network_reapply(self):
        with patch("esurfingpy.campus.nmcli", side_effect=[reply("campus-uuid"), reply("campus-test"), reply("100")]) as nm:
            prioritize_campus(Config(interface="pcie-test", ssid="campus-test"))
        self.assertEqual(nm.call_count, 3)


class KeepaliveRecoveryTests(unittest.TestCase):
    def test_keepalive_continues_after_initial_retry_batch_is_exhausted(self):
        client = object()
        with patch("esurfingpy.campus.connect_with_retry", side_effect=[requests.ConnectionError("offline"), client]) as connect, \
                patch("esurfingpy.campus.time.sleep") as sleep:
            self.assertIs(connect_until_ready(Mock(), Config(mode="keepalive", interval=3)), client)
        self.assertEqual(connect.call_count, 2)
        sleep.assert_called_once_with(3)

    def test_one_shot_login_preserves_failure_exit_behavior(self):
        with patch("esurfingpy.campus.connect_with_retry", side_effect=requests.ConnectionError("offline")) as connect:
            with self.assertRaises(requests.ConnectionError):
                connect_until_ready(Mock(), Config(mode="login"))
        connect.assert_called_once()

    def test_invalid_credentials_do_not_trigger_endless_retries(self):
        with patch("esurfingpy.campus.connect_with_retry", side_effect=ValueError("password rejected")) as connect:
            with self.assertRaises(ValueError):
                connect_until_ready(Mock(), Config(mode="keepalive"))
        connect.assert_called_once()


class DiagnosticLogTests(unittest.TestCase):
    def test_current_and_rotated_logs_remain_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campus.log"
            handler = PrivateRotatingFileHandler(path, maxBytes=80, backupCount=2, encoding="utf-8")
            try:
                for number in range(8):
                    handler.emit(logging.LogRecord("test", logging.WARNING, __file__, 1,
                                                   "network recovery event %s", (number,), None))
            finally:
                handler.close()
            files = list(Path(directory).glob("campus.log*"))
            self.assertGreater(len(files), 1)
            for file in files:
                self.assertEqual(file.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
