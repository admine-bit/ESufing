"""通过指定网卡查询 DNS，不修改系统解析器或其他网卡的网络配置。"""

import ipaddress
import re
import socket
import subprocess
import time

import dns.exception
import dns.message
import dns.query
import dns.rcode
import dns.rdatatype
from psutil import net_if_addrs

from . import log


class InterfaceResolver:
    def __init__(self, interface, fallback_servers=(), host_fallbacks=None):
        self.interface = interface
        self.fallback_servers = tuple(fallback_servers)
        self.cache = {}
        self.host_fallbacks = host_fallbacks or {}

    def network(self):
        addresses = net_if_addrs().get(self.interface, [])
        source = next((item.address for item in addresses if item.family == socket.AF_INET), "")
        if not source:
            raise socket.gaierror(socket.EAI_AGAIN, f"网卡 {self.interface} 尚未获取 IPv4 地址")
        servers = []
        try:
            result = subprocess.run(
                ["nmcli", "-g", "IP4.DNS", "device", "show", self.interface],
                capture_output=True, text=True, timeout=5, check=True,
            )
            servers.extend(re.split(r"[|,\s]+", result.stdout))
        except (OSError, subprocess.SubprocessError):
            pass
        valid = []
        for item in [*servers, *self.fallback_servers]:
            try:
                address = str(ipaddress.IPv4Address(item.strip()))
            except ValueError:
                continue
            if address not in valid:
                valid.append(address)
        return source, tuple(valid)

    def resolve(self, hostname):
        try:
            return (str(ipaddress.ip_address(hostname)),)
        except ValueError:
            pass
        source, servers = self.network()
        key = (hostname, source, servers)
        cached = self.cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        query = dns.message.make_query(hostname, dns.rdatatype.A)
        for server in servers:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, self.interface.encode() + b"\0")
                    sock.bind((source, 0))
                    sock.setblocking(False)
                    response = dns.query.udp(query, server, timeout=2, sock=sock, raise_on_truncation=True)
                if response.rcode() != dns.rcode.NOERROR:
                    continue
                records = [rrset for rrset in response.answer if rrset.rdtype == dns.rdatatype.A]
                addresses = tuple(dict.fromkeys(record.address for rrset in records for record in rrset))
                if addresses:
                    ttl = min(60, min(rrset.ttl for rrset in records))
                    self.cache[key] = (time.monotonic() + ttl, addresses)
                    return addresses
            except (OSError, dns.exception.DNSException):
                continue
        addresses = self.host_fallbacks.get(hostname.lower().rstrip("."), ())
        if addresses:
            log.warning(f"{hostname} 的 DNS 暂不可用，使用配置的认证入口 IP")
            return tuple(addresses)
        raise socket.gaierror(socket.EAI_AGAIN,
                              f"网卡 {self.interface} 的 DNS 暂不可用，无法解析 {hostname}；将重试")
