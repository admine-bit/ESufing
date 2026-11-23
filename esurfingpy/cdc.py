"""新版天翼 CCTP 认证与保活；所有 HTTP 复用绑定校园网卡的 Session。"""

import hashlib
import html
import json
import os
import re
import socket
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from psutil import net_if_addrs

from .config import ROOT

USER_AGENT = "CCTP/android11_64/2104"
CAPTIVE_URL = "http://connect.rom.miui.com/generate_204"
CRYPTO_BINARY = ROOT / ".venv" / "esurfing-crypto"
ZERO_UUID = "00000000-0000-0000-0000-000000000000"
STATE_FILE = ROOT / ".esurfing-session.json"


def state_file(config):
    suffix = config.interface or "default"
    return STATE_FILE.with_name(f"{STATE_FILE.stem}-{suffix}.json")


def tag_text(content, tag):
    match = re.search(rf"<{re.escape(tag)}(?:\s[^>]*)?>(.*?)</{re.escape(tag)}>", content, re.S | re.I)
    if not match:
        return ""
    value = match.group(1).strip()
    if value.startswith("<![CDATA[") and value.endswith("]]>"):
        return value[9:-3]
    return html.unescape(value)


def portal_config(content):
    match = re.search(r"<!--//config\.campus\.js\.chinatelecom\.com\s*(.*?)//config\.campus\.js\.chinatelecom\.com-->", content, re.S)
    if not match:
        return None
    block = match.group(1)
    result = {"ticket_url": tag_text(block, "ticket-url"), "auth_url": tag_text(block, "auth-url")}
    if not all(result.values()):
        raise ValueError("天翼认证页面缺少 ticket-url 或 auth-url")
    for key in ("QueryVerificateCodeStatus", "QueryAuthCode"):
        node = re.search(rf"<{key}\b([^>]*)/?>", block)
        if node:
            url = re.search(r'\burl="([^"]+)"', node.group(1))
            if url and re.search(r'\benable="1"', node.group(1)):
                result[key] = html.unescape(url.group(1))
    return result


def zsm_algorithm(data):
    if len(data) < 5:
        raise ValueError("服务器没有返回有效的 ZSM 握手数据")
    offset = 4 + data[3]
    if offset >= len(data):
        raise ValueError("ZSM 算法数据不完整")
    length = data[offset]
    if length != 36 or offset + 1 + length > len(data):
        raise ValueError("ZSM 算法标识不完整")
    value = data[offset + 1:offset + 1 + length].decode("ascii")
    return str(uuid.UUID(value)).upper()


def crypto(operation, algorithm, data):
    if not CRYPTO_BINARY.is_file():
        raise ValueError("缺少新版认证加密组件，请运行 ./start.sh 自动构建")
    result = subprocess.run(
        [str(CRYPTO_BINARY)],
        input=json.dumps({"operation": operation, "algorithm": algorithm, "data": data}) + "\n",
        capture_output=True, text=True, timeout=10, check=True,
    )
    answer = json.loads(result.stdout)
    if "error" in answer:
        raise ValueError(f"新版认证加解密失败：{answer['error']}")
    return answer["data"]


