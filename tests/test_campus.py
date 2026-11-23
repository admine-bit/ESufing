import base64
import json
import os
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import requests

from esurfingpy.campus import byod_login, encode_byod_password, probe, redirect_url
from esurfingpy.cdc import CDCClient, portal_config, zsm_algorithm
from esurfingpy.config import Config, load_config
from esurfingpy.esurfing import parse_parameters
from esurfingpy.http import create_session


class Handler(BaseHTTPRequestHandler):
    records = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/online")
            self.end_headers()
        elif self.path == "/online":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html>campus login</html>")

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.records.append((self.path, body, self.headers.get("CDC-SchoolId")))
        if self.path == "/ticket":
            self.send_response(302)
            self.send_header("Location", "/routed-ticket")
            self.send_header("schoolid", "test-school")
            self.end_headers()
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"test-ticket")


class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_proxy_is_bypassed_and_requests_use_selected_device(self):
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "NO_PROXY": ""}):
            with create_session("lo") as session:
                self.assertFalse(session.trust_env)
                adapter = session.get_adapter(self.base)
                self.assertIn((socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b"lo\0"),
                              adapter.poolmanager.connection_pool_kw["socket_options"])
                self.assertEqual(session.get(self.base, timeout=2).status_code, 200)

    def test_online_check_rejects_login_pages_and_redirected_204(self):
        with create_session("lo") as session:
            for path, expected in (("/login", False), ("/redirect", False), ("/online", True)):
                with self.subTest(path=path), patch("esurfingpy.campus.CAPTIVE_URL", self.base + path):
                    self.assertEqual(probe(session, Config(timeout=2))[0], expected)

    def test_cdc_redirect_preserves_post_and_routing_headers(self):
        Handler.records.clear()
        with create_session("lo") as session:
            client = CDCClient(session, Config(timeout=2))
            self.assertEqual(client.post(self.base + "/ticket", "test-body"), b"test-ticket")
        self.assertEqual(Handler.records, [
            ("/ticket", b"test-body", None),
            ("/routed-ticket", b"test-body", "test-school"),
        ])


class ParsingTests(unittest.TestCase):
    def test_js_redirect_keeps_all_query_parameters(self):
        response = requests.Response()
        response.url = "http://189.cn/"
        response._content = b'<script>location.href="http://172.17.18.2:30004/byod/index.html?userip=1&usermac=2"</script>'
        self.assertEqual(redirect_url(response), "http://172.17.18.2:30004/byod/index.html?userip=1&usermac=2")

    def test_credentials_are_not_posted_to_unknown_byod_host(self):
        response = requests.Response()
        response.url = "http://unknown.invalid/byod/index.html"
        response._content = b"login"
        with create_session() as session, patch.object(session, "post") as post:
            with self.assertRaisesRegex(ValueError, "未知"):
                byod_login(session, Config(username="test", password="secret"), response)
            post.assert_not_called()

    def test_portal_config_handles_real_world_unescaped_ampersands(self):
        body = '<!--//config.campus.js.chinatelecom.com <config><ticket-url><![CDATA[http://example.test/ticket?wlanuserip=1&wlanacip=2]]></ticket-url><auth-url>http://example.test/auth</auth-url><broken url="a&b"/></config>//config.campus.js.chinatelecom.com-->'
        self.assertEqual(portal_config(body)["ticket_url"], "http://example.test/ticket?wlanuserip=1&wlanacip=2")
        self.assertIsNone(portal_config("normal web page"))

    def test_legacy_parameter_order_and_trailing_fields(self):
        self.assertEqual(parse_parameters("http://portal.test/?wlanuserip=1&wlanacip=2&extra=3"),
                         (True, "portal.test", "2", "1"))

    def test_zsm_header_and_truncation(self):
        algorithm = b"9ABF4D29-34DB-4CE9-BB8C-7E371D637758"
        packet = b"001\x03key\x24" + algorithm + b"remainder"
        self.assertEqual(zsm_algorithm(packet), algorithm.decode())
        for data in (b"", b"001\xff", b"001\x03key\x24short"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                zsm_algorithm(data)

    def test_byod_password_matches_browser_escaping(self):
        self.assertEqual(encode_byod_password("a\\中😀"),
                         base64.b64encode(b"a\\\\\\u4E2D\\uD83D\\uDE00").decode())

    def test_private_config_is_loaded_outside_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text("[account]\nusername=test\npassword=percent%value\n[runtime]\nmode=keepalive\n")
            config = load_config(path)
            self.assertEqual(config.password, "percent%value")
            self.assertNotIn("percent%value", repr(config))

    def test_failed_restore_does_not_prevent_existing_network_use(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            state.write_text(json.dumps({"interface": "another-adapter"}))
            with create_session() as session, patch("esurfingpy.cdc.state_file", return_value=state):
                self.assertIsNone(CDCClient.restore(session, Config(interface="lo")))

    def test_usb_and_pcie_profiles_share_credentials_but_select_own_interface(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.ini"
            path.write_text("[account]\nusername=test\npassword=secret\n[usb]\ninterface=usb-test\n[pcie]\ninterface=pcie-test\n")
            usb = load_config(path, "usb")
            pcie = load_config(path, "pcie")
            self.assertEqual(usb.interface, "usb-test")
            self.assertEqual(pcie.interface, "pcie-test")
            self.assertEqual((usb.username, usb.password), (pcie.username, pcie.password))


if __name__ == "__main__":
    unittest.main()
