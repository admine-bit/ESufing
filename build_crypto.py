"""构建本地天翼新版加密组件；首次运行会校验并安装独立 Go 工具链。"""

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# 工具链配置区
GO_VERSION = "go1.27.4"  # 需要升级加密组件构建工具时修改，版本必须存在于 Go 官方下载站。
ROOT = Path(__file__).resolve().parent


def main():
    source = ROOT / "third_party" / "esurfing-go"
    output = ROOT / ".venv" / "esurfing-crypto"
    inputs = list(source.rglob("*.go")) + [source / "go.mod", source / "go.sum"]
    if output.exists() and all(p.stat().st_mtime <= output.stat().st_mtime for p in inputs):
        return
    local_go = ROOT / ".tools" / "go" / "bin" / "go"
    go = str(local_go) if local_go.exists() else shutil.which("go")
    if not go:
        if platform.system() != "Linux":
            raise RuntimeError("请安装 Go 1.25.5 或以上版本，再重新运行")
        arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
        if not arch:
            raise RuntimeError("此架构请自行安装 Go 1.25.5 或以上版本")
        print("首次构建：下载并校验独立 Go 工具链……", flush=True)
        with urllib.request.urlopen("https://go.dev/dl/?mode=json&include=all", timeout=30) as response:
            releases = json.load(response)
        release = next(r for r in releases if r["version"] == GO_VERSION)
        item = next(f for f in release["files"] if f["os"] == "linux" and f["arch"] == arch and f["kind"] == "archive")
        tools_dir = ROOT / ".tools"
        tools_dir.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tools_dir) as temp:
            archive = Path(temp) / "go.tar.gz"
            digest = hashlib.sha256()
            with urllib.request.urlopen("https://go.dev/dl/" + item["filename"], timeout=60) as response, archive.open("wb") as file:
                while chunk := response.read(1024 * 1024):
                    file.write(chunk)
                    digest.update(chunk)
            if digest.hexdigest() != item["sha256"]:
                raise RuntimeError("Go 工具链 SHA256 校验失败，已停止安装")
            with tarfile.open(archive) as tar:
                tar.extractall(tools_dir, filter="data")
        go = str(local_go)
    output.parent.mkdir(exist_ok=True)
    print("构建天翼新版加密组件……", flush=True)
    env = {**os.environ, "CGO_ENABLED": "0"}
    subprocess.run([go, "mod", "verify"], cwd=source, env=env, check=True)
    subprocess.run([go, "build", "-trimpath", "-o", str(output), "."], cwd=source, env=env, check=True)


if __name__ == "__main__":
    main()
