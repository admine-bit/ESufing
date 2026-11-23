import binascii
import json
import re
import time
from urllib.parse import parse_qs, urlsplit

import rsa

from . import log, ocr
from .http import create_session

DEFAULT_ESURFING_URL = "enet.10000.gd.cn:10001"


class ESurfing:

    def __init__(self,
                 account: str,
                 password: str = "",
                 signature: str = "",
                 esurfingurl: str = DEFAULT_ESURFING_URL,
                 wlanacip: str = "",
                 wlanuserip: str = "",
                 verbose: bool = True):
        """实例化"""
        self.account = account
        self.password = password
        self.signature = signature
        if not all([esurfingurl, wlanacip, wlanuserip]):
            _, self.esurfingurl, self.wlanacip, self.wlanuserip, = get_parameters()
        else:
            self.esurfingurl = esurfingurl
            self.wlanacip = wlanacip
            self.wlanuserip = wlanuserip
        self.verbose = verbose

    def login(self):
        """登录"""
        success, signature = login(account=self.account,
                                   password=self.password,
                                   esurfingurl=self.esurfingurl,
                                   wlanacip=self.wlanacip,
                                   wlanuserip=self.wlanuserip,
                                   verbose=self.verbose)
        if success:
            self.signature = signature
        return success, signature

    def logout(self):
        """登出"""
        return logout(account=self.account,
                      password=self.password,
                      signature=self.signature,
                      esurfingurl=self.esurfingurl,
                      wlanacip=self.wlanacip,
                      wlanuserip=self.wlanuserip,
                      verbose=self.verbose)


def parse_parameters(url):
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    acip = query.get("wlanacip", [""])[0]
    userip = query.get("wlanuserip", [""])[0]
    if parsed.scheme in ("http", "https") and parsed.netloc and acip and userip:
        return True, parsed.netloc, acip, userip
    return False, None, None, None


def get_parameters(verbose: bool = False, session=None, timeout=8):
    """
    获取 esurfingurl, wlanacip, wlanuserip 参数
    本机未登录校园网时才可通过此方法获取上述参数
    """
    try:
        session = session or create_session()
        response = session.get(url="http://connect.rom.miui.com/generate_204", timeout=timeout)
        for item in [response] + list(reversed(response.history)):
            result = parse_parameters(item.url)
            if result[0]:
                return result
    except Exception as exc:
        if verbose:
            log.error(f"获取参数失败：{exc}")
    return False, None, None, None


