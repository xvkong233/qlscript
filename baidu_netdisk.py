"""
new Env('百度网盘多合一签到')

cron: 30 8 * * *

百度网盘多合一每日签到（青龙订阅版）

基于 Sitoi/dailycheckin 的 baiduwp 模块重写，
接口均来自真实抓包验证（2026-10）。

功能：成长值签到 / 每日答题 / PC 客户端积分签到 / 任务中心签到 /
     自动补签（最近优先，每月 5 张 SVIP 无门槛卡+金币通道）/ 会员信息查询

环境变量：
  BAIDUWP_COOKIE         百度网盘 cookie，必填（两种写法可混用）：
                           ① 单变量多账号：值内用 & 或换行分隔
                           ② 编号轮询：BAIDUWP_COOKIE、BAIDUWP_COOKIE_1、
                              BAIDUWP_COOKIE_2、...（每个变量一个账号，
                              编号连续，断号后连续 3 个缺失停止扫描）
                  值只需 BDUSS=...; STOKEN=...（成长值/积分通道仅 BDUSS 可用，
                  任务中心与补签需要 STOKEN，建议两个都带上）。

  BAIDUWP_DELAY    每日随机延迟上限（分钟），默认 10：脚本启动后随机等待
                   0~10 分钟再执行，使每天实际签到时间不同；设为 0 关闭。
                   手动调试时可设 0 立即执行。

  --- 任务中心「设备登记」相关（详见文件末尾 §任务中心设备登记说明）---
  BAIDUWP_DEVICE          指定本机使用的任务中心设备标识（全局，覆盖自动派生）
  BAIDUWP_DEVICE_n        第 n 个账号专用的设备标识（优先于 BAIDUWP_DEVICE）
  BAIDUWP_DEVICE_POOL     备用「已登记」设备池，多台用 & 或 , 分隔；
                          运行期内每台最多服务一个账号，避免自造 dev repeat
  BAIDUWP_DEVICE_FILE     设备登记表落盘路径，默认脚本同目录
                          .baidu_taskcenter_device.json
  BAIDUWP_DEVICE_RESET    置 1 时清空登记的设备绑定（下次运行重新生成/指定）
  BAIDUWP_DEVICE_COOLDOWN 设备风控冷却秒数，默认 43200（12 小时）

  获取方式见仓库 Wiki「Cookie 获取教程」。
  STOKEN 失效特征：推送中出现"任务中心签到失败: STOKEN 已失效"，
            其余功能不受影响，届时重新取一次 cookie 更新环境变量即可。

依赖：requests（青龙 依赖管理 -> Python3 -> 安装 requests）
"""

import gzip
import hashlib
import json
import os
import random
import re
import sys
import time
import zlib

import requests

API_BASE = "https://pan.baidu.com"
QUERY_PARAMS = {"app_id": "250528", "web": "1", "clienttype": "5", "clientinfo": "wap"}
TIMEOUT = 15
# PC 客户端/任务中心通道使用的 UA（抓包自 PC 客户端 8.8.8.101 与新版 App 13.34.3）
PC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) baidunetdisk/8.8.8 Chrome/108.0.5359.215 Electron/22.3.27 "
    "Safari/537.36;netdisk;8.8.8.101;PC;PC-Windows;10.0.26200;WindowsBaiduYunGuanJia",
    "Referer": "https://pan.baidu.com/operation/activitys/goldcoin",
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
}
TASK_BASE = {
    "clienttype": "1", "channel": "android_16_script_bd-netdisk_1027840c",
    "app": "android", "version": "13.34.3", "versioncode": "4228",
}

