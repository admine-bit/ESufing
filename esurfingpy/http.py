"""校园网请求直连指定 Linux 网卡，避免走代理或手机热点。"""

import socket
import sys

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection


class InterfaceAdapter(HTTPAdapter):
    def __init__(self, interface):
        if not sys.platform.startswith("linux"):
            raise ValueError("指定 interface 目前仅支持 Linux")
        socket.if_nametoindex(interface)
        self.interface = interface
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        kwargs["socket_options"] = list(HTTPConnection.default_socket_options) + [
            (socket.SOL_SOCKET, socket.SO_BINDTODEVICE, self.interface.encode() + b"\0")
        ]
        return super().init_poolmanager(*args, **kwargs)


def create_session(interface=""):
    session = requests.Session()
    session.trust_env = False
    if interface:
        adapter = InterfaceAdapter(interface)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    return session
