import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

import dns.exception
import requests

from esurfingpy.campus import connect, probe
from esurfingpy.config import Config
from esurfingpy.dns import InterfaceResolver
from esurfingpy.http import create_session


def response(url, status=204, body="", headers=None):
    result = requests.Response()
    result.url = url
    result.status_code = status
    result._content = body.encode()
    result.headers.update(headers or {})
    return result


class ProbeFallbackTests(unittest.TestCase):
    def test_dns_failure_uses_numeric_address_and_keeps_probe_host(self):
        session = Mock()
        session.get.side_effect = [requests.ConnectionError("DNS failed"),
                                   response("http://220.181.104.183/generate_204")]
        online, result = probe(session, Config())
        self.assertTrue(online)
        call = session.get.call_args_list[1]
        self.assertEqual(call.args[0], "http://220.181.104.183/generate_204")
        self.assertEqual(call.kwargs["headers"]["Host"], "connect.rom.miui.com")
        self.assertFalse(call.kwargs["allow_redirects"])

    def test_dead_first_ip_uses_next_candidate(self):
        session = Mock()
        session.get.side_effect = [requests.ConnectionError(), requests.ConnectTimeout(),
                                   response("http://202.69.4.32/generate_204")]
        self.assertTrue(probe(session, Config())[0])
        self.assertEqual(session.get.call_count, 3)

    def test_login_page_and_unexpected_204_do_not_count_as_online(self):
        for result in (response("http://220.181.104.183/generate_204", 200, "login page"),
                       response("http://another.test/", 204)):
            with self.subTest(result=result.url):
                session = Mock()
                session.get.side_effect = [requests.ConnectionError(), result]
                with self.assertRaises(requests.ConnectionError):
                    probe(session, Config(probe_ipv4=("220.181.104.183",)))

    def test_portal_redirect_does_not_reuse_probe_host_header(self):
        portal = response("http://enet.10000.gd.cn:10001/", 200, "campus login page")
        session = Mock()
        session.get.side_effect = [requests.ConnectionError(),
                                   response("http://220.181.104.183/generate_204", 302,
                                            headers={"Location": portal.url}), portal]
        online, actual = probe(session, Config())
        self.assertFalse(online)
        self.assertIs(actual, portal)
        self.assertNotIn("Host", session.get.call_args_list[2].kwargs["headers"])

    def test_byod_javascript_redirect_is_returned_for_school_authentication(self):
        page = response("http://220.181.104.183/generate_204", 200,
                        '<script>location.href="http://172.17.18.2:30004/byod/index.html?userip=1&usermac=2"</script>')
        session = Mock()
        session.get.side_effect = [requests.ConnectionError(), page]
        self.assertEqual(probe(session, Config()), (False, page))

    def test_only_explicitly_configured_portal_has_ip_fallback(self):
        resolver = InterfaceResolver("lo", host_fallbacks={"enet.test": ("127.0.0.1",)})
        with patch.object(resolver, "network", return_value=("127.0.0.1", ("192.0.2.1",))), \
                patch("dns.query.udp", side_effect=dns.exception.Timeout):
            self.assertEqual(resolver.resolve("enet.test"), ("127.0.0.1",))
            with self.assertRaises(socket.gaierror):
                resolver.resolve("unknown.test")

    def test_complete_portal_discovery_and_login_when_all_dns_queries_fail(self):
        class Handler(BaseHTTPRequestHandler):
            authenticated = False
            hosts = []

            def log_message(self, *args):
                pass

            def do_GET(self):
                self.hosts.append(self.headers["Host"])
                if self.path == "/generate_204":
                    if self.authenticated:
                        self.send_response(204)
                    else:
                        self.send_response(302)
                        self.send_header("Location", f"http://enet.test:{self.server.server_port}/portal")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'<!--//config.campus.js.chinatelecom.com <config><ticket-url><![CDATA[http://127.0.0.1/ticket?wlanuserip=1&wlanacip=2]]></ticket-url><auth-url>http://127.0.0.1/auth</auth-url></config>//config.campus.js.chinatelecom.com-->')

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = Mock()
        client.login.side_effect = lambda *args: setattr(Handler, "authenticated", True)
        captive = f"http://probe.test:{server.server_port}/generate_204"
        try:
            with create_session("lo", host_fallbacks={"enet.test": ("127.0.0.1",)}) as session, \
                    patch("esurfingpy.campus.CAPTIVE_URL", captive), \
                    patch("esurfingpy.campus.ensure_wifi"), \
                    patch("esurfingpy.campus.CDCClient", return_value=client), \
                    patch("esurfingpy.dns.InterfaceResolver.network", return_value=("127.0.0.1", ("192.0.2.1",))), \
                    patch("dns.query.udp", side_effect=dns.exception.Timeout):
                config = Config(interface="lo", username="test", password="test", probe_ipv4=("127.0.0.1",))
                self.assertIs(connect(session, config), client)
            client.login.assert_called_once()
            self.assertEqual(Handler.hosts, [f"probe.test:{server.server_port}",
                                            f"enet.test:{server.server_port}",
                                            f"probe.test:{server.server_port}"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
