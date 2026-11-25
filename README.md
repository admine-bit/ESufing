# ESurfingPy-CLI

## Linux 一键连接（五邑大学 / 广东天翼新版）

本分支仓库：<https://github.com/admine-bit/ESufing>。保留原项目的旧版网页认证和 GUI，
新增 Linux 的学校 BYOD 认证、天翼新版 CCTP 认证、指定网卡联网检测及心跳保活。

本机绿联 USB 网卡为 `wlxec1ac353bc7c`，PCIe 无线网卡（RTL8852BE）为 `wlp6s0`，
无线网络为 `WYUNET-STUDENT`。两张网卡都已分别通过认证、HTTPS 外网访问及心跳测试。
首次登录会先通过学校网页认证，随后自动重连并获取电信网段地址，最后进行天翼认证。
整个认证及外网检测过程均绑定配置的网卡，HTTP 请求不使用环境变量中的代理。
DNS 查询也绑定同一网卡，先使用该网卡从 DHCP 获取的 DNS，再尝试 `[network] fallback_dns` 中的备用地址；
不会修改系统 DNS、USB 其他网络的 DNS 或连接配置。HTTPS 仍按原域名校验证书。
当所有 DNS 都不可用时，改用 `[network] probe_ipv4` 中的地址直接访问探测端点，
并保留正确的 HTTP Host。认证域名也无法解析时，使用 `portal_ipv4` 直连天翼入口。
这条路径不依赖 DNS；普通网页和认证页面的 HTTP 200 不会被误判为已联网。

本机已经配置账号。日常选择相应入口，无需额外参数：

```bash
cd /home/ad/ESurfingPy-CLI
./start-usb.sh
```

使用 PCIe 无线网卡：

```bash
/home/ad/ESurfingPy-CLI/start-pcie.sh
```

`start.sh` 则使用 `[network]` 的默认接口。两个入口共用账号配置，
按网卡分别保存 NetworkManager 连接及认证会话。
启动 PCIe 入口会停止本项目已有的 USB 校园网保活，并断开 USB 上的 `ssid` 校园网连接。
USB 若连接手机热点或其他 Wi-Fi，则保持其连接、自动连接设置及保存的网络配置。
PCIe 保活期间会阻止另一个 USB 校园网脚本启动，并定期检查 USB 是否重新连上同一校园网。
需要切回 USB 校园网时，先停止 PCIe 入口，再运行 `start-usb.sh`。

配置集中在项目根目录 `config.ini` 的 `[account]`、`[network]`、`[usb]`、`[pcie]` 和 `[runtime]`，
每个可修改参数都有中文注释。更换账号、密码或网卡时只需编辑此文件。
该文件已加入 `.gitignore`，本机权限设置为 `600`，不应提交到 Git。
认证成功后会将会话缓存到同样被 Git 忽略、权限为 `600` 的 `.esurfing-session-网卡名.json`，
供程序重启后恢复心跳；更换账号时先删除对应的会话缓存。

新机器安装（Python 3.12 及以上、NetworkManager / `nmcli`）：

```bash
git clone git@github.com:admine-bit/ESufing.git ESurfingPy-CLI
cd ESurfingPy-CLI
cp config.example.ini config.ini
chmod 600 config.ini
# 编辑 config.ini，填写账号、密码、ssid 及对应网卡配置的 interface。
./start-usb.sh
```