# 任务中心签到仅接受「已登记」设备，且一台设备不能同时服务多个账号。
#
# 逆向 App 13.34.3 得到的设备标识供给链：
#   bd_netdisk://com.baidu.netdisk.hybrid/getClientInfo
#     -> com.baidu.netdisk.ui.webview.hybrid.ClientInfoHelper.getClientInfo()
#          cuid   = CommonParam.getCUID(context)            (=> DeviceId.getCUID)
#          devuid = com.baidu.netdisk.kernel.architecture.AppCommon.DEVUID
#   com.baidu.netdisk.startup.task.CUID3StartupTask.initDeviceId():
#          先从 PersonalConfig["deviceId"] 读回，有就直接复用；
#          只有首次启动才 DeviceId.getCUID() 生成一次并写回配置。
# 即：设备标识是「安装维度一次性生成、永久复用」的稳定量，与 cookie/登录态无关。
#
# 服务端侧（实测）：
#   /coins/taskcenter/signin 先做参数校验（缺 clienttype/cuid/devuid/task_id/
#   task_from 任一即 errno=2 "param error"），通过后再查「账号↔设备」登记记录：
#     未登记           -> "param error"
#     已被别的账号占用 -> "dev repeat"
#   /coins/taskcenter/checkdevmp 即 App 的 PointCenterApi.checkDeviceUnique()，
#   errno==0 表示「本账号下该设备是新的（没有登记记录）」。
#
# 因此脚本必须保证：①同账号永远上报同一台设备；②同一天不把同一台设备喂给不同账号。
# 本文件把 ① 的绑定关系与 ② 的冷却时间戳都持久化到磁盘。
DEVICE_STATE_FILE = os.getenv("BAIDUWP_DEVICE_FILE", "").strip() or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".baidu_taskcenter_device.json")
# 备用「已在服务端登记」的设备池：仅在账号自有设备被拒时兜底，
# 且运行期内每台最多服务一个账号（见 DeviceRegistry.acquire_shared）。
DEFAULT_DEVICE_POOL = ("5ACF9C71D2E84B0FA6C8D2E91F3A7B55|dailycheckin",)
# dev repeat 期间该设备处于服务端校验窗口，冷却时间内不再重撞
DEV_REPEAT_COOLDOWN = max(0, int(os.getenv("BAIDUWP_DEVICE_COOLDOWN", "43200") or 43200))
DEVICE_STATE_TTL = 180 * 86400

_DEVICE_RE = re.compile(r"^[A-Za-z0-9_.\-]{6,128}(\|[A-Za-z0-9_.\-]{1,64})?$")


def _is_valid_device(device) -> bool:
    """宽松校验设备标识：非空、无空白与分隔符冲突即可（服务端并不校验形态）。"""
    return bool(device) and bool(_DEVICE_RE.match(device)) and "&" not in device


class DeviceRegistry:
    """任务中心「账号 ↔ 设备」登记表（落盘持久化）。

    磁盘结构::

        {
          "version": 1,
          "accounts": {"<account_key>": {"device": "...", "used_at": 0}},
          "devices":  {"<device>": {"cooldown_until": 0, "is_new_device": null}}
        }
    """

    def __init__(self, path: str):
        self.path = path
        self.data = {"version": 1, "accounts": {}, "devices": {}}
        self._run_shared_users = {}      # device -> account_key（仅本次进程运行期）
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self.data["accounts"] = raw.get("accounts") or {}
                self.data["devices"] = raw.get("devices") or {}
                self._gc()
        except FileNotFoundError:
            pass
        except Exception:                # noqa: BLE001 状态文件损坏不应阻塞签到
            pass

    def save(self):
        try:
            self._gc()
            tmp = f"{self.path}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:                # noqa: BLE001 只读文件系统下降级为内存态
            pass

    def _gc(self):
        now = time.time()
        for key in list(self.data["accounts"]):
            if now - float(self.data["accounts"][key].get("used_at") or now) > DEVICE_STATE_TTL:
                self.data["accounts"].pop(key, None)
        for dev in list(self.data["devices"]):
            item = self.data["devices"][dev]
            if (not item.get("cooldown_until")
                    and now - float(item.get("last_used") or now) > DEVICE_STATE_TTL):
                self.data["devices"].pop(dev, None)

    def device_for(self, account_key: str, derive):
        """返回该账号已登记的设备；没有则用 derive() 现场生成一台并登记。"""
        item = self.data["accounts"].get(account_key) or {}
        device = str(item.get("device") or "")
        if not _is_valid_device(device):
            device = derive()
            self.data["accounts"][account_key] = {
                "device": device, "registered": None,
                "checked_at": 0, "used_at": time.time(),
            }
            self.save()
        return device

    def bind(self, account_key: str, device: str):
        item = self.data["accounts"].setdefault(account_key, {})
        item["device"] = device
        item["used_at"] = time.time()
        self.save()

    def note_check(self, device: str, is_new: bool):
        """记录 checkdevmp 探测结果（errno==0 -> 服务端认为该设备是新设备）。"""
        item = self.data["devices"].setdefault(device, {})
        item["is_new_device"] = bool(is_new)
        item["checked_at"] = time.time()
        self.save()

    def is_known_new(self, device: str):
        return (self.data["devices"].get(device) or {}).get("is_new_device")

    def in_cooldown(self, device: str) -> bool:
        return float((self.data["devices"].get(device) or {}).get("cooldown_until") or 0) > time.time()

    def cooldown_left(self, device: str) -> int:
        left = float((self.data["devices"].get(device) or {}).get("cooldown_until") or 0) - time.time()
        return max(0, int(left))

    def set_cooldown(self, device: str, seconds: int, account_key: str = ""):
        item = self.data["devices"].setdefault(device, {})
        item["cooldown_until"] = time.time() + max(0, seconds)
        item["last_used"] = time.time()
        if account_key:
            item["last_account"] = account_key
        self.save()

    def acquire_shared(self, device: str, account_key: str) -> bool:
        """备用设备池独占：本次运行内同一台共享设备只允许一个账号使用。"""
        owner = self._run_shared_users.get(device)
        if owner is None:
            self._run_shared_users[device] = account_key
            return True
        return owner == account_key

