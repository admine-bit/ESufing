import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from esurfingpy.campus import keep_usb_off_campus
from esurfingpy.config import Config
from esurfingpy.processes import coordinate_clients, project_clients


def config(interface="pcie-test"):
    return Config(interface=interface, pcie_interface="pcie-test",
                  usb_interface="usb-test", ssid="campus-test")


def reply(text="", code=0):
    return subprocess.CompletedProcess([], code, stdout=text, stderr="")


class USBNetworkPolicyTests(unittest.TestCase):
    def test_other_usb_wifi_is_read_only(self):
        with patch("esurfingpy.campus.nmcli", side_effect=[reply("hotspot-uuid"), reply("MyHotspot")]) as nm:
            keep_usb_off_campus(config())
        self.assertEqual(len(nm.call_args_list), 2)
        for call in nm.call_args_list:
            self.assertEqual(call.args[0], "-g")

    def test_disconnected_usb_is_left_disconnected(self):
        with patch("esurfingpy.campus.nmcli", return_value=reply("--")) as nm:
            keep_usb_off_campus(config())
        nm.assert_called_once_with("-g", "GENERAL.CON-UUID,GENERAL.CON-PATH", "device", "show", "usb-test", check=False)

    def test_missing_usb_does_not_affect_pcie(self):
        with patch("esurfingpy.campus.nmcli", return_value=reply(code=10)) as nm:
            keep_usb_off_campus(config())
        self.assertEqual(nm.call_count, 1)

    def test_only_confirmed_campus_connection_is_disconnected(self):
        apath = "/org/freedesktop/NetworkManager/ActiveConnection/42"
        active = "campus-uuid\n" + apath
        replies = [reply(active), reply("campus-test"), reply(), reply(active), reply()]
        with patch("esurfingpy.campus.nmcli", side_effect=replies) as nm:
            keep_usb_off_campus(config())
        mutations = [call.args for call in nm.call_args_list if call.args[0] != "-g"]
        self.assertEqual(mutations, [
            ("connection", "modify", "campus-uuid", "connection.autoconnect", "no"),
            ("--wait", "10", "connection", "down", "apath", apath),
        ])

    def test_switch_to_hotspot_during_check_never_disconnects_new_network(self):
        active = "campus-uuid\n/org/freedesktop/NetworkManager/ActiveConnection/42"
        replies = [reply(active), reply("campus-test"), reply(), reply("hotspot-uuid")]
        with patch("esurfingpy.campus.nmcli", side_effect=replies) as nm:
            keep_usb_off_campus(config())
        self.assertFalse(any("down" in call.args for call in nm.call_args_list))

    def test_reactivated_profile_does_not_disconnect_a_new_active_connection(self):
        original = "shared-campus-uuid\n/org/freedesktop/NetworkManager/ActiveConnection/42"
        current = "shared-campus-uuid\n/org/freedesktop/NetworkManager/ActiveConnection/43"
        with patch("esurfingpy.campus.nmcli", side_effect=[reply(original), reply("campus-test"), reply(), reply(current)]) as nm:
            keep_usb_off_campus(config())
        self.assertFalse(any("down" in call.args for call in nm.call_args_list))

    def test_usb_mode_does_not_apply_pcie_policy(self):
        with patch("esurfingpy.campus.nmcli") as nm:
            keep_usb_off_campus(config("usb-test"))
        nm.assert_not_called()


class ClientCoordinationTests(unittest.TestCase):
    def test_pcie_stops_only_this_projects_usb_and_duplicate_pcie_clients(self):
        usb, pcie, unrelated = Mock(pid=11), Mock(pid=12), Mock(pid=13)
        with tempfile.TemporaryDirectory() as directory, \
                patch("esurfingpy.processes.START_LOCK", Path(directory) / "start.lock"), \
                patch("esurfingpy.processes.project_clients", return_value=[
                    (usb, "usb-test"), (pcie, "pcie-test"), (unrelated, "another-interface")]), \
                patch("esurfingpy.processes.stop_client") as stop:
            with coordinate_clients(config()):
                pass
        self.assertEqual([call.args[0] for call in stop.call_args_list], [usb, pcie])

    def test_usb_cannot_restart_campus_while_pcie_client_is_running(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("esurfingpy.processes.START_LOCK", Path(directory) / "start.lock"), \
                patch("esurfingpy.processes.project_clients", return_value=[(Mock(pid=12), "pcie-test")]), \
                patch("esurfingpy.processes.stop_client") as stop:
            with self.assertRaisesRegex(ValueError, "不能同时启动 USB"):
                with coordinate_clients(config("usb-test")):
                    self.fail("USB client must not start")
        stop.assert_not_called()

    def test_scan_ignores_other_projects_gui_and_non_python_commands(self):
        from esurfingpy.config import ROOT
        processes = []
        for index, (cwd, args) in enumerate([
            (str(ROOT), ["python3", "main.py"]),
            ("/tmp/another-project", ["python3", "main.py"]),
            (str(ROOT), ["python3", "main.py", "gui"]),
            (str(ROOT), ["node", "main.py"]),
        ]):
            process = Mock(pid=100000 + index)
            process.info = {"cwd": cwd, "cmdline": args}
            process.uids.return_value = Mock(real=os.getuid())
            process.environ.return_value = {"ESURFING_PROFILE": "usb"}
            processes.append(process)
        with patch("esurfingpy.processes.psutil.process_iter", return_value=processes), \
                patch("esurfingpy.processes.load_config", return_value=config("usb-test")):
            self.assertEqual(project_clients(), [(processes[0], "usb-test")])


if __name__ == "__main__":
    unittest.main()
