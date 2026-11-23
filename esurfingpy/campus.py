"""Linux 双阶段校园网认证入口。"""

import base64
import html
import re
import subprocess
import time
from urllib.parse import parse_qs, urljoin, urlsplit

import requests

from . import log
from .cdc import CAPTIVE_URL, USER_AGENT, CDCClient, portal_config
from .config import load_config
from .http import create_session


def nmcli(*args, check=True):
    return subprocess.run(["nmcli", *args], capture_output=True, text=True,
                          check=check, timeout=45)


def ensure_wifi(config):
    if not config.ssid:
        return
    if not config.interface:
        raise ValueError("自动连接 Wi-Fi 时必须在 config.ini 指定 interface")
    active = nmcli("-g", "GENERAL.CONNECTION", "device", "show", config.interface).stdout.strip()
    if active and active != "--":
        ssid = nmcli("-g", "802-11-wireless.ssid", "connection", "show", active, check=False).stdout.strip()
        if ssid == config.ssid:
            return
    profile = "ESurfing-" + config.ssid + "-" + config.interface
    result = nmcli("connection", "show", profile, check=False)
    if result.returncode:
        nmcli("connection", "add", "type", "wifi", "ifname", config.interface,
              "con-name", profile, "ssid", config.ssid, "connection.autoconnect", "no",
              "802-11-wireless.cloned-mac-address", "permanent", "ipv4.route-metric", "2000",
              "ipv4.ignore-auto-dns", "no", "ipv6.method", "disabled")
    else:
        # 固定已保存配置的接口，避免双无线网卡时误切换内置网卡。
        nmcli("connection", "modify", profile, "connection.interface-name", config.interface)
    log.info(f"正在连接 {config.ssid}（{config.interface}）")
    nmcli("--wait", "30", "connection", "up", profile, "ifname", config.interface)


def redirect_url(response):
    for pattern in (r'location(?:\.href)?\s*=\s*[\'"]([^\'"]+)',
                    r'<a\b[^>]*href=[\'"]([^\'"]+)'):
        match = re.search(pattern, response.text, re.I)
        if match:
            return urljoin(response.url, html.unescape(match.group(1)))
    return response.url


def encode_byod_password(password):
    escaped = []
    for char in password:
        if ord(char) < 256:
            escaped.append(char.replace("\\", "\\\\"))
        else:
            units = char.encode("utf-16-be")
            for offset in range(0, len(units), 2):
                escaped.append(f"\\u{int.from_bytes(units[offset:offset + 2], 'big'):04X}")
    return base64.b64encode("".join(escaped).encode("latin-1")).decode()


def byod_login(session, config, response):
    url = redirect_url(response)
    if urlsplit(url).netloc != urlsplit(config.byod_url).netloc:
        raise ValueError("发现未知的学校认证入口，请检查 config.ini 的 byod_url")
    params = parse_qs(urlsplit(url).query)
    values = {key: params.get(key, [""])[0] for key in ("wlannasid", "usermac", "userip", "userurl", "ssid")}
    if not values["usermac"] or not values["userip"]:
        raise ValueError("学校认证入口缺少 USB 网卡的 MAC 或 IP")
    init = session.get(config.byod_url + "/byod/byodrs/init", params=values, timeout=config.timeout)
    init.raise_for_status()
    data = init.json()
    if data.get("code") != 0:
        raise ValueError("学校认证初始化失败：" + str(data.get("msg", "未知错误")))
    mac_info = data.get("data", {}).get("byodMacRegistInfo", {})
    # MAC 已经注册时无需重复提交凭据。
    if "Result" in data.get("data", {}).get("url", ""):
        return
    response = session.get(config.byod_url + "/byod/byodrs/login/init", params={"hp": 1}, timeout=config.timeout)
    response.raise_for_status()
    meta = response.json()
    if meta.get("errormsg") != "success":
        raise ValueError("学校认证服务初始化失败")
    # 对齐学校网页使用的 JavaScript escape + Base64，支持非 ASCII 密码。
    payload = {
        "userName": config.username, "userPassword": encode_byod_password(config.password),
        "serviceSuffixId": meta.get("defaultServiceTypeId", -1), "dynamicPwdAuth": False,
        "code": "", "codeTime": "", "validateCode": "",
        "shopIdE": mac_info.get("shopIdE", ""), "wlannasid": mac_info.get("wlannasid", ""),
    }
    payload.update({key: meta.get(key, "") for key in ("licenseCode", "userGroupId", "validationType", "guestManagerId")})
    response = session.post(config.byod_url + "/byod/byodrs/login/defaultLogin", json=payload, timeout=config.timeout)
    response.raise_for_status()
    result = response.json()
    if result.get("code") != 0:
        raise ValueError("学校认证失败：" + str(result.get("msg", "未知错误")))
    if result.get("data", {}).get("ifModifyPwd"):
        raise ValueError("学校要求修改密码，请先在学校认证页面完成")
    log.info("学校 BYOD 认证成功，等待网卡重新接入电信网段")
    time.sleep(3)
    ensure_wifi(config)