# 补签方式: 1=SVIP 无门槛卡(每月5张) 2=做任务 3=金币


class BaiduPan:
    def __init__(self, cookie: str, index: int = 1, registry: DeviceRegistry = None):
        cookie = cookie.strip()
        if "BDUSS=" not in cookie:
            cookie = f"BDUSS={cookie}"
        self.cookie = cookie
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/90.0.4430.91 Mobile Safari/537.36",
                "Referer": "https://pan.baidu.com/wap/svip/growth/task",
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Cookie": cookie,
            }
        )
        self.registry = registry or DeviceRegistry(DEVICE_STATE_FILE)
        # 账号 uid 只用来做设备派生的稳定锚点，取不到则退化为 STOKEN/cookie 哈希
        self.uid = ""
        self.account_key = ""
        self.device = ""
        self._resolve_device_identity()
        # 补签通道（signinlist/supptasklist/suppsignin）与签到通道共用同一台设备，
        # 保证服务端看到的「账号 ↔ 设备」绑定在所有任务中心接口上是一致的。
        self.task_base = {**TASK_BASE, "cuid": self.device, "devuid": self.device}

    # ---------- 任务中心设备身份 ----------
    def get_uid(self) -> str:
        """取账号 uid(uk)，只作为设备派生的稳定锚点；失败不阻塞主流程。"""
        try:
            data = self._pc_api("/api/loginstatus", {"clienttype": "1"})
            uk = str((data.get("login_info") or {}).get("uk") or "")
            if uk and uk != "0":
                return uk
        except (RuntimeError, requests.RequestException):
            pass
        try:
            data = self._api_get("/rest/2.0/xpan/nas", {"method": "uinfo"})
            uk = str(data.get("uk") or "")
            if uk and uk != "0":
                return uk
        except (RuntimeError, requests.RequestException):
            pass
        return ""

    def _account_key(self) -> str:
        """账号稳定锚点：uid > STOKEN(md5) > 整串 cookie(md5)。"""
        if self.uid:
            return f"uk:{self.uid}"
        m = re.search(r"STOKEN=([^;,\s]+)", self.cookie)
        if m:
            return "stoken:" + hashlib.md5(m.group(1).encode("utf-8")).hexdigest()
        return "cookie:" + hashlib.md5(self.cookie.encode("utf-8")).hexdigest()

    @staticmethod
    def _legacy_device(cookie: str) -> str:
        """升级前的老算法（md5(cookie)|前8位）：首次登记时沿用，保住已存在的服务端绑定。"""
        digest = hashlib.md5(cookie.encode("utf-8")).hexdigest().upper()
        return f"{digest}|{digest[:8]}"

    @staticmethod
    def _derive_device(account_key: str) -> str:
        """按 App 设备标识形态生成：<32位大写HEX>|<8位小写HEX>。

        由账号稳定身份派生，保证同账号永远同一台设备，重建状态文件也能复现。
        """
        head = hashlib.md5(
            f"netdisk-taskcenter|{account_key}|cuid".encode("utf-8")).hexdigest().upper()
        tail = hashlib.md5(
            f"netdisk-taskcenter|{account_key}|devuid".encode("utf-8")).hexdigest()[:8]
        return f"{head}|{tail}"

    def _resolve_device_identity(self):
        self.uid = self.get_uid()
        self.account_key = self._account_key()
        if os.getenv("BAIDUWP_DEVICE_RESET", "").strip() in ("1", "true", "True"):
            self.registry.data["accounts"].pop(self.account_key, None)
            self.registry.save()
        override = (os.getenv(f"BAIDUWP_DEVICE_{self.index}", "").strip()
                    or os.getenv("BAIDUWP_DEVICE", "").strip())
        if override and not _is_valid_device(override):
            print(f"  BAIDUWP_DEVICE 形态异常已忽略: {override[:24]}...", flush=True)
            override = ""
        if override:
            # 显式指定时不动登记表里原有的绑定，去掉环境变量即可恢复
            self.device = override
        else:
            # 首次登记沿用老算法设备（老用户零回归，保住服务端可能已存在的绑定）；
            # 若已确认它在服务端就是"新设备"（没有登记记录），则改用由账号稳定身份
            # 派生的确定性设备 —— 它不随 cookie 变化，重建状态文件也能复现。
            # 无论走哪条，一旦落盘就被冻结，不再随 cookie 变化 ——
            # 这是设备能长期保持"已登记"状态的前提。
            legacy = self._legacy_device(self.cookie)
            fallback = (self._derive_device(self.account_key)
                        if self.registry.is_known_new(legacy) is True else legacy)
            self.device = self.registry.device_for(self.account_key, lambda: fallback)

    def _device_candidates(self):
        """按优先级返回 [(标签, 设备)]：账号自有 -> 环境变量指定 -> 备用已登记池。"""
        candidates = [("账号自有设备", self.device)]
        override = (os.getenv(f"BAIDUWP_DEVICE_{self.index}", "").strip()
                    or os.getenv("BAIDUWP_DEVICE", "").strip())
        if override and _is_valid_device(override) and override != self.device:
            candidates.append(("环境变量指定设备", override))
        pool = os.getenv("BAIDUWP_DEVICE_POOL", "").strip()
        pool = [d.strip() for d in re.split(r"[&,]+", pool) if d.strip()] if pool else []
        for device in list(pool) + list(DEFAULT_DEVICE_POOL):
            if _is_valid_device(device) and all(device != d for _, d in candidates):
                candidates.append(("备用已登记设备", device))
        return candidates

    @staticmethod
    def _decode_json(resp, path: str) -> dict:
        """解析响应 JSON（自行解压，兼容网关错误页谎报 Content-Encoding）。

        百度网关的 404/5xx 错误页会给出 Content-Encoding: gzip，而 body 其实是明文 HTML。
        requests 在 stream=False 时会在 session.get() 内部就把 body 读完并解压，
        解码失败直接抛 ContentDecodingError —— 真正的 HTTP 状态码被完全掩盖
        （表现为"网络请求异常"，看不到 404）。所以这里统一 stream=True 拿响应：
        先判状态码，再自行按 Content-Encoding 解压，解压失败就按明文继续。
        """
        raw = b""
        if resp.raw is not None:
            try:
                raw = resp.raw.read(decode_content=False)
            except Exception:            # noqa: BLE001
                raw = b""
        encoding = (resp.headers.get("Content-Encoding") or "").strip().lower()
        if encoding in ("gzip", "x-gzip"):
            try:
                raw = gzip.decompress(raw)
            except Exception:            # noqa: BLE001 网关谎报编码，按明文继续
                pass
        elif encoding == "deflate":
            for fn in (zlib.decompress, lambda b: zlib.decompress(b, -zlib.MAX_WBITS)):
                try:
                    raw = fn(raw)
                    break
                except Exception:        # noqa: BLE001
                    continue
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            raise RuntimeError(
                f"{path} 响应非 JSON（HTTP {resp.status_code}，"
                f"body 前 80 字节: {raw[:80]!r}；cookie 可能已失效）")

    def _api_get(self, path: str, extra_params: dict, headers: dict = None) -> dict:
        params = dict(QUERY_PARAMS)
        params.update(extra_params)
        resp = self.session.get(API_BASE + path, params=params,
                                headers=headers, timeout=TIMEOUT, stream=True)
        if resp.status_code != 200:
            resp.close()
            raise RuntimeError(f"{path} 请求失败 HTTP {resp.status_code}")
        return self._decode_json(resp, path)

    def _pc_api(self, path: str, params: dict) -> dict:
        resp = self.session.get(API_BASE + path, params=params,
                                headers=PC_HEADERS, timeout=TIMEOUT, stream=True)
        if resp.status_code != 200:
            resp.close()
            raise RuntimeError(f"{path} 请求失败 HTTP {resp.status_code}")
        return self._decode_json(resp, path)

    @staticmethod
    def _not_logged_in(data: dict) -> bool:
        error_msg = str(data.get("error_msg") or data.get("show_msg") or "")
        return data.get("error_code") == -6 or "登录" in error_msg or "login" in error_msg.lower()

    def get_username(self) -> str:
        try:
            resp = self.session.get(API_BASE + "/api/user/getinfo",
                                    params={"need_selfinfo": "1"}, timeout=TIMEOUT)
            records = (resp.json().get("records") or [])
            if records:
                info = records[0]
                return (info.get("nick_name") or info.get("priority_name")
                        or info.get("display_name") or "")
        except Exception:
            pass
        return ""

    # ---------- 1. 成长值签到 ----------
    def get_sign_status(self):
        """返回 (today_signed, signed_cnt)；异常时 (None, None)，调用方降级为直接尝试签到。"""
        data = self._api_get("/rest/2.0/membership/level", {"method": "signinlist"})
        if self._not_logged_in(data):
            raise RuntimeError("BDUSS 已失效，请重新获取 cookie")
        if data.get("error_code") != 0:
            return None, None
        inner = data.get("data") or {}
        return inner.get("today_signed"), inner.get("signed_cnt")

    def signin(self):
        """返回 (points, error_msg)。"""
        data = self._api_get("/rest/2.0/membership/level", {"method": "signin"})
        if self._not_logged_in(data):
            raise RuntimeError("BDUSS 已失效，请重新获取 cookie")
        if data.get("error_code") == 0:
            return (data.get("result") or {}).get("points"), ""
        error_msg = data.get("error_msg") or "未知错误"
        if data.get("error_code") == 421001 or "repeat" in str(error_msg):
            return None, "今日已签到"
        return None, f"签到失败: {error_msg} (error_code={data.get('error_code')})"

    def growth_signin(self) -> str:
        today_signed, signed_cnt = self.get_sign_status()
        if today_signed:
            return f"今日已签到，已连续签到 {signed_cnt} 天" if signed_cnt else "今日已签到"
        points, error_msg = self.signin()
        if points is not None:
            msg = f"签到成功，获得 {points} 成长值"
            if signed_cnt is not None:
                msg += f"，已连续签到 {signed_cnt + 1} 天"
            return msg
        return error_msg or "签到失败"

    # ---------- 2. 每日答题 ----------
    def answer_daily_question(self) -> str:
        data = self._api_get("/act/v2/membergrowv2/getdailyquestion", {})
        if data.get("errno") not in (0, None):
            return ""
        inner = data.get("data") or {}
        ask_id, answer, status = inner.get("ask_id"), inner.get("answer"), inner.get("answer_status")
        if not ask_id:
            return ""
        if status == 1:
            return "今日已答题"
        if answer is None:
            return "今日题目暂无答案，跳过答题"
        result = self._api_get("/act/v2/membergrowv2/answerquestion",
                               {"ask_id": ask_id, "answer": answer})
        if self._not_logged_in(result):
            raise RuntimeError("BDUSS 已失效，请重新获取 cookie")
        if result.get("errno") == 9502:
            return "今日已答题"
        score = (result.get("data") or {}).get("score")
        if score is not None:
            return f"答题成功，获得 {score} 成长值"
        show_msg = (result.get("data") or {}).get("show_msg") or result.get("show_msg") or "答题失败"
        return f"答题: {show_msg}"

    # ---------- 3. PC 积分签到 ----------
    def pc_signin(self) -> str:
        status = self._pc_api("/coins/pc/signinlist", {"clienttype": "8", "win64": "1", "vip": "2"})
        if status.get("errno") != 0:
            return f"积分签到状态查询失败: {status.get('error') or status.get('errno')}"
        inner = status.get("data") or {}
        if inner.get("signed_today"):
            return f"积分今日已签到，当前积分余额 {inner.get('points_balance')}"
        result = self._pc_api("/coins/pc/signin", {})
        if result.get("errno") != 0:
            return f"积分签到失败: {result.get('error') or result.get('errno')}"
        return f"积分签到成功，当前积分余额 {inner.get('points_balance')}"

    # ---------- 4. 任务中心签到 ----------
    def _taskcenter_signin_once(self, device: str) -> dict:
        params = {"cuid": device, "devuid": device, **TASK_BASE}
        params.update({
            "task_id": "1666916321758720", "task_id_str": "1666916321758720",
            "task_from": "task_sys_daily", "is_growth": "1",
        })
        return self._pc_api("/coins/taskcenter/signin", params)

    def _taskcenter_checkdev(self, device: str) -> dict:
        """App 的 PointCenterApi.checkDeviceUnique()：GET /coins/taskcenter/checkdevmp。

        用来确认「本账号下这台设备是不是新设备（即没有登记记录）」：
        errno == 0 -> 服务端认为该设备是新的（未登记）。
        这一步同时把设备信息上报给任务中心，等价于 App 打开任务中心首页时做的事。
        """
        return self._pc_api("/coins/taskcenter/checkdevmp",
                            {"cuid": device, "devuid": device, **TASK_BASE})

    def _taskcenter_signin_device(self, device: str, tries: int = 3):
        """在指定设备上尝试签到；仅 dev repeat 做退避重试。返回 (data, error)。"""
        data, error = {}, ""
        for attempt in range(tries):
            try:
                data = self._taskcenter_signin_once(device)
            except (RuntimeError, requests.RequestException) as e:
                return {"errno": -1, "error": str(e)}, str(e)
            error = str(data.get("error") or "")
            if data.get("errno") == 0 or "dev repeat" not in error:
                return data, error
            wait = 15 * (attempt + 1)
            print(f"    设备重复触发风控(dev repeat)，{wait}s 后重试({attempt + 1}/{tries})...",
                  flush=True)
            time.sleep(wait)
        return data, error

    def taskcenter_signin(self) -> str:
        """任务中心签到：按「账号自有设备 -> 环境变量指定 -> 备用已登记池」依次尝试。

        对照 App 行为修正的三点：
          * 设备标识必须长期稳定（App 是一次生成永久复用），否则永远是"新设备"；
          * dev repeat 只是该设备进入服务端校验窗口，应换下一台继续，而不是直接放弃；
          * param error 说明该设备没有登记记录，用 checkdevmp 复核并给出可执行指引；
          * 任何设备失败后写入冷却时间戳，下次运行不再无脑重撞同一台。
        """
        notes = []
        need_register = False
        for label, device in self._device_candidates():
            if device != self.device and not self.registry.acquire_shared(device, self.account_key):
                notes.append(f"{label}(本次运行已被其它账号占用)")
                continue
            if self.registry.in_cooldown(device):
                left = self.registry.cooldown_left(device)
                notes.append(f"{label}(风控冷却中，约{max(1, left // 3600)}h后解除)")
                continue

            print(f"  使用{label}签到...", flush=True)
            data, error = self._taskcenter_signin_device(device)
            if data.get("errno") == 0:
                # 只有账号自有设备才回写绑定；备用池是公共兜底资源，
                # 一旦永久绑定给某个账号，其它账号就再也用不上它了。
                if device == self.device:
                    self.registry.bind(self.account_key, device)
                self.registry.set_cooldown(device, 0, self.account_key)
                days = (data.get("data") or {}).get("signin_days")
                return f"任务中心签到完成，累计 {days} 天"

            if "bduss" in error.lower() or "login" in error.lower():
                return "任务中心签到失败: STOKEN 已失效，请更新配置中的完整 cookie"

            if "dev repeat" in error:
                self.registry.set_cooldown(device, DEV_REPEAT_COOLDOWN, self.account_key)
                notes.append(f"{label}(设备校验中 dev repeat)")
                continue

            if "param error" in error:
                # 该设备没有「账号↔设备」登记记录：先用 App 的 checkdevmp 复核上报，
                # 再给它一次机会（部分账号在 checkdev 之后即可放行）。
                is_new = None
                try:
                    check = self._taskcenter_checkdev(device)
                    check_err = str(check.get("error") or "")
                    if check.get("errno") == 0:
                        is_new = True
                    elif "bduss" in check_err.lower() or "login" in check_err.lower():
                        return "任务中心签到失败: STOKEN 已失效，请更新配置中的完整 cookie"
                    else:
                        is_new = False
                except (RuntimeError, requests.RequestException):
                    pass
                if is_new is not None:
                    self.registry.note_check(device, is_new)
                if is_new:
                    need_register = True
                    notes.append(f"{label}(未登记)")
                    continue
                retry_data, retry_error = self._taskcenter_signin_device(device, tries=1)
                if retry_data.get("errno") == 0:
                    if device == self.device:
                        self.registry.bind(self.account_key, device)
                    days = (retry_data.get("data") or {}).get("signin_days")
                    return f"任务中心签到完成，累计 {days} 天"
                error = retry_error or error
                if "dev repeat" in error:
                    self.registry.set_cooldown(device, DEV_REPEAT_COOLDOWN, self.account_key)
                    notes.append(f"{label}(设备校验中 dev repeat)")
                    continue
                need_register = True
                notes.append(f"{label}(未登记)")
                continue

            notes.append(f"{label}({error or data.get('errno')})")

        detail = "；".join(notes) if notes else "无可用设备"
        if need_register:
            return (f"任务中心签到失败: 设备尚未在服务端登记（{detail}）。"
                    "请用官方 App 打开一次「任务中心/积分中心」完成该账号的设备登记，"
                    "或用 BAIDUWP_DEVICE/BAIDUWP_DEVICE_POOL 填入已登记设备后重跑")
        return f"任务中心签到未完成: {detail}"

    # ---------- 5. 自动补签 ----------
    def makeup_signin(self) -> str:
        calendar = self._pc_api("/coins/taskcenter/signinlist", dict(self.task_base))
        if calendar.get("errno") != 0:
            return f"补签检查失败: {calendar.get('error') or calendar.get('errno')}"
        inner = calendar.get("data") or {}
        start_time, now = inner.get("start_time"), inner.get("date")
        today_day = (now - start_time) // 86400 + 1 if start_time and now else 0
        # 最近的漏签日优先
        missed = sorted(
            [it["day"] for it in inner.get("signin_list", [])
             if isinstance(it, dict) and it.get("day", 0) < today_day and not it.get("signed")],
            reverse=True,
        )
        if not missed:
            return "补签检查: 本轮无漏签，无需补签"

        balance = None
        done, skipped = [], []
        for day in missed:
            if len(done) >= 5:  # 单次运行上限，防异常数据刷接口
                skipped.append(f"day{day}(达到单次上限)")
                continue
            try:
                pre = (self._pc_api("/coins/taskcenter/supptasklist",
                                    {**self.task_base, "day": str(day)}).get("data")) or {}
            except RuntimeError:
                skipped.append(f"day{day}(预检失败)")
                continue
            supp_type = pre.get("supp_type")
            if supp_type == 1:
                ok, note = True, "无门槛卡"
            elif supp_type == 3:
                cost = int(pre.get("coins_consumed") or 0)
                if balance is None:
                    home = self._pc_api("/coins/center/home", {"ptype": "5", "is_pc": "1"})
                    balance = int((home.get("data") or {}).get("coin_balance") or 0)
                if cost <= balance:
                    ok, note = True, f"金币{cost}"
                    balance -= cost
                else:
                    ok, note = False, f"day{day}(需{cost}金币，余额{balance}不足)"
            else:
                ok, note = False, f"day{day}(需做任务补签)"
            if not ok:
                skipped.append(note)
                continue
            try:
                result = self._pc_api("/coins/taskcenter/suppsignin",
                                      {**self.task_base, "day": str(day), "supp_type": str(supp_type)})
            except RuntimeError:
                skipped.append(f"day{day}(请求失败)")
                continue
            if result.get("errno") == 0:
                done.append(f"day{day}({note})")
            else:
                skipped.append(f"day{day}({result.get('error') or result.get('errno')})")

        msg = f"补签成功 {len(done)} 天" + (": " + "、".join(done) if done else "")
        if skipped:
            msg += f"；未处理 {len(skipped)} 天: " + "、".join(skipped)
        return msg

    # ---------- 6. 会员信息 ----------
    def userinfo(self):
        try:
            data = self._api_get("/rest/2.0/membership/user", {"method": "query"})
        except RuntimeError:
            return None, None
        if self._not_logged_in(data):
            raise RuntimeError("BDUSS 已失效，请重新获取 cookie")
        level_info = data.get("level_info") or {}
        return level_info.get("current_level"), level_info.get("current_value")

    # ---------- 主流程 ----------
    def run(self) -> str:
        msg = []
        try:
            msg.append(self.growth_signin())
            answer = self.answer_daily_question()
            if answer:
                msg.append(answer)
            try:
                msg.append(self.pc_signin())
                msg.append(self.taskcenter_signin())
                msg.append(self.makeup_signin())
            except (requests.RequestException, RuntimeError) as e:
                msg.append(f"积分/任务通道异常: {e.__class__.__name__}: {e}")
            level, value = self.userinfo()
            if level is not None:
                msg.append(f"当前会员等级 SVIP{level}，成长值 {value}")
        except requests.RequestException as e:
            return f"网络请求异常: {e.__class__.__name__}: {e}"
        except RuntimeError as e:
            return str(e)
        return "\n".join(msg)


