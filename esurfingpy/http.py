"""校园网请求直连指定 Linux 网卡，避免走代理或手机热点。"""

import socket
import sys

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import ConnectTimeoutError, NameResolutionError, NewConnectionError
from urllib3.util.connection import create_connection

from .dns import InterfaceResolver


def interface_pools(resolver):
    class ResolvedConnection:
        def _new_conn(self):
            try:
                addresses = resolver.resolve(self._dns_host)
            except socket.gaierror as exc:
                raise NameResolutionError(self.host, self, exc) from exc
            last_error = NewConnectionError(self, "DNS 未返回可连接的地址")
            for address in addresses:
                try:
                    # 直接连接解析出的 IP；连接对象的域名不变，保留 Host、SNI 及证书校验。
                    sock = create_connection((address, self.port), self.timeout,
                                             source_address=self.source_address,
                                             socket_options=self.socket_options)
                except socket.timeout:
                    last_error = ConnectTimeoutError(self, f"连接 {self.host} 超时")
                except OSError as exc:
                    last_error = NewConnectionError(self, f"连接 {self.host} 失败：{exc}")
                else:
                    sys.audit("http.client.connect", self, self.host, self.port)
                    return sock
            raise last_error

    class BoundHTTPConnection(ResolvedConnection, HTTPConnection):
        pass

    class BoundHTTPSConnection(ResolvedConnection, HTTPSConnection):
        pass

    class BoundHTTPPool(HTTPConnectionPool):
        ConnectionCls = BoundHTTPConnection

    class BoundHTTPSPool(HTTPSConnectionPool):
        ConnectionCls = BoundHTTPSConnection

    return {"http": BoundHTTPPool, "https": BoundHTTPSPool}


class InterfaceAdapter(HTTPAdapter):
    def __init__(self, interface, dns_servers=()):
        if not sys.platform.startswith("linux"):
            raise ValueError("指定 interface 目前仅支持 Linux")
        socket.if_nametoindex(interface)
        self.interface = interface
        self.resolver = InterfaceResolver(interface, dns_servers)
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        kwargs["socket_options"] = list(HTTPConnection.default_socket_options) + [
            (socket.SOL_SOCKET, socket.SO_BINDTODEVICE, self.interface.encode() + b"\0")
        ]
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = interface_pools(self.resolver)


def create_session(interface="", dns_servers=()):
    session = requests.Session()
    session.trust_env = False
    if interface:
        adapter = InterfaceAdapter(interface, dns_servers)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    return session