def login(account: str, password: str,
          esurfingurl: str = DEFAULT_ESURFING_URL, wlanacip: str = "", wlanuserip: str = "",
          retry: int = 10, verbose: bool = True, session=None, timeout=8):
    """
    登录校园网
    account, password 必填参数；
    esurfingurl, wlanacip, wlanuserip 选填参数，本机登录且未登录时可自动获取；
    retry: 选填参数，最大重试次数；
    verbose: 选填参数，输出过程。
    """

    # 记录
    log_data = {
        "time": time.time(),  # 开始时间
        "times": 0  # 验证码识别错误次数（不符合条件的不算）
    }

    # 判断是否缺少参数：account, password
    if not all([account, password]):
        return False, log.error("登录失败：缺少 Account, Password 参数")

    # 判断是否缺少参数：esurfingurl, wlanacip, wlanuserip
    if not all([esurfingurl, wlanacip, wlanuserip]):
        if verbose:
            log.warning("缺少 ESurfingUrl, WlanACIP, WlanUserIP 参数，尝试获取中……")
        success, esurfingurl, wlanacip, wlanuserip = get_parameters(session=session, timeout=timeout)
        if not success:
            return False, log.error("登录失败：缺少 ESurfingUrl, WlanACIP, WlanUserIP 参数，且自动获取失败")
        if verbose:
            log.info("获取成功：")
            log.info(f"  - ESurfingUrl: {esurfingurl}")
            log.info(f"  - WlanACIP: {wlanacip}")
            log.info(f"  - WlanUserIP: {wlanuserip}")

    session = session or create_session()
    session.cookies.set("loginUser", account)
    retry = max(1, retry)
    while True:

        # 访问认证登录页面
        try:
            if verbose:
                log.info("正在请求获取登录页面...")
            resp = session.get(
                url=f"http://{esurfingurl}/qs/index_gz.jsp",
                params={"wlanacip": wlanacip, "wlanuserip": wlanuserip},
                timeout=timeout,
            )
            if verbose:
                log.info("请求获取登录页面成功")
        except Exception as exc:
            return False, log.error(f"请求获取登录页面失败：{exc}")

        # 正则匹配验证码网址
        try:
            if verbose:
                log.info('正在获取验证码网址...')
            vcode_path = re.search(r'/common/image_code\.jsp\?time=\d+', str(resp.content)).group()
            vcode_url = f'http://{esurfingurl}{vcode_path}'
            if verbose:
                log.info('获取验证码网址成功')
        except Exception as exc:
            return False, log.error(f"获取验证码网址失败：{exc}")

        for captcha_attempt in range(retry):
            # 获取并保存验证码
            try:
                if verbose:
                    log.info("正在获取验证码图片...")
                resp = session.get(url=vcode_url, timeout=timeout)
                if verbose:
                    log.info("获取验证码图片成功")
            except Exception as exc:
                return False, log.error(f"请求获取验证码失败：{exc}")

            # 识别验证码
            try:
                if verbose:
                    log.info("正在识别验证码...")
                log_time = time.time()
                ocr_succeed, ocr_result = ocr.ocr_image(resp.content)
                time_taken = round(time.time() - log_time, 2)

                # 识别失败
                if not ocr_succeed:
                    return False, log.error(f"识别验证码失败：{ocr_result}")
                if len(ocr_result) < 4:
                    if verbose:
                        log.warning("验证码识别结果不符合条件，重新获取新的验证码...")
                    continue

                # 识别成功
                ocr_result = ocr_result[0:4]
                if verbose:
                    log.info(f'识别验证码成功：{ocr_result}  耗时：{time_taken}s')
                break
            except Exception as exc:
                return False, log.error(f"识别验证码失败：{exc}")
        else:
            return False, log.error("验证码连续识别失败，已停止重试")

        # 计算 loginKey
        try:
            log_time = time.time()
            if verbose:
                log.info('正在计算 loginKey ...')
            modules = int("b2867727e19e1163cc084ea57b9fa8406a910c6703413fa7df96c1acdca7b983"
                          "a262e005af35f9485d92cd4c622eca4a14d6fd818adca5cae73d9d228b4ef05d"
                          "732b41fb85f80af578a150ebd9a2eb5ececb853372ca4731ca1c868689298740"
                          "9be3247f9b26cae8e787d8c135fc0652ec0678a5eda0c3d95cc1741517c0c9c3", 16)
            public_key = rsa.PublicKey(modules, 65537)
            data = json.dumps({
                "userName": account,
                "password": password,
                "rand": ocr_result,
            }, separators=(',', ':'))
            if len(data) > 117:
                return False, log.error("账号或密码长度过长")
            encrypted_data = rsa.encrypt(data.encode(), public_key)
            login_key = binascii.b2a_hex(encrypted_data).decode()
            time_taken = round(time.time() - log_time, 2)
            if verbose:
                log.info(f"完成计算，耗时：{time_taken}s")
        except Exception as exc:
            return False, log.error(f"计算 loginKey 失败：{exc}")

        # 发送登录请求
        try:
            if verbose:
                log.info('正在发送登录请求...')
            resp = session.post(
                url=f'http://{esurfingurl}/ajax/login',
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
                },
                data={"loginKey": login_key, "wlanuserip": wlanuserip, "wlanacip": wlanacip},
                timeout=timeout,
            )
            if not resp.ok:
                return False, log.error(f"登录请求回应异常，HTTP 状态码：{resp.status_code}，返回文本：{resp.text}")
        except Exception as exc:
            return False, log.error(f'发送登录请求失败：{exc}')

        # 判断登录结果
        try:
            result = resp.json()
            result_code = str(result['resultCode'])
            result_info = result.get('resultInfo', '')
        except (ValueError, KeyError, TypeError):
            return False, log.error("认证服务器未返回有效的登录结果")

        # 登录成功 / 重复登录
        if result_code in ['0', '13002000']:
            time_taken = round(time.time() - log_data['time'], 2)
            if result_code == '0':
                log.info(f'登录成功，总耗时 {time_taken}s，失败 {log_data["times"]} 次')
            elif result_code == '13002000':
                log.warning(f'重复登录，总耗时 {time_taken}s，失败 {log_data["times"]} 次')
            return True, resp.cookies.get('signature', session.cookies.get('signature', ''))

        log_data['times'] += 1
        if log_data['times'] >= retry:
            log.error(f"登录失败，返回码：{result_code}  信息：{result_info}")
            return False, log.warning(f"已达到最大重试次数：{retry}，停止尝试登录")

        # 问题不大
        if result_code in [
            '11063000',  # 验证码错误
            '13005000',  # 请求认证超时
        ]:
            log.warning(result_info)
            continue

        # 问题很大
        if result_code in [
            '13012000',  # 密码错误
            '13004000',  # 用户认证失败（也可能是因为密码错误）
            '11064000',  # 账号登陆过于频繁
            '13018000',  # 禁止网页认证
            '13016000',  # 没有定购此产品
        ]:
            return False, log.error(result_info)

        # 未知情况
        if log_data["times"] < retry:
            log.warning(f"登录失败，返回码：{result_code}  信息：{result_info}")
            continue

        # 达到最大重试次数
        return False, log.error(f"登录失败，返回码：{result_code}  信息：{result_info}")