def load_cookies() -> list:
    """轮询环境变量读取 cookie，支持两种写法（可混用，按顺序执行）：

    1. 单变量多账号：BAIDUWP_COOKIE 内用 & 或换行分隔
    2. 编号变量：BAIDUWP_COOKIE、BAIDUWP_COOKIE_1、BAIDUWP_COOKIE_2、...
       （编号需连续，中间断号后连续 3 个缺失即停止扫描）

    兼容直接粘贴浏览器完整 cookie 串（串内 & 字符不会导致误切分：
    含 BDUSS= 的值按 BDUSS= 边界切分账号）。
    """
    cookies: list = []

    def _split(value: str) -> list:
        if "BDUSS=" in value:
            # 按 BDUSS= 边界切分：完整 cookie 串里的 & 等字符不影响
            parts = [p.lstrip("; ").strip() for p in re.split(r"(?=BDUSS=)", value)]
            return [p for p in parts if p.startswith("BDUSS=") and len(p) > 20]
        return [c.strip() for c in re.split(r"[&\n]+", value) if c.strip()]

    base = os.getenv("BAIDUWP_COOKIE", "").strip()
    if base:
        cookies.extend(_split(base))
    misses = 0
    for i in range(1, 100):
        var = os.getenv(f"BAIDUWP_COOKIE_{i}", "").strip()
        if var:
            misses = 0
            cookies.extend(_split(var))
        else:
            misses += 1
            if misses >= 3:
                break
    # 去重（保持顺序），避免同一账号重复执行
    seen, unique = set(), []
    for c in cookies:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    if unique:
        return unique
    # 兼容 config.json（dailycheckin 格式）
    for path in ("config.json", "/ql/scripts/config.json"):
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    datas = json.load(f)
                return [str(c.get("cookie") or "").strip()
                        for c in datas.get("BAIDUWP", []) if c.get("cookie")]
            except Exception:
                pass
    return []