def probe(session, config):
    response = session.get(CAPTIVE_URL, headers={"User-Agent": USER_AGENT}, timeout=config.timeout)
    response.raise_for_status()
    # 只有原地址直接返回空的 204 才认定外网正常；认证页的 200 不算成功。
    online = response.status_code == 204 and response.url == CAPTIVE_URL and not response.content
    return online, response


def connect(session, config):
    ensure_wifi(config)
    online, response = probe(session, config)
    if online:
        log.info(f"校园网已联网（{config.interface or '默认接口'}）")
        client = CDCClient.restore(session, config)
        if client:
            log.info("已恢复本机天翼会话，心跳检测通过")
        return client
    url = redirect_url(response)
    if "/byod/" in url:
        byod_login(session, config, response)
        # BYOD 首次认证会强制下线并切换 VLAN，等待 DHCP 地址更新。
        for _ in range(12):
            time.sleep(2)
            ensure_wifi(config)
            try:
                online, response = probe(session, config)
                if "/byod/" not in redirect_url(response):
                    break
            except requests.RequestException:
                continue
        else:
            raise ValueError("学校认证已完成，但网卡尚未切换到电信网段，请稍后重试")
        if online:
            return None
    portal = portal_config(response.text)
    if portal is None:
        raise ValueError("未检测到天翼新版认证入口，请确认指定网卡已连接校园网")
    client = CDCClient(session, config)
    log.info("正在进行天翼新版客户端认证")
    client.login(portal, config.username, config.password)
    online, _ = probe(session, config)
    if not online:
        raise ValueError("天翼已返回登录凭据，但指定网卡尚未通过外网检测")
    log.info(f"校园网认证成功，外网检测通过（{config.interface or '默认接口'}）")
    return client


def run():
    try:
        config = load_config()
        with create_session(config.interface) as session:
            client = connect(session, config)
            if config.mode == "login":
                if client:
                    log.warning("当前为单次登录；天翼需要持续心跳，长期联网请将 mode 改为 keepalive")
                return 0
            log.info("正在保活，按 Ctrl+C 停止")
            last_heartbeat = time.monotonic()
            last_check = time.monotonic()
            while True:
                time.sleep(1)
                try:
                    now = time.monotonic()
                    if client and now - last_heartbeat >= client.interval:
                        client.heartbeat()
                        last_heartbeat = time.monotonic()
                    if now - last_check >= config.interval:
                        ensure_wifi(config)
                        online, _ = probe(session, config)
                        last_check = time.monotonic()
                        if not online:
                            client = connect(session, config)
                            last_heartbeat = time.monotonic()
                        elif client is None:
                            client = CDCClient.restore(session, config)
                            last_heartbeat = time.monotonic()
                except (requests.RequestException, ValueError, subprocess.SubprocessError) as exc:
                    log.warning(f"连接中断：{exc}；稍后重新认证")
                    client = None
                    time.sleep(config.interval)
    except KeyboardInterrupt:
        log.info("已停止保活")
        return 0
    except (ValueError, OSError, requests.RequestException, subprocess.SubprocessError) as exc:
        log.error(str(exc))
        return 1
