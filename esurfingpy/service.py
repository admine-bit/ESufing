"""让 PCIe 保活由用户服务管理器托管，生命周期独立于终端和聊天。"""

import os
import subprocess
import sys

from .config import ROOT, load_config

UNIT = "esurfing-pcie.service"


def unit_loaded():
    result = subprocess.run(
        ["systemctl", "--user", "show", UNIT, "--property=LoadState", "--value"],
        capture_output=True, text=True, check=True, timeout=10,
    )
    return result.stdout.strip() == "loaded"


def start():
    config = load_config(profile="pcie")
    if config.mode != "keepalive":
        # 显式选择单次登录时，保持前台执行并退出的原有语义。
        env = {**os.environ, "ESURFING_PROFILE": "pcie"}
        return subprocess.run([sys.executable, str(ROOT / "main.py")], cwd=ROOT, env=env).returncode
    if unit_loaded():
        subprocess.run(["systemctl", "--user", "restart", UNIT], check=True, timeout=30)
    else:
        subprocess.run([
            "systemd-run", "--user", f"--unit={UNIT}", "--collect", "--service-type=exec",
            "--description=ESurfing PCIe campus keepalive",
            f"--working-directory={ROOT}", "--setenv=ESURFING_PROFILE=pcie",
            "--property=Restart=always", "--property=RestartPreventExitStatus=2",
            f"--property=RestartSec={config.startup_retry_interval:g}s",
            "--property=StartLimitIntervalSec=0", "--property=TimeoutStopSec=10s",
            "--property=KillSignal=SIGINT", "--property=UMask=0077",
            sys.executable, str(ROOT / "main.py"),
        ], check=True, timeout=30)
    print("PCIe 校园网后台保活已启动，关闭终端或结束聊天后会继续运行。")
    print(f"停止：{ROOT / 'stop-pcie.sh'}")
    print(f"查看状态：{ROOT / 'status-pcie.sh'}")
    return 0


def stop():
    if unit_loaded():
        subprocess.run(["systemctl", "--user", "stop", UNIT], check=True, timeout=30)
    print("PCIe 后台保活已停止。")
    return 0


def status():
    if unit_loaded():
        return subprocess.run(["systemctl", "--user", "status", "--no-pager", UNIT]).returncode
    print("PCIe 后台保活未运行。")
    return 3


def main():
    actions = {"start": start, "stop": stop, "status": status}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        print("请使用 start-pcie.sh、stop-pcie.sh 或 status-pcie.sh。", file=sys.stderr)
        return 2
    try:
        return actions[sys.argv[1]]()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"PCIe 服务操作失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