class CDCClient:
    def __init__(self, session, config):
        self.session = session
        self.config = config
        self.client_id = str(uuid.uuid4())
        self.algorithm = ZERO_UUID
        self.routing = {}
        self.ticket = ""
        self.keep_url = ""
        self.term_url = ""
        self.interval = 30
        self.user_ip = ""
        self.ac_ip = ""
        self.mac = ""
        if config.interface:
            self.mac = Path(f"/sys/class/net/{config.interface}/address").read_text().strip()

    def post(self, url, data):
        headers = {
            "User-Agent": USER_AGENT, "Connection": "close",
            "Content-Type": "application/x-www-form-urlencoded",
            "Client-ID": self.client_id, "Algo-ID": self.algorithm,
            "CDC-Checksum": hashlib.md5(data.encode()).hexdigest(),
        }
        for _ in range(6):
            if urlsplit(url).scheme not in ("http", "https"):
                raise ValueError("认证服务器返回了不支持的地址")
            response = self.session.post(url, data=data, headers={**headers, **self.routing},
                                         timeout=self.config.timeout, allow_redirects=False)
            for source, target in (("area", "CDC-Area"), ("schoolid", "CDC-SchoolId"), ("domain", "CDC-Domain")):
                if response.headers.get(source):
                    self.routing[target] = response.headers[source]
            if response.is_redirect:
                url = urljoin(url, response.headers["Location"])
                response.close()
                continue
            response.raise_for_status()
            if not response.content:
                raise ValueError(f"认证服务器返回空响应，Error-Code={response.headers.get('Error-Code', '未知')}")
            return response.content
        raise ValueError("认证服务器重定向次数过多")

    def payload(self, **values):
        root = ET.Element("request")
        common = {"user-agent": USER_AGENT, "client-id": self.client_id,
                  "local-time": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")}
        for key, value in {**common, **values}.items():
            ET.SubElement(root, key).text = str(value)
        return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")

    def exchange(self, url, **values):
        encrypted = crypto("encrypt", self.algorithm, self.payload(**values))
        raw = self.post(url, encrypted).decode("ascii")
        return crypto("decrypt", self.algorithm, raw)

    def login(self, portal, username, password):
        query = parse_qs(urlsplit(portal["ticket_url"]).query)
        self.user_ip = query.get("wlanuserip", [""])[0]
        self.ac_ip = query.get("wlanacip", [""])[0]
        if not self.user_ip or not self.ac_ip:
            raise ValueError("新版认证入口缺少设备或认证服务器 IP")
        self.algorithm = zsm_algorithm(self.post(portal["ticket_url"], ZERO_UUID))
        info = self.exchange(portal["ticket_url"], **{
            "host-name": socket.gethostname(), "ipv4": self.user_ip, "ipv6": "",
            "mac": self.mac, "ostag": "Linux", "gwip": self.ac_ip,
        })
        self.ticket = tag_text(info, "ticket")
        if not self.ticket:
            raise ValueError("获取天翼认证票据失败：" + self.error(info))
        info = self.exchange(portal["auth_url"], ticket=self.ticket, userid=username, passwd=password)
        self.keep_url = tag_text(info, "keep-url")
        self.term_url = tag_text(info, "term-url")
        if not self.keep_url:
            raise ValueError("天翼认证失败：" + self.error(info))
        self.interval = max(1, int(tag_text(info, "keep-retry") or 30))
        self.save()

    def save(self):
        values = {key: getattr(self, key) for key in (
            "client_id", "algorithm", "routing", "ticket", "keep_url", "term_url",
            "interval", "user_ip", "ac_ip", "mac",
        )}
        values["interface"] = self.config.interface
        fd, temp = tempfile.mkstemp(dir=ROOT, prefix=".esurfing-session-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(values, stream)
            os.replace(temp, state_file(self.config))
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    @classmethod
    def restore(cls, session, config):
        try:
            data = json.loads(state_file(config).read_text())
            if not config.interface or data.get("interface") != config.interface:
                return None
            addresses = net_if_addrs().get(config.interface, [])
            if data.get("user_ip") not in {item.address for item in addresses if item.family == socket.AF_INET}:
                return None
            client = cls(session, config)
            if data.get("mac") != client.mac:
                return None
            for key in ("client_id", "algorithm", "routing", "ticket", "keep_url", "term_url",
                        "interval", "user_ip", "ac_ip"):
                setattr(client, key, data[key])
            client.heartbeat()
            return client
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            return None

    @staticmethod
    def error(content):
        for tag in ("error-message", "message", "msg", "result-info", "reason", "description"):
            if tag_text(content, tag):
                return tag_text(content, tag)
        return "服务端未提供错误说明"

    def heartbeat(self):
        info = self.exchange(self.keep_url, **{
            "host-name": socket.gethostname(), "ipv4": self.user_ip, "ipv6": "",
            "ticket": self.ticket, "mac": self.mac, "ostag": "Linux",
        })
        interval = tag_text(info, "interval")
        if not interval:
            raise ValueError("天翼心跳响应无效，需要重新认证")
        self.interval = max(1, int(interval))
