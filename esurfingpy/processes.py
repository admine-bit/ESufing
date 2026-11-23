"""协调本项目的校园网进程，不干预其他联网程序。"""

import fcntl
import os
import signal
from contextlib import contextmanager
from pathlib import Path

import psutil

from . import log
from .config import ROOT, load_config

START_LOCK = ROOT / ".esurfing-start.lock"


def project_clients():
    """只查找同一项目、同一用户的 main.py 校园网入口。"""
    result = []
    for process in psutil.process_iter(["pid", "cmdline", "cwd"]):
        try:
            if process.pid == os.getpid() or process.uids().real != os.getuid():
                continue
            args = process.info["cmdline"] or []
            if len(args) < 2 or not Path(args[0]).name.startswith("python"):
                continue
            cwd = process.info["cwd"]
            if not cwd or Path(cwd).resolve() != ROOT:
                continue
            entry = Path(args[1])
            if not entry.is_absolute():
                entry = Path(cwd) / entry
            if entry.resolve() != ROOT / "main.py" or args[2:] not in ([], ["campus"]):
                continue
            profile = process.environ().get("ESURFING_PROFILE", "")
            interface = load_config(profile=profile).interface
            result.append((process, interface))
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, ValueError):
            continue
    return result


def stop_client(process):
    """停止旧保活及其短期认证子进程，避免继续把 USB 拉回校园网。"""
    try:
        children = process.children(recursive=True)
        process.send_signal(signal.SIGINT)
        _, alive = psutil.wait_procs([process], timeout=3)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        for item in alive:
            item.terminate()
        _, alive = psutil.wait_procs(alive + children, timeout=3)
        if alive:
            raise ValueError("旧校园网进程尚未停止，请结束旧进程后重新启动 PCIe 入口")
    except psutil.NoSuchProcess:
        pass


@contextmanager
def coordinate_clients(config):
    # 只锁启动阶段，让 USB/PCIe 同时启动时也按同一顺序检查。
    with START_LOCK.open("a") as lock:
        START_LOCK.chmod(0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        peers = project_clients()
        if config.usb_interface and config.interface == config.usb_interface:
            if any(interface == config.pcie_interface for _, interface in peers):
                raise ValueError("PCIe 校园网进程正在运行，不能同时启动 USB 校园网；请先停止 PCIe 入口")
        if config.pcie_interface and config.interface == config.pcie_interface:
            interfaces = {config.pcie_interface, config.usb_interface} - {""}
            for process, interface in peers:
                if interface in interfaces:
                    log.info(f"停止旧校园网保活进程（{interface}，PID {process.pid}）")
                    stop_client(process)
    yield