def logout(account: str,
           wlanacip: str, wlanuserip: str, esurfingurl: str = DEFAULT_ESURFING_URL,
           password: str = "", signature: str = "",
           verbose: bool = True, session=None, timeout=8):
    """
    登出校园网
    account 必填参数；
    esurfingurl, wlanacip, wlanuserip 必填参数；
    password, signature 至少填一项参数；
    verbose: 选填参数，输出过程。
    """

    # 记录
    log_data = {
        "time": time.time(),  # 开始时间
        "times": 0  # 验证码识别错误次数（不符合条件的不算）
    }

    # 判断是否缺少参数：password / signature
    if not any([password, signature]):
        return False, log.error("登出失败：缺少 Password, Signature 任一参数")

    # 判断是否缺少参数：esurfingurl, wlanacip, wlanuserip
    if not all([esurfingurl, wlanacip, wlanuserip]):
        return False, log.error("登出失败：缺少 ESurfingUrl, WlanACIP, WlanUserIP 参数")

    # 缺少 signature
    if not signature:
        # 尝试通过登录获取
        if verbose:
            log.warning('缺少 signature 参数，正在尝试通过登录获取该参数...')
        login_success, signature = login(account, password, esurfingurl, wlanacip, wlanuserip,
                                         verbose=verbose, session=session, timeout=timeout)

        # 登录失败
        if not login_success:
            return False, log.error("登出失败：缺少 signature 参数，且尝试通过登录获取失败")

        # 登录成功
        if not signature:
            return False, log.error("登出失败：服务器未返回 signature")

    # 请求登出
    try:
        if verbose:
            log.info('正在发送登出请求...')
        session = session or create_session()
        resp = session.post(
            url=f'http://{esurfingurl}/ajax/logout',
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.87 Safari/537.36 SE 2.X MetaSr 1.0',
                'Cookie': f'signature={signature}; loginUser={account}',
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
            },
            data={"wlanuserip": wlanuserip, "wlanacip": wlanacip},
            timeout=timeout,
        )
        if not resp.ok:
            return False, log.error(f"登出请求回应异常，HTTP 状态码：{resp.status_code}，返回文本：{resp.text}")
    except Exception as exc:
        return False, log.error(f'发送登出请求失败：{exc}')

    # 判断登出结果
    result_code = json.loads(resp.text)['resultCode']
    result_info = json.loads(resp.text)['resultInfo']

    # 登出成功 / 重复登出
    if result_code == '0':
        time_taken = round(time.time() - log_data["time"], 2)
        return True, log.info(f'登出成功，耗时 {time_taken}s')

    # 登出失败
    return False, log.error(f'登出失败，返回码：{result_code}  信息：{result_info}')