def random_delay():
    """启动随机延迟（默认 0~10 分钟），让每天实际执行时间有差异。"""
    max_minutes = 10
    raw = os.getenv("BAIDUWP_DELAY", "").strip()
    if raw.isdigit():
        max_minutes = int(raw)
    if max_minutes <= 0:
        return
    seconds = random.randint(0, max_minutes * 60)
    print(f"随机延迟 {seconds // 60} 分 {seconds % 60} 秒后开始（BAIDUWP_DELAY={max_minutes} 分钟内随机）...", flush=True)
    time.sleep(seconds)


def main():
    random_delay()
    cookies = load_cookies()
    if not cookies:
        print("未配置 cookie 环境变量：BAIDUWP_COOKIE（或 BAIDUWP_COOKIE_1、_2 ...）")
        sys.exit(1)
    registry = DeviceRegistry(DEVICE_STATE_FILE)
    results = []
    for i, cookie in enumerate(cookies, 1):
        panel = BaiduPan(cookie, index=i, registry=registry)
        username = panel.get_username()
        header = f"===== 账号 {i} 【{username}】=====" if username else f"===== 账号 {i} ====="
        print(header)
        try:
            msg = panel.run()
        except Exception as e:  # noqa: BLE001
            msg = f"执行异常: {e.__class__.__name__}: {e}"
        print(msg, "\n")
        if "HTTP 4" in msg or "已失效" in msg:
            msg += "\n（提示：该账号 cookie 可能无效或已失效，请核对对应的环境变量）"
        results.append(f"{header}\n{msg}")
        if i < len(cookies):
            gap = random.randint(3, 15)
            print(f"等待 {gap}s 后处理下一个账号...", flush=True)
            time.sleep(gap)
    registry.save()
    # 青龙通知（存在 notify.py 则推送）
    try:
        from notify import send  # type: ignore
        send("百度网盘签到", "\n\n".join(results))
    except Exception:
        pass


if __name__ == "__main__":
    main()