首次运行请先保留一条可联网的连接以下载依赖。脚本会创建 `.venv`，安装 Python 依赖，
并构建本地新版加密组件。如果未安装 Go，会从 Go 官方下载固定版本工具链到 `.tools`，
校验 SHA256 后使用；后续启动会复用已构建的组件，无需重复下载。
如系统未提供 venv，请先安装对应的 `python3-venv` 包。
加密实现引用 [xxmod/EsurfingGo](https://github.com/xxmod/EsurfingGo)，
来源、固定版本和 MIT 许可证见 `third_party/esurfing-go/`。

`mode = keepalive` 为推荐设置：保持终端运行，程序按服务器要求发送心跳，断线后重新认证；
按 `Ctrl+C` 停止。`mode = login` 仅登录并检查外网后退出，停止心跳后可能被服务器断开。
此启动方式不会安装开机自启服务。

若刚连接 Wi-Fi 时出现 `Temporary failure in name resolution`，程序会自动重试网络初始化，
默认最多 5 次，每次间隔 5 秒。需要调整时修改 `config.ini` 的 `[runtime] startup_retries`
和 `startup_retry_interval`；备用 DNS 在 `[network] fallback_dns` 中调整。
如果探测服务或天翼入口 IP 发生变化，分别更新 `probe_ipv4` 或 `portal_ipv4`。

Wi-Fi 配置使用网卡的永久 MAC 地址，通过 NetworkManager 自动获取 IP 和 DNS。
自动创建的校园网连接优先级低于已有连接，便于同时保留手机热点；
需要整台机器使用校园网时，认证成功后在系统网络设置中断开手机热点即可。

需要图形界面时，额外安装 GUI 依赖并明确启动：

```bash
.venv/bin/python -m pip install -r requirements-gui.txt
.venv/bin/python main.py gui
```

下面保留原项目的旧版接口说明。对于服务端提示“拨号方式错误”的账号，请使用上述新版入口。

## 简介

基于 Python 实现登录和登出广东天翼校园网网页认证的命令行工具。可以用该工具来快速登录或登出广东天翼校园网，
或者反复重新登录来重置限速状态，以 “破解” 限速。

![./docs/images/1.png](./docs/images/1.png)

<br />

## 项目演示

### 图形界面

![./docs/images/gui.gif](./docs/images/gui.gif)

### 命令行

![./docs/images/cli.gif](./docs/images/cli.gif)

<br />

## 适用学校

> 小道消息，广东天翼校园网于2021年10月20日，凌晨期间“优化”了校园网，实则是关闭了部分学校的网页认证通道。
> 一些学校原本只是前端网页删除或屏蔽了登录相关组件的学校，其实还是可以使用类似此项目相关的基于网页认证的
> 程序实现网页登录，但关闭认证通道后就彻底用不了（提示 `已办理一人一号多终端业务的用户，请使用客户端登录` 
> 或 `当前该账号的拨号方式错误` ）。此项目不再适用于这些学校，只适用于没有关闭网页认证的广东天翼校园网。
> 如果你的校园网可以使用天翼校园网客户端登录，可以试试我的新项目 [go-esurfing](https://github.com/Pandaft/go-esurfing) 。 

如果你的学校校园网是广东天翼校园网，欢迎使用并反馈项目适用情况：
[discussion#3](https://github.com/Pandaft/ESurfingPy-CLI/discussions/3)

<br />

## 下载运行

### 运行已打包的可执行文件

> 程序打包了识别验证码所需的模型文件，因此文件体积较大。
>
> 由于 Python 不能交叉编译，在不同系统上存在差异，因此很可能无法正常运行。
>
> 已知 Win10, Win11, Ubuntu 22.10 测试正常，其余未测试，建议通过源码运行和自行~~编译~~打包。

- 下载链接：[Releases](https://github.com/Pandaft/ESurfingPy-CLI/releases)

### 运行源码

建议 Python 3.12 或以上；Linux 用户优先使用上方的一键连接方式。

```shell
git clone git@github.com:admine-bit/ESufing.git ESurfingPy-CLI
cd ESurfingPy-CLI
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-gui.txt
.venv/bin/python main.py gui
```

<br />

## 参数说明

设备刚连上校园网络时自动弹出的，或者已经连上但未登录时打开任意网页跳转到下面这个登录网页，其中有此程序要的参数：

![./docs/images/2.png](./docs/images/2.png)

1. `ESurfingURL` ：校园网登录网址（部分），需要带端口。未登录时可能会出现域名解析错误（未能连接DNS服务器），可以先手动登录校园网后，使用 ping 等网络工具解析，然后用 `IP:端口` 代替，例如：`125.88.59.131:10001`
2. `WlanACIP` ：校园网的认证服务器IP，应该每个学校都不同；
3. `WlanUserIP` ：要登录的设备的IP，**可以不是本机的，实现远程登录**；
4. `Account` ：校园网账号
5. `Password` ：校园网账号的密码

<br />

## 命令行

```shell
> ./ESurfingPy-CLI.exe --help
Usage: ESurfingPy-CLI.exe [OPTIONS] COMMAND [ARGS]...

  基于 Python 实现登录和登出广东天翼校园网网页认证通道的命令行工具。

Options:
  --help  Show this message and exit.

Commands:
  auto     多种模式触发重登校园网
  gui      启动图形界面
  login    登录校园网
  logout   登出校园网
  ocr      识别图片
  version  输出当前版本
```

### 启动图形界面

```shell
> ./ESurfingPy-CLI.exe gui --help
Usage: ESurfingPy-CLI.exe gui [OPTIONS]

  启动图形界面

Options:
  -h, --hide-console BOOLEAN  隐藏控制台（仅适用于 Windows）  [default: True]
  --help                      Show this message and exit.
```

Linux 下无参数运行会读取 `config.ini` 连接校园网；其他系统无参数运行默认启动图形界面。
也可通过 `gui` 命令明确启动图形界面。

### 登录

```shell
> ./ESurfingPy-CLI.exe login --help
Usage: ESurfingPy-CLI.exe login [OPTIONS]

  登录校园网

Options:
  -u, --esurfing-url TEXT  校园网登录网址  [default: enet.10000.gd.cn:10001]
  -c, --wlan-acip TEXT     认证服务器IP
  -r, --wlan-userip TEXT   登录设备IP
  -a, --account TEXT       账号
  -p, --password TEXT      密码
  -v, --verbose BOOLEAN    输出详细过程  [default: True]
  --help                   Show this message and exit.
```

**本机登录校园网的话，`-u`, `-c`, `-r` 可以不填，程序会尝试自动获取。**

示例：`./ESurfingPy-CLI.exe login -u 125.88.59.131:10001 -c 123.123.123.123 -r 234.234.234.234 -a 15012341234 -p 12345678 -v true`

### 登出

```shell
> ./ESurfingPy-CLI.exe logout --help
Usage: ESurfingPy-CLI.exe logout [OPTIONS]

  登出校园网

Options:
  -u, --esurfing-url TEXT  校园网登录网址
  -c, --wlan-acip TEXT     认证服务器IP
  -r, --wlan-userip TEXT   登录设备IP
  -a, --account TEXT       账号
  -p, --password TEXT      密码
  -s, --signature TEXT     签名
  -v, --verbose BOOLEAN    输出详细过程  [default: True]
  --help                   Show this message and exit.
```

- 如果填写了 `signature` ，不需要填写 `password` ；
- 如果没有填写 `signature` ，需要填写账号和密码，程序会尝试登录来获取 `signature` 然后再登出。

`signature` 可以登录获得（即使重复登录），可以自己写程序将登录时返回的 `signature` 保存下来，需要时再读取使用。

示例：`./ESurfingPy-CLI.exe logout -u 125.88.59.131:10001 -c 123.123.123.123 -r 234.234.234.234 -a 15012341234 -s XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX -v true`

### 识别验证码

```shell
> ESurfingPy-CLI.exe ocr --help
Usage: ESurfingPy-CLI.exe ocr [OPTIONS]

  识别图片

Options:
  -i, --image TEXT  图片路径
  --help            Show this message and exit.
```

示例：`./ESurfingPy-CLI.exe ocr -i code.png`

### 多种模式自动重登

```shell
> ./ESurfingPy-CLI.exe auto --help
Usage: ESurfingPy-CLI.exe auto [OPTIONS]

  多种模式触发重登校园网

Options:
  -m, --mode [net|uls|dls|ult|dlt|itv|mul]
                                  触发模式
  -t, --threshold FLOAT           触发网速(MB/s)或流量(MB)或时间(s)
  -s, --auto-stop BOOLEAN         自动停止(仅对网速模式有效)  [default: True]
  -u, --esurfing-url TEXT         校园网登录网址  [default: enet.10000.gd.cn:10001]
  -c, --wlan-acip TEXT            认证服务器IP
  -r, --wlan-userip TEXT          登录设备IP
  -a, --account TEXT              账号
  -p, --password TEXT             密码
  -v, --verbose BOOLEAN           输出详细过程  [default: True]
  --help                          Show this message and exit.
```

触发模式：

|  值  |                                   值备注 | 说明                                       |
|:---:|--------------------------------------:|------------------------------------------|
| net |                        <u>net</u>work | 每间隔指定的时间（s）检测网络，断网时自动重登校园网               |
| uls |     <u>u</u>p<u>l</u>oad <u>s</u>peed | 实时监控**上传**速率（MB/s），连续 10s 低于指定值时自动重登校园网。 |
| dls |   <u>d</u>own<u>l</u>oad <u>s</u>peed | 实时监控**下载**速率（MB/s），连续 10s 低于指定值时自动重登校园网。 |
| ult |   <u>u</u>p<u>l</u>oad <u>t</u>raffic | 实时监控**上传**流量（MB），达到指定值时自动重登校园网。          |
| dlt | <u>d</u>own<u>l</u>oad <u>t</u>raffic | 实时监控**下载**流量（MB），达到指定值时自动重登校园网。          |
| itv |         <u>i</u>n<u>t</u>er<u>v</u>al | 每间隔指定的时间（s）自动重登校园网。                      |
| mul |           <u>m</u>an<u>u</u>a<u>l</u> | 手动回车后重登校园网。                              |

示例：

- 间隔 5 秒检测网络，当网络断开时自动登录：

`./ESurfingPy-CLI.exe auto -m net -t 5 -u 125.88.59.131:10001 -c 123.123.123.123 -r 234.234.234.234 -a 15012341234 -p 12345678 -v true`

- 实时监控上传速率，连续 10s 低于 3MB/s 时自动重登：

`./ESurfingPy-CLI.exe auto -m uls -t 3 -u 125.88.59.131:10001 -c 123.123.123.123 -r 234.234.234.234 -a 15012341234 -p 12345678 -v true`

- 实时监控下载流量，达到 600MB 时自动重登：

`./ESurfingPy-CLI.exe auto -m dlt -t 600 -u 125.88.59.131:10001 -c 123.123.123.123 -r 234.234.234.234 -a 15012341234 -p 12345678 -v true`

<br />

## 应用示例

### 1. Win10 快速一键登录/登出

利用快捷方式，可以实现带参数启用程序：

![./docs/images/3.png](./docs/images/3.png)

记得不要移动原文件，否则快捷方式会不可用。

### 2. Win10 开机自动登录校园网

根据上述制作一个登录的快捷方式，然后按下 `Win` + `R` 输入 `shell:startup` 并确定，
将登录的快捷方式拖进弹出的窗口，如果杀毒软件提示有程序想自启就点允许就可以了。

### 3. 更多

可以自己开发脚本或程序，设定特定条件后调用此程序，来实现更多的功能等等……

<br />

## 项目不足

由于使用 Python 语言开发：

- 运行效率较低，特别是打包后的可执行文件，在打开时需要较长的加载时间；
- 不能交叉编译，对应平台的可执行文件需要对应的平台进行打包，对于百花齐放拥有众多发行版的 Linux 来说，Ubuntu 打包的也不一定能在 Debian 中运行；
 
由于使用网页认证接口实现核心登录和登出功能：

- 部分学校禁用了网页认证登录，只能通过客户端登录，该项目不适合这部分学校；
- 需要提交验证码，项目通过使用 ddddocr 库来识别验证码，但是在打包时需要将模型文件也打包进行，带来额外的文件体积，而且部分系统可能无法运行。

而以上不足，都在我的新项目 [go-esurfing](https://github.com/Pandaft/go-esurfing) 中得到解决。

<br />

## 免责声明

**此项目仅供研究、学习和交流，请勿用于商业或非法用途，
开发者与协作者不对使用者负任何法律责任，
使用者自行承担因不当使用所产生的后果与责任。**

**This project is only for research, learning and exchange. 
Do not use it for commercial or illegal purposes. 
Developers and collaborators do not assume any legal responsibility for users. 
Users bear the consequences and responsibilities arising from improper use.**

<br />

## 其他

广东天翼校园网 QQ 交流群：791455104
（[点此加入](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=yTA84KiemCppMD5Y2CDepUsnVRo59dOS&authKey=CH%2Bb2yFiTVPqLOjdwrEGXGVvmhWTURTFX8yM5eRA7ipWh5fOKAIpJRqCKDIWZT7V&noverify=0&group_code=791455104)）
