"""不依赖工作目录的本机私有配置。"""

from configparser import ConfigParser
from dataclasses import dataclass, field
import ipaddress
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config.ini"


@dataclass
class Config:
    username: str = ""
    password: str = field(default="", repr=False)
    interface: str = ""
    ssid: str = ""
    byod_url: str = "http://172.17.18.2:30004"
    timeout: float = 8
    mode: str = "keepalive"
    interval: float = 30
    usb_interface: str = ""
    pcie_interface: str = ""
    fallback_dns: tuple = ("202.96.128.166", "202.96.128.86")
    startup_retries: int = 5
    startup_retry_interval: float = 5
    probe_ipv4: tuple = ("220.181.104.183", "202.69.4.32")
    portal_ipv4: str = "125.88.59.131"

    @property
    def host_fallbacks(self):
        return {"enet.10000.gd.cn": (self.portal_ipv4,)}


def load_config(path=CONFIG_FILE, profile=None):
    parser = ConfigParser(interpolation=None)
    if not parser.read(path, encoding="utf-8"):
        raise ValueError("请先复制 config.example.ini 为 config.ini，再填写账号和密码")
    profile = profile if profile is not None else os.environ.get("ESURFING_PROFILE", "")
    if profile not in ("", "usb", "pcie"):
        raise ValueError("网卡配置只支持 usb 或 pcie")
    interface = parser.get("network", "interface", fallback="").strip()
    if profile:
        interface = parser.get(profile, "interface", fallback="").strip()
        if not interface:
            raise ValueError(f"请在 config.ini 的 [{profile}] 中填写 interface")
    config = Config(
        username=parser.get("account", "username", fallback="").strip(),
        password=parser.get("account", "password", fallback=""),
        interface=interface,
        ssid=parser.get("network", "ssid", fallback="").strip(),
        byod_url=parser.get("network", "byod_url", fallback=Config.byod_url).rstrip("/"),
        timeout=parser.getfloat("network", "timeout", fallback=8),
        mode=parser.get("runtime", "mode", fallback="keepalive").strip(),
        interval=parser.getfloat("runtime", "interval", fallback=30),
        usb_interface=parser.get("usb", "interface", fallback="").strip(),
        pcie_interface=parser.get("pcie", "interface", fallback="").strip(),
        fallback_dns=tuple(item.strip() for item in parser.get(
            "network", "fallback_dns", fallback=",".join(Config.fallback_dns)).split(",") if item.strip()),
        startup_retries=parser.getint("runtime", "startup_retries", fallback=5),
        startup_retry_interval=parser.getfloat("runtime", "startup_retry_interval", fallback=5),
        probe_ipv4=tuple(item.strip() for item in parser.get(
            "network", "probe_ipv4", fallback=",".join(Config.probe_ipv4)).split(",") if item.strip()),
        portal_ipv4=parser.get("network", "portal_ipv4", fallback=Config.portal_ipv4).strip(),
    )
    if not config.username or not config.password:
        raise ValueError("请在 config.ini 的 [account] 中填写 username 和 password")
    if config.mode not in ("login", "keepalive"):
        raise ValueError("[runtime] mode 只支持 login 或 keepalive")
    if config.timeout <= 0 or config.interval < 1:
        raise ValueError("timeout 必须大于 0，interval 必须至少为 1 秒")
    if config.usb_interface and config.usb_interface == config.pcie_interface:
        raise ValueError("[usb] 和 [pcie] 必须配置不同的网卡")
    for server in (*config.fallback_dns, *config.probe_ipv4, config.portal_ipv4):
        ipaddress.IPv4Address(server)
    if not config.probe_ipv4:
        raise ValueError("probe_ipv4 至少需要填写一个探测地址")
    if config.startup_retries < 1 or config.startup_retry_interval <= 0:
        raise ValueError("startup_retries 必须至少为 1，startup_retry_interval 必须大于 0")
    return config
