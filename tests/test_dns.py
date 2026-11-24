import ipaddress
import socket
import subprocess
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import Mock, patch

import dns.message
import dns.rcode
import dns.rdatatype
import dns.rrset
import requests

from esurfingpy.campus import connect_with_retry
from esurfingpy.config import Config
from esurfingpy.dns import InterfaceResolver
from esurfingpy.http import create_session, interface_pools


def answer(address="127.0.0.1"):
    response = dns.message.make_response(dns.message.make_query("portal.test", dns.rdatatype.A))
    response.answer.append(dns.rrset.from_text("portal.test.", 60, "IN", "A", address))
    return response


class InterfaceDNSTests(unittest.TestCase):
    def test_query_is_bound_to_selected_interface_and_dhcp_source_address(self):
        resolver = InterfaceResolver("pcie-test")
        sock = Mock()
        sock.__enter__ = Mock(return_value=sock)
        sock.__exit__ = Mock(return_value=False)
        with patch.object(resolver, "network", return_value=("100.2.1.2", ("202.96.128.166",))), \
                patch("esurfingpy.dns.socket.socket", return_value=sock), \
                patch("esurfingpy.dns.dns.query.udp", return_value=answer("203.0.113.2")) as query:
            self.assertEqual(resolver.resolve("portal.test"), ("203.0.113.2",))
        sock.setsockopt.assert_called_once_with(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b"pcie-test\0")
        sock.bind.assert_called_once_with(("100.2.1.2", 0))
        self.assertEqual(query.call_args.kwargs["sock"], sock)

    def test_unavailable_dhcp_dns_uses_configured_fallback(self):
        resolver = InterfaceResolver("lo", ("202.96.128.86",))
        with patch.object(resolver, "network", return_value=("127.0.0.1", ("192.0.2.1", "202.96.128.86"))), \
                patch("esurfingpy.dns.dns.query.udp", side_effect=[TimeoutError(), answer()]) as query:
            self.assertEqual(resolver.resolve("portal.test"), ("127.0.0.1",))
        self.assertEqual([call.args[1] for call in query.call_args_list], ["192.0.2.1", "202.96.128.86"])

    def test_dhcp_dns_is_read_only_and_precedes_fallback(self):
        resolver = InterfaceResolver("pcie-test", ("202.96.128.166", "202.96.128.86"))
        address = Mock(family=socket.AF_INET, address="100.2.1.2")
        with patch("esurfingpy.dns.net_if_addrs", return_value={"pcie-test": [address]}), \
                patch("esurfingpy.dns.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "192.0.2.1 | 202.96.128.166\n")) as command:
            self.assertEqual(resolver.network(), ("100.2.1.2", ("192.0.2.1", "202.96.128.166", "202.96.128.86")))
        self.assertEqual(command.call_args.args[0], ["nmcli", "-g", "IP4.DNS", "device", "show", "pcie-test"])

    def test_cache_is_invalidated_when_dhcp_address_changes(self):
        resolver = InterfaceResolver("lo")
        networks = [("127.0.0.1", ("192.0.2.1",)), ("127.0.0.1", ("192.0.2.1",)), ("127.0.0.2", ("192.0.2.1",))]
        with patch.object(resolver, "network", side_effect=networks), \
                patch("esurfingpy.dns.dns.query.udp", side_effect=[answer("203.0.113.1"), answer("203.0.113.2")]) as query:
            self.assertEqual(resolver.resolve("portal.test"), ("203.0.113.1",))
            self.assertEqual(resolver.resolve("portal.test"), ("203.0.113.1",))
            self.assertEqual(resolver.resolve("portal.test"), ("203.0.113.2",))
        self.assertEqual(query.call_count, 2)

    def test_ip_literal_needs_no_dns(self):
        resolver = InterfaceResolver("lo")
        with patch.object(resolver, "network") as network:
            self.assertEqual(resolver.resolve("127.0.0.1"), ("127.0.0.1",))
        network.assert_not_called()

    def test_host_header_is_preserved_without_system_name_resolution(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(self.headers["Host"].encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        original = socket.getaddrinfo

        def broken_system_dns(host, *args, **kwargs):
            try:
                ipaddress.ip_address(host)
            except ValueError:
                raise socket.gaierror(socket.EAI_AGAIN, "simulated system DNS failure")
            return original(host, *args, **kwargs)

        try:
            with create_session("lo") as session, \
                    patch("esurfingpy.dns.InterfaceResolver.network", return_value=("127.0.0.1", ("192.0.2.1",))), \
                    patch("esurfingpy.dns.dns.query.udp", return_value=answer()), \
                    patch("socket.getaddrinfo", side_effect=broken_system_dns):
                response = session.get(f"http://portal.test:{server.server_port}/", timeout=2)
                self.assertEqual(response.text, f"portal.test:{server.server_port}")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_https_connection_keeps_original_hostname_for_sni_and_verification(self):
        resolver = Mock()
        resolver.resolve.return_value = ("203.0.113.1",)
        connection = interface_pools(resolver)["https"].ConnectionCls("portal.test", 443)
        with patch("esurfingpy.http.create_connection", return_value=Mock()) as new_socket:
            connection._new_conn()
        self.assertEqual(new_socket.call_args.args[0], ("203.0.113.1", 443))
        self.assertEqual(connection.host, "portal.test")
        self.assertEqual(connection._dns_host, "portal.test")


class StartupRetryTests(unittest.TestCase):
    def test_temporary_dns_failure_does_not_exit_on_first_attempt(self):
        client = object()
        with patch("esurfingpy.campus.connect", side_effect=[requests.ConnectionError("DNS unavailable"), client]) as connect, \
                patch("esurfingpy.campus.time.sleep") as sleep:
            self.assertIs(connect_with_retry(Mock(), Config(startup_retries=3)), client)
        self.assertEqual(connect.call_count, 2)
        sleep.assert_called_once_with(5)

    def test_network_retries_stop_at_configured_limit(self):
        with patch("esurfingpy.campus.connect", side_effect=requests.ConnectionError("offline")) as connect, \
                patch("esurfingpy.campus.time.sleep"):
            with self.assertRaises(requests.ConnectionError):
                connect_with_retry(Mock(), Config(startup_retries=2))
        self.assertEqual(connect.call_count, 2)

    def test_authentication_errors_are_not_retried_as_dns_failures(self):
        with patch("esurfingpy.campus.connect", side_effect=ValueError("password rejected")) as connect:
            with self.assertRaises(ValueError):
                connect_with_retry(Mock(), Config(startup_retries=3))
        connect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
