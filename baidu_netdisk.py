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

  --- 日志与等级预估 ---
  BAIDUWP_DEBUG           置 1 打开 DEBUG 级日志（打印每次 HTTP 请求/响应摘要）
  BAIDUWP_LEVEL_TABLE     手工指定「等级:成长值门槛」表，形如 1:0,2:1000,5:10000；
                          默认自动向服务端查询（/rest/2.0/membership/level?method=config）
  BAIDUWP_DAILY_GROWTH    手工指定「每日基础增量」（不含任务奖励），仅当日增速来源
                          不可用时使用；SVIP 通常 30，普通会员 12。升级天数按「每日增量 + 当日任务奖励」计算

  日志与推送是分开的：stdout（青龙日志面板）打印全部过程细节，
  推送只发送每个账号的结果行。

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

# ---------------------------------------------------------------------------
# 日志 / 推送分离
#
#   日志(log)  : 写 stdout，带时间戳、账号标签与级别，供青龙日志面板排障；
#   推送(push) : 只放每个账号的结果行，一眼看完。
# 所有过程性输出一律走 log()；进入推送的文本由 BaiduPan.emit() 登记。
# ---------------------------------------------------------------------------
DEBUG = os.getenv("BAIDUWP_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")


def log(msg="", level="INFO", tag=""):
    """写详细日志到 stdout。绝不进推送；也绝不打印 cookie 内容。"""
    prefix = f"[{time.strftime('%H:%M:%S')}]"
    if tag:
        prefix += f"[{tag}]"
    if level and level != "INFO":
        prefix += f"[{level}]"
    for line in str(msg).splitlines() or [""]:
        print(f"{prefix} {line}", flush=True)


def log_debug(msg, tag=""):
    """仅 BAIDUWP_DEBUG 打开时输出。"""
    if DEBUG:
        log(msg, "DEBUG", tag)


def brief(value, limit=200):
    """把响应压成一行摘要，避免日志被大 JSON 淹没。"""
    try:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else f"{text[:limit]}…(len={len(text)})"


def structure_map(node, limit=90, max_depth=4):
    """把未知结构的 JSON 压成「路径 = 类型/样本」清单。

    用途：接口契约未知时，把 30KB 的原始 JSON 压成可贴回、可人工核对的一小段，
    而不是截断原始 JSON —— 截断恰好会把关键分支切掉（本轮就吃过这个亏）。
    """
    lines = []

    def walk(node, path, depth):
        if len(lines) >= limit:
            return
        pad = "  " * depth
        if isinstance(node, dict):
            lines.append(f"{pad}{path} = object({len(node)} keys)")
            for key, val in list(node.items()):
                walk(val, str(key), depth + 1)
        elif isinstance(node, (list, tuple)):
            lines.append(f"{pad}{path} = array({len(node)})")
            for i, val in enumerate(list(node)[:2]):
                walk(val, f"[{i}]", depth + 1)
        else:
            lines.append(f"{pad}{path} = {type(node).__name__} {str(node)[:48]}")

    if max_depth > 0:
        walk(node, "", 0)
    truncated = len(lines) >= limit
    body = chr(10).join(f"      {line}" for line in lines[:limit])
    if truncated:
        body += chr(10) + "      …(已截断，共 %d+ 行)" % len(lines)
    return body


def dump_json(payload, path_hint: str):
    """把原始响应全文落盘，便于离线核对；返回文件路径（失败返回空串）。"""
    try:
        target = os.path.join(os.path.dirname(os.path.abspath(DEVICE_STATE_FILE)), path_hint)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        return target
    except Exception:                # noqa: BLE001 只读目录下静默跳过
        return ""


def _mask_credential(value, keep=6):
    """凭据一律脱敏：只留头部若干字符与长度。"""
    raw = str(value or "")
    if len(raw) <= keep:
        return "*" * len(raw)
    return f"{raw[:keep]}…(len={len(raw)})"


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

# App 侧 hybrid 客户端信息签名密钥（HybridActionClientInfo.AK）。
# 官方客户端用它做设备-账号绑定签名: rchannel = MD5(AK + uid + time + channel)
APP_CLIENT_AK = "1e34f40405355a992583c9d7b166cd39"

# /coins/taskcenter/* 的实测错误码（只记录已实测到的语义，未验证的不臆测）。
TASKCENTER_ERRNO = {
    2: "服务端不认可该设备/参数（实测：该设备在本账号下无登记记录）",
    9230: "实测发生当日签到日历为「未签」，故不属于「今日已签」；且表现与"
          "账号1/2 的 param error 不同，提示该设备已通过登记校验，卡点在签到本身",
    9312: "该设备正在被其它账号使用或处于风控窗口",
}

# 等级预估：优先手工指定，其次向服务端要「等级↔成长值」档位表
LEVEL_TABLE_ENV = os.getenv("BAIDUWP_LEVEL_TABLE", "").strip()
DAILY_GROWTH_ENV = os.getenv("BAIDUWP_DAILY_GROWTH", "").strip()
# 服务端配置里可能出现的等级/成长值字段名（契约未固定，见 fetch_level_table 注释）
_LEVEL_KEYS = ("level", "growth_level", "growthlevel", "grade", "lvl", "current_level")
_VALUE_KEYS = ("value", "growth_value", "growthvalue", "min_value", "minvalue",
               "need_value", "threshold", "upgrade_value", "score")


def _parse_level_table(payload) -> list:
    """从服务端配置里挖出 [(level, threshold)]，升序。挖不干净就返回 []。

    契约未固定，这里只认两种形状：
      A) 显式字段： {"level": 3, "value": 10000}  /  [3, 10000]
      B) 键值映射： {"1": 0, "2": 1000, "3": 5000, ...}
    结果还会做单调性与长度校验 —— 宁可返回空，也不给错数。
    """
    strict, loose = {}, {}
    # 内层取门槛用的字段名
    threshold_keys = ("value", "level_value", "growth_value", "need_value",
                      "threshold", "min_value", "score")

    def add(bucket, level, value):
        try:
            lv, val = int(level), int(value)
        except (TypeError, ValueError):
            return
        if 1 <= lv <= 20 and 0 <= val <= 10 ** 9:
            bucket.setdefault(lv, val)

    def walk(node):
        if isinstance(node, dict):
            low = {str(k).lower(): v for k, v in node.items()}
            # 形态 A：同层显式字段 {"level": 3, "value": 10000}
            lv = next((low[k] for k in _LEVEL_KEYS if k in low), None)
            val = next((low[k] for k in _VALUE_KEYS if k in low), None)
            if lv is not None and val is not None and not isinstance(val, (dict, list)):
                add(strict, lv, val)
            for k, v in low.items():
                if isinstance(v, dict):
                    # 形态 C（实测 level_infos）：等级做键、门槛在内层字典的 value 字段
                    #   {"1": {"name": "level1", "value": 0, ...}, "2": {...}}
                    for tk in threshold_keys:
                        cand = v.get(tk)
                        if isinstance(cand, (int, float)) and not isinstance(cand, bool):
                            add(strict, k, cand)
                            break
                else:
                    # 形态 B：键值映射 {"1": 0, "2": 1000, ...}
                    add(loose, k, v)
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            if len(node) == 2 and not isinstance(node[0], (dict, list)):
                add(strict, node[0], node[1])
            for v in node:
                walk(v)

    walk(payload)
    for bucket in (strict, loose):
        pairs = sorted(bucket.items())
        values = [v for _, v in pairs]
        # 至少 3 档且门槛单调不减，才算像一张等级表
        if len(pairs) >= 3 and all(a <= b for a, b in zip(values, values[1:])):
            return pairs
    return []


# 每日增量取键优先级：年费(含自动续费/推荐官) > 季 > 月。
# 实测 level_detail.daily_increase.svip 形如
#   {vip2_1y: 30, vip2_1y_auto: 30, vip2_1y_tuijianguan: 30, vip2_3m: 20, vip2_1m: 20}
#   vip 侧 {vip1_1y: 12, vip1_3m: 10, vip1_1m: 5}
# 「年费」才是公开口径里的标准日增量（SVIP 30/天、VIP 12/天），故优先取年费档。
_DAILY_INCREASE_KEYS = ("vip2_1y", "vip2_1y_auto", "vip2_1y_tuijianguan",
                        "vip2_3m", "vip2_3m_auto", "vip2_1m", "vip2_1m_auto")


def _numeric_leaves(node, bucket):
    """把子树里的数值叶子（排除 bool）收集进 bucket。"""
    if isinstance(node, dict):
        for val in node.values():
            _numeric_leaves(val, bucket)
    elif isinstance(node, (list, tuple)):
        for val in node:
            _numeric_leaves(val, bucket)
    elif isinstance(node, bool):
        return
    elif isinstance(node, (int, float)):
        bucket.append(int(node))


def _parse_daily_increase(payload) -> int:
    """取「每日成长值增量」（level_detail.daily_increase），取不到返回 0。

    实测响应里形如:  "daily_increase": {"svip": {"vip2": 30}, "vip": {...}}
    与 "daily_decrease": 10（非会员每日扣减）成对出现。
    形状尚未完全确认，因此：只在同名键下取值、优先 svip 档、取该子树最大数值，
    并做 1..500 的合理性夹取；任何一步不满足就返回 0，交由调用方回退。
    """
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, val in node.items():
                if str(key).lower() == "daily_increase":
                    found.append(val)
                walk(val)
        elif isinstance(node, (list, tuple)):
            for val in node:
                walk(val)

    walk(payload)
    for branch in found:
        # 优先 svip 档（超级会员的每日增量最大，且脚本账号基本都是 SVIP）
        target = branch
        if isinstance(branch, dict):
            for key, val in branch.items():
                if str(key).lower() == "svip":
                    target = val
                    break
        bucket = []
        _numeric_leaves(target, bucket)
        bucket = [v for v in bucket if 1 <= v <= 500]
        if not bucket:
            continue
        # 1) 按产品档位优先取键（年费 > 季 > 月）
        if isinstance(target, dict):
            low = {str(k).lower(): v for k, v in target.items()}
            for key in _DAILY_INCREASE_KEYS:
                cand = low.get(key)
                if isinstance(cand, (int, float)) and not isinstance(cand, bool) \
                        and 1 <= int(cand) <= 500:
                    return int(cand)
        # 2) 退化为该档最大值
        return max(bucket)
    return 0


def describe_daily_increase(payload) -> str:
    """把 level_detail.daily_increase 的分档压成一行，便于日志核对。"""
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, val in node.items():
                if str(key).lower() == "daily_increase":
                    found.append(val)
                walk(val)
        elif isinstance(node, (list, tuple)):
            for val in node:
                walk(val)

    walk(payload)
    for branch in found:
        if isinstance(branch, dict):
            parts = []
            for tier, val in branch.items():
                bucket = []
                _numeric_leaves(val, bucket)
                if bucket:
                    parts.append(f"{tier}={max(bucket)}")
            return ", ".join(parts)
    return ""


def _parse_level_table_expr(text: str) -> list:
    """解析 BAIDUWP_LEVEL_TABLE，形如 '1:0,2:1000,5:10000'。"""
    pairs = {}
    for chunk in re.split(r"[,;\s]+", text or ""):
        if not chunk:
            continue
        parts = re.split(r"[:=]", chunk, 1)
        if len(parts) != 2:
            continue
        try:
            pairs[int(parts[0])] = int(parts[1])
        except ValueError:
            continue
    ordered = sorted(pairs.items())
    return ordered if len(ordered) >= 2 else []

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
        self.data = {"version": 1, "accounts": {}, "devices": {}, "growth": {}}
        self._run_shared_users = {}      # device -> account_key（仅本次进程运行期）
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self.data["accounts"] = raw.get("accounts") or {}
                self.data["devices"] = raw.get("devices") or {}
                self.data["growth"] = raw.get("growth") or {}
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

    def set_daily_growth(self, account_key: str, growth: int):
        """记录本账号实测的日成长速度，供「今天已签到」的后续运行复用。"""
        item = self.data["growth"].setdefault(account_key, {})
        item["daily_growth"] = int(growth)
        item["updated_at"] = time.time()
        self.save()

    def daily_growth(self, account_key: str) -> int:
        return int((self.data["growth"].get(account_key) or {}).get("daily_growth") or 0)

    def set_growth_value(self, account_key: str, value: int):
        """记录本次读到的成长值，作为下次推算实测日增量的基线。"""
        item = self.data["growth"].setdefault(account_key, {})
        item["last_value"] = int(value)
        item["last_ts"] = time.time()
        self.save()

    def growth_delta_rate(self, account_key: str, value: int, min_hours: float = 12.0):
        """用「上次成长值 -> 本次成长值」的实测差值推算该账号的日增量。

        实测数据：同一时刻三账号的成长值增量分别为 +0 / +20 / +30，对应不同
        产品档位（年费 30 / 季月 20）。档位表是全局的、列不出账号属于哪一档，
        而差值是这个账号自己的真实值，所以优先用它。

        要求间隔 >= min_hours：否则会把同一天内的任务奖励误当成年日增量。
        返回 (rate, span_hours)；不可用返回 (0, span_hours)。
        """
        item = self.data["growth"].get(account_key) or {}
        last_value, last_ts = item.get("last_value"), item.get("last_ts")
        if not isinstance(last_value, int) or not last_ts:
            return 0, 0.0
        span = (time.time() - float(last_ts)) / 3600.0
        if span < min_hours:
            return 0, span
        delta = int(value) - last_value
        if delta <= 0:
            return 0, span
        rate = int(round(delta / (span / 24.0)))
        return (rate, span) if 1 <= rate <= 500 else (0, span)

    def release_shared(self, device: str):
        """释放本次运行对共享设备的占用（失败时调用，避免瞬时问题烧掉整池）。"""
        self._run_shared_users.pop(device, None)

    def acquire_shared(self, device: str, account_key: str) -> bool:
        """备用设备池独占：本次运行内同一台共享设备只允许一个账号使用。"""
        owner = self._run_shared_users.get(device)
        if owner is None:
            self._run_shared_users[device] = account_key
            return True
        return owner == account_key

# 补签方式: 1=SVIP 无门槛卡(每月5张) 2=做任务 3=金币


class BaiduPan:
    log_tag = ""          # 类级默认值，避免非常规构造路径取不到该属性

    def __init__(self, cookie: str, index: int = 1, registry: DeviceRegistry = None):
        # 日志标签必须在最早设置：_resolve_device_identity 里就要用
        self.log_tag = f"账号{index}"
        self.index = index      # _resolve_device_identity 会读 BAIDUWP_DEVICE_{index}
        self.push = []          # 只进推送的结果行
        self.observed_growth = 0  # 本次实际获得的成长值（签到+答题）
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
        log(f"账号识别: uid={self.uid or '(未取到)'} account_key={self.account_key} "
            f"cookie=[BDUSS/STOKEN 已隐藏]", "INFO", self.log_tag)
        log(f"任务中心设备: {self.device}（来源: "
            f"{'环境变量指定' if self.device != self._legacy_device(self.cookie) else '登记表/老算法'}）",
            "INFO", self.log_tag)

    def emit(self, line: str) -> str:
        """登记一条「结果行」：进推送列表，同时在日志里留档。"""
        if line:
            self.push.append(line)
            log(line, "RESULT", self.log_tag)
        return line

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

    def _http_get(self, path: str, params: dict, headers: dict) -> dict:
        """统一出口：发请求 + 记录请求/响应摘要日志 + 统一错误。"""
        started = time.time()
        try:
            resp = self.session.get(API_BASE + path, params=params,
                                    headers=headers, timeout=TIMEOUT, stream=True)
        except requests.RequestException as e:
            log(f"HTTP {path} 连接失败: {e.__class__.__name__}: {e}", "ERR", self.log_tag)
            raise
        cost = time.time() - started
        if resp.status_code != 200:
            resp.close()
            log(f"HTTP {path} -> {resp.status_code}（{cost:.2f}s）", "ERR", self.log_tag)
            raise RuntimeError(f"{path} 请求失败 HTTP {resp.status_code}")
        data = self._decode_json(resp, path)
        log_debug(f"GET {path} params={brief(params)} -> {brief(data, 160)} "
                  f"({cost:.2f}s)", self.log_tag)
        return data

    def _api_get(self, path: str, extra_params: dict, headers: dict = None) -> dict:
        params = dict(QUERY_PARAMS)
        params.update(extra_params)
        return self._http_get(path, params, headers)

    def _pc_api(self, path: str, params: dict) -> dict:
        return self._http_get(path, params, PC_HEADERS)

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
        log(f"成长值签到: signinlist -> today_signed={today_signed} "
            f"signed_cnt={signed_cnt}", "INFO", self.log_tag)
        if today_signed:
            return f"今日已签到，已连续签到 {signed_cnt} 天" if signed_cnt else "今日已签到"
        points, error_msg = self.signin()
        log(f"成长值签到: signin -> points={points} error={error_msg or '无'}",
            "INFO", self.log_tag)
        if points is not None:
            try:
                self.observed_growth += int(points)
            except (TypeError, ValueError):
                pass
            msg = f"签到成功，获得 {points} 成长值"
            if signed_cnt is not None:
                msg += f"，已连续签到 {signed_cnt + 1} 天"
            return msg
        return error_msg or "签到失败"

    # ---------- 2. 每日答题 ----------
    def answer_daily_question(self) -> str:
        data = self._api_get("/act/v2/membergrowv2/getdailyquestion", {})
        if data.get("errno") not in (0, None):
            log(f"每日答题: 取题接口 errno={data.get('errno')} "
                f"show_msg={data.get('show_msg')}，跳过答题", "WARN", self.log_tag)
            return ""
        inner = data.get("data") or {}
        ask_id, answer, status = inner.get("ask_id"), inner.get("answer"), inner.get("answer_status")
        log(f"每日答题: ask_id={ask_id} answer_status={status} "
            f"answer={'-' if answer is None else answer}", "INFO", self.log_tag)
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
        log(f"每日答题: answerquestion -> errno={result.get('errno')} score={score}",
            "INFO", self.log_tag)
        if score is not None:
            try:
                self.observed_growth += int(score)
            except (TypeError, ValueError):
                pass
            return f"答题成功，获得 {score} 成长值"
        show_msg = (result.get("data") or {}).get("show_msg") or result.get("show_msg") or "答题失败"
        return f"答题: {show_msg}"

    # ---------- 3. PC 积分签到 ----------
    def pc_signin(self) -> str:
        status = self._pc_api("/coins/pc/signinlist", {"clienttype": "8", "win64": "1", "vip": "2"})
        log(f"PC 积分: signinlist -> errno={status.get('errno')} "
            f"signed_today={(status.get('data') or {}).get('signed_today')} "
            f"balance={(status.get('data') or {}).get('points_balance')}", "INFO", self.log_tag)
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
    def _taskcenter_today_signed(self):
        """读任务中心签到日历，判断今天是否已签。返回 True/False/None(取不到)。

        实测 errno 9230 "signin error" 只出现在已连续签到天数更多的账号上，
        高度疑似「今日任务中心已签到」。先查日历既能解释该错误码，也能省掉
        后面整串无意义的设备尝试。
        """
        try:
            cal = self._pc_api("/coins/taskcenter/signinlist", dict(self.task_base))
        except (RuntimeError, requests.RequestException):
            return None
        if cal.get("errno") != 0:
            return None
        inner = cal.get("data") or {}
        start, now = inner.get("start_time"), inner.get("date")
        if not start or not now:
            return None
        today = (now - start) // 86400 + 1
        for item in inner.get("signin_list") or []:
            if isinstance(item, dict) and item.get("day") == today:
                return bool(item.get("signed"))
        return None

    def _app_client_params(self, device: str) -> dict:
        """按官方客户端 getClientInfo 组装设备绑定参数。

        来源：com.baidu.netdisk.ui.webview.hybrid.ClientInfoHelper.getClientInfo()
          rchannel = MD5(AK + uid + time + channel)，AK 取 HybridActionClientInfo.AK
          rand / time 为 h5 侧 NetworkUtil.addRand 生成的请求随机数与时间戳
        客观限制：sofire 反欺诈指纹 z = com.baidu.sofire.ac.FH.gz(context) 由本地
        SDK 依据设备信号算出，脚本侧无法复现，因此不提供该字段。
        """
        ts = int(time.time())
        params = {
            "cuid": device, "devuid": device,
            "time": str(ts),
            "rand": str(random.randint(100000, 999999)),
            "channel": TASK_BASE["channel"],
        }
        if self.uid:
            params["rchannel"] = hashlib.md5(
                f"{APP_CLIENT_AK}{self.uid}{ts}{TASK_BASE['channel']}".encode("utf-8")
            ).hexdigest()
        return params

    def _taskcenter_signin_once(self, device: str, extra: dict = None) -> dict:
        params = {"cuid": device, "devuid": device, **TASK_BASE}
        if extra:
            params.update(extra)
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

    def _probe_device_register(self, label: str, device: str):
        """问服务端：这台设备在本账号下是不是「新设备」（无登记记录）。

        对应 App 的 PointCenterApi.checkDeviceUnique() -> GET /coins/taskcenter/checkdevmp，
        errno == 0 表示「新设备」。返回 True / False / None(取不到结论)。
        """
        try:
            check = self._taskcenter_checkdev(device)
        except (RuntimeError, requests.RequestException) as e:
            log(f"  checkdevmp({label}) 请求失败: {e}", "WARN", self.log_tag)
            return None
        check_err = str(check.get("error") or "")
        if check.get("errno") == 0:
            is_new = True
        elif "bduss" in check_err.lower() or "login" in check_err.lower():
            is_new = None          # cookie 失效 -> 这是「取不到结论」，不能当成已登记
        else:
            is_new = False
        if is_new is not None:
            self.registry.note_check(device, is_new)
        log(f"  checkdevmp({label}) -> is_new_device={is_new}", "INFO", self.log_tag)
        return is_new

    def _dump_taskcenter_state(self, label: str):
        """签到失败且设备已在册时，把任务中心首页状态打进日志，定位非登记类失败。"""
        try:
            home = self._pc_api("/coins/taskcenter/home", dict(self.task_base))
        except (RuntimeError, requests.RequestException) as e:
            log(f"  任务中心首页读取失败: {e}", "WARN", self.log_tag)
            return
        if home.get("errno") != 0:
            log(f"  任务中心首页 errno={home.get('errno')} "
                f"error={home.get('error') or home.get('errmsg')}", "WARN", self.log_tag)
            return
        log(f"  任务中心首页({label}) data: {brief(home.get('data'), 320)}",
            "INFO", self.log_tag)

    def _taskcenter_signin_device(self, device: str, tries: int = 3):
        """在指定设备上尝试签到；仅 dev repeat 做退避重试。返回 (data, error)。"""
        data, error = {}, ""
        for attempt in range(tries):
            try:
                data = self._taskcenter_signin_once(device)
            except (RuntimeError, requests.RequestException) as e:
                return {"errno": -1, "error": str(e)}, str(e)
            error = str(data.get("error") or "")
            if data.get("errno") not in (0, None) and "dev repeat" not in error:
                # 未知服务端错误码（如 9230 signin error）只留 errno 无法定位，留全量响应
                log(f"    signin 原始响应: {brief(data, 320)}", "WARN", self.log_tag)
            if data.get("errno") == 0 or "dev repeat" not in error:
                return data, error
            wait = 15 * (attempt + 1)
            log(f"    设备重复触发风控(dev repeat)，{wait}s 后重试({attempt + 1}/{tries})...",
                "WARN", self.log_tag)
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
        # 先读服务端签到日历：今天已签就没必要再折腾设备（实测 errno 9230 即此情形）
        signed = self._taskcenter_today_signed()
        log(f"任务中心签到日历: today_signed={signed}", "INFO", self.log_tag)
        if signed is True:
            return "任务中心签到: 今日已签到"
        notes = []
        need_register = False
        for label, device in self._device_candidates():
            shared = device != self.device
            # 冷却优先判定：它才是更准确的原因（上一版会把「冷却中」误报成「被其它账号占用」）
            if self.registry.in_cooldown(device):
                left = self.registry.cooldown_left(device)
                notes.append(f"{label}(风控冷却中，约{max(1, left // 3600)}h后解除)")
                continue
            if shared and not self.registry.acquire_shared(device, self.account_key):
                notes.append(f"{label}(本次运行已被其它账号占用)")
                continue

            log(f"  尝试{label}: {device}", "INFO", self.log_tag)
            # 账号自有设备做退避重试（可能是瞬时风控）；备用池是公共热设备，
            # 90 秒内不会恢复，重试只是白等，交给冷却时间戳判定即可。
            data, error = self._taskcenter_signin_device(
                device, tries=1 if shared else 3)
            log(f"  {label} -> errno={data.get('errno')} error={error or '无'}",
                "INFO", self.log_tag)
            if data.get("errno") == 0:
                # 只有账号自有设备才回写绑定；备用池是公共兜底资源，
                # 一旦永久绑定给某个账号，其它账号就再也用不上它了。
                if device == self.device:
                    self.registry.bind(self.account_key, device)
                self.registry.set_cooldown(device, 0, self.account_key)
                days = (data.get("data") or {}).get("signin_days")
                return f"任务中心签到: 完成，累计 {days} 天"

            if "bduss" in error.lower() or "login" in error.lower():
                log("任务中心签到失败: 服务端返回 bduss 错误，说明 cookie 缺少有效的 "
                    "STOKEN（任务中心通道必须带 STOKEN）", "ERR", self.log_tag)
                return "任务中心签到: 失败（完整 cookie 已失效，需含 STOKEN）"

            if "dev repeat" in error:
                self.registry.set_cooldown(device, DEV_REPEAT_COOLDOWN, self.account_key)
                notes.append(f"{label}(设备校验中 dev repeat)")
                self.registry.release_shared(device)
                continue

            # 任何「非 dev repeat」的失败都先无条件问一次服务端：这台设备在本账号下
            # 是不是「新设备」（无登记记录）。
            # 不只在 param error 分支里探，是因为实测账号 3 拿到的是 errno 9230 而非
            # param error —— 若只在 param error 里探，就永远拿不到它的设备登记状态，
            # 诊断信息是残缺的，也没法判断卡点到底在不在登记。
            is_new = self._probe_device_register(label, device)
            if is_new is False:
                # 设备已在册 —— 卡点不是登记，再走登记流程毫无意义，
                # 直接把真实错误码、解读和任务中心首页状态打出来。
                hint = TASKCENTER_ERRNO.get(data.get("errno"), "")
                log(f"  设备已在册但签到仍失败: errno={data.get('errno')} "
                    f"error={error or '无'}" + (f"  —— {hint}" if hint else ""),
                    "WARN", self.log_tag)
                self._dump_taskcenter_state(label)
                # 共享设备在本账号下失败时释放占用，让同轮其它账号还能试
                if shared:
                    self.registry.release_shared(device)
                notes.append(f"{label}(已登记但服务端仍拒绝 errno={data.get('errno')})")
                continue
            # 设备未登记（或状态未知）：按官方客户端流程补上设备绑定参数再试。
            # cuid/devuid 只是标识；App 的每个请求还会带 rchannel/rand/time，
            # 其中 rchannel = MD5(AK + uid + time + channel) 才是把设备与账号
            # 绑定的签名。缺它时服务端可能无从登记该设备 -> param error。
            try:
                app_data = self._taskcenter_signin_once(
                    device, self._app_client_params(device))
            except (RuntimeError, requests.RequestException) as e:
                app_data = {"errno": -1, "error": str(e)}
            app_err = str(app_data.get("error") or "")
            log(f"  按客户端流程重试({label}) -> errno={app_data.get('errno')} "
                f"error={app_err or '无'}", "INFO", self.log_tag)
            if app_data.get("errno") == 0:
                if device == self.device:
                    self.registry.bind(self.account_key, device)
                days = (app_data.get("data") or {}).get("signin_days")
                return f"任务中心签到: 完成，累计 {days} 天"
            if "bduss" in app_err.lower() or "login" in app_err.lower():
                return "任务中心签到: 失败（完整 cookie 已失效，需含 STOKEN）"
            # 第二优先：不带附加参数再试一次（覆盖 checkdevmp 有登记副作用的假设）
            retry_data, retry_error = self._taskcenter_signin_device(device, tries=1)
            if retry_data.get("errno") == 0:
                if device == self.device:
                    self.registry.bind(self.account_key, device)
                days = (retry_data.get("data") or {}).get("signin_days")
                return f"任务中心签到: 完成，累计 {days} 天"
            error = retry_error or error
            if "dev repeat" in error:
                self.registry.set_cooldown(device, DEV_REPEAT_COOLDOWN, self.account_key)
                notes.append(f"{label}(设备校验中 dev repeat)")
                continue
            need_register = True
            notes.append(f"{label}(未登记)")
            continue


        detail = "；".join(notes) if notes else "无可用设备"
        if need_register:
            log(f"任务中心签到失败（设备未登记）明细: {detail}", "ERR", self.log_tag)
            # 实测确认：App 登记的是「它自己的 devuid」，脚本派生的这台不会被登记；
            # 只做第 1 步没用，必须把 App 的 devuid 取出来给脚本用。
            log("处理办法（两步都要做，只做第 1 步没用）:", "ERR", self.log_tag)
            log("  1) 用官方 App 登录该账号，打开一次「任务中心/积分中心」—— "
                "这一步把 App 自己的 devuid 登记到服务端", "ERR", self.log_tag)
            log("  2) 取出该 App 的 devuid，填进 BAIDUWP_DEVICE_n（n=账号序号）。"
                "脚本派生的是另一台设备，App 不会替它登记", "ERR", self.log_tag)
            log("     取 devuid 最省事：手机抓包看 App 打开任务中心时请求 URL 里的 "
                "devuid= 参数（cuid= 通常同值）", "ERR", self.log_tag)
            log("     备选：App 配置存于 MMKV 的 deviceId 键，但该文件 RC4 加密，"
                "不推荐手抠", "ERR", self.log_tag)
            return "任务中心签到: 失败（设备未在服务端登记）"
        log(f"任务中心签到失败明细: {detail}", "WARN", self.log_tag)
        return f"任务中心签到: 失败（{detail}）"

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
            log(f"  补签 day{day}: supp_type={supp_type} "
                f"coins_consumed={pre.get('coins_consumed')}", "INFO", self.log_tag)
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

        if done:
            log(f"补签成功明细: {'、'.join(done)}", "INFO", self.log_tag)
        if skipped:
            log(f"补签跳过明细: {'、'.join(skipped)}", "INFO", self.log_tag)
        msg = f"补签: 成功 {len(done)} 天"
        if skipped:
            msg += f"，跳过 {len(skipped)} 天"
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

    # ---------- 7. 等级与升级预估 ----------
    def fetch_level_table(self):
        """取「等级 ↔ 成长值门槛」档位表；返回 (pairs, 原始配置)。
        原始配置会透传给日增速解析（level_detail.daily_increase），所以
        即使档位表拿不到，每日增量仍可能拿到。

        数据源优先级：
          1) BAIDUWP_LEVEL_TABLE 手工指定（形如 1:0,2:1000,5:10000）
          2) /rest/2.0/membership/level?method=config
             —— 即 App/H5 的 getUpgradeLevelConfig（会员中心「成长值与等级关系表」）
        两者都拿不到就返回 []，ETA 不显示；宁可不说，也不猜一个数出来。
        """
        if LEVEL_TABLE_ENV:
            pairs = _parse_level_table_expr(LEVEL_TABLE_ENV)
            if pairs:
                log(f"等级档位表来源: BAIDUWP_LEVEL_TABLE -> {pairs}", "INFO", self.log_tag)
                return pairs, None
            log("BAIDUWP_LEVEL_TABLE 无法解析（形如 1:0,2:1000,5:10000），已忽略",
                "WARN", self.log_tag)
        try:
            data = self._api_get("/rest/2.0/membership/level", {"method": "config"})
        except (RuntimeError, requests.RequestException) as e:
            log(f"等级档位表获取失败: {e}", "WARN", self.log_tag)
            return [], None
        if data.get("error_code") not in (0, None):
            log(f"等级档位表接口返回 error_code={data.get('error_code')} "
                f"error_msg={data.get('error_msg')}（该接口需要有效 cookie）",
                "WARN", self.log_tag)
            return [], data.get("data")
        pairs = _parse_level_table(data.get("data"))
        if not pairs:
            log("等级档位表解析失败：该接口返回的是「成长值获取规则」(level_detail)，"
                "未必含等级门槛表；下面给出结构清单供人工核对。", "WARN", self.log_tag)
            log("【结构清单】" + structure_map(data.get("data")), "WARN", self.log_tag)
            dumped = dump_json(data.get("data"), ".baidu_level_config_dump.json")
            if dumped:
                log(f"原始响应全文已落盘: {dumped}", "WARN", self.log_tag)
            return [], data.get("data")
        log(f"等级档位表来源: 服务端 method=config -> {pairs}", "INFO", self.log_tag)
        return pairs, data.get("data")

    def _daily_growth_rate(self, config=None, value=None) -> int:
        """日成长速度 = **每日增量 + 当日任务奖励**。

        官方公式: 成长值 =(开通 + 续费 + 每日×持续天数 + 任务)-(过期 + 解约)，
        所以「每日」与「任务」是两部分相加 —— 只拿本次签到/答题实测值当增速
        会严重低估（SVIP 的每日增量本身就有 30，任务奖励通常只有 10 上下）。

        每日增量来源优先级（从高到低）:
          1) BAIDUWP_DAILY_GROWTH —— 用户对该账号的精确指定
          2) 实测差值 —— 上次运行到本次运行成长值实际涨了多少（间隔需 >= 12h）
          3) 服务端 level_detail.daily_increase —— 全局档位表，取年费档
          4) 历史记录
        第 2 项之所以排在档位表之前：档位表是全局的，列不出「这个账号是哪一档」。
        实测三账号同刻增量为 +0/+20/+30，正好对应不同档位 —— 差值才是该账号的真实值。
        任务奖励 = 本次实测（签到 + 答题）；今天已签过则为 0，此时只算每日增量。
        """
        base, base_src = 0, "未知"
        if DAILY_GROWTH_ENV.isdigit() and int(DAILY_GROWTH_ENV) > 0:
            base, base_src = int(DAILY_GROWTH_ENV), "BAIDUWP_DAILY_GROWTH"
        if base <= 0 and value is not None:
            rate, span = self.registry.growth_delta_rate(self.account_key, value)
            if rate > 0:
                base, base_src = rate, f"实测差值(距上次 {span:.1f}h)"
            elif span > 0:
                log(f"实测差值不可用: 距上次仅 {span:.1f}h（需 >= 12h 才能排除任务奖励）",
                    "INFO", self.log_tag)
        if base <= 0 and config is not None:
            base = _parse_daily_increase(config)
            if base > 0:
                base_src = "服务端档位表(年费档，可能与本账号档位不符)"
                detail = describe_daily_increase(config)
                log(f"每日增量分档: {detail} -> 取 {base}/天", "INFO", self.log_tag)
        if base <= 0:
            stored = self.registry.daily_growth(self.account_key)
            if stored > 0:
                base, base_src = stored, "历史记录"
        task = self.observed_growth
        if base <= 0 and task <= 0:
            log("日成长速度: 未知（服务端配置与本地记录都没拿到，且本次未获得成长值）",
                "WARN", self.log_tag)
            return 0
        total = base + task
        log(f"日成长速度: {total}/天 = 每日{base}({base_src}) + 任务{task}(本次实测)",
            "INFO", self.log_tag)
        if base > 0:
            # 只持久化「每日增量」部分：它是账号长期属性，不含每天波动的任务奖励
            self.registry.set_daily_growth(self.account_key, base)
        if value is not None:
            # 记下本次成长值，作为下次推算实测日增量的基线
            self.registry.set_growth_value(self.account_key, value)
        return total

    def membership_report(self) -> str:
        """结果行：会员等级 / 成长值 / 距下一等级的预估天数。细节走日志。"""
        level, value = self.userinfo()
        if level is None:
            log("会员信息: 未取到 level_info", "WARN", self.log_tag)
            return ""
        level, value = int(level), int(value or 0)
        head = f"会员等级 SVIP{level}，成长值 {value}"
        pairs, config = self.fetch_level_table()
        nxt = next(((lv, th) for lv, th in pairs if lv > level), None)
        if nxt is None:
            if not pairs:
                log("等级档位表不可用，本次不给出升级天数预估。可设 BAIDUWP_LEVEL_TABLE "
                    "手工指定，形如 1:0,2:1000,5:10000", "WARN", self.log_tag)
            else:
                log(f"已是已知最高等级 SVIP{level}", "INFO", self.log_tag)
            return head
        next_level, threshold = nxt
        need = max(0, threshold - value)
        gain = self._daily_growth_rate(config, value)
        log(f"升级预估: SVIP{level}/{value} -> SVIP{next_level} 门槛 {threshold}，"
            f"还差 {need}，日增速 {gain or '未知'}", "INFO", self.log_tag)
        if need <= 0:
            return f"{head}；已达 SVIP{next_level} 门槛"
        if not gain or gain <= 0:
            return f"{head}；距 SVIP{next_level} 还差 {need}（日增速未知，暂不给天数）"
        days = -(-need // gain)
        return f"{head}；距 SVIP{next_level} 还差 {need}，约 {days} 天（+{gain}/天）"

    # ---------- 主流程 ----------
    def run(self):
        """执行本账号全部任务。

        返回：推送用结果行 list[str]（详细过程全部走 log() 进 stdout）。
        """
        self.push = []
        try:
            self.emit(self.growth_signin())
            self.emit(self.answer_daily_question())
            # 会员等级/升级预估不依赖积分与任务中心。放在它们之前计算，
            # 这样即使任务中心进入分钟级退避重试（多台设备累计可达数分钟），
            # 升级天数也一定能出现在推送里。
            self.emit(self.membership_report())
            try:
                self.emit(self.pc_signin())
                self.emit(self.taskcenter_signin())
                self.emit(self.makeup_signin())
            except (requests.RequestException, RuntimeError) as e:
                log(f"积分/任务通道异常: {e.__class__.__name__}: {e}", "ERR", self.log_tag)
                self.emit(f"积分/任务通道: 异常（{e.__class__.__name__}）")
        except requests.RequestException as e:
            log(f"网络请求异常: {e.__class__.__name__}: {e}", "ERR", self.log_tag)
            self.push.append(f"执行失败: 网络异常 {e.__class__.__name__}")
        except RuntimeError as e:
            log(f"执行中断: {e}", "ERR", self.log_tag)
            self.push.append(f"执行失败: {e}")
        return self.push


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
    results = []          # 仅结果行，进推送
    for i, cookie in enumerate(cookies, 1):
        log(f"{'=' * 60}")
        log(f"开始处理第 {i}/{len(cookies)} 个账号")
        panel = BaiduPan(cookie, index=i, registry=registry)
        username = panel.get_username()
        header = f"===== 账号 {i} 【{username}】=====" if username else f"===== 账号 {i} ====="
        log(f"账号昵称: {username or '(未取到)'}", "INFO", panel.log_tag)
        try:
            lines = panel.run()
        except Exception as e:  # noqa: BLE001
            log(f"执行异常: {e.__class__.__name__}: {e}", "ERR", panel.log_tag)
            lines = [f"执行异常: {e.__class__.__name__}"]
        lines = [line for line in lines if line]
        log("---- 本账号结果（同时会进推送）----", "INFO", panel.log_tag)
        for line in lines:
            log(f"  {line}", "INFO", panel.log_tag)
        log(f"账号 {i} 处理完毕，共 {len(lines)} 条结果", "INFO", panel.log_tag)
        results.append(f"{header}\n" + "\n".join(lines))
        if i < len(cookies):
            gap = random.randint(3, 15)
            log(f"等待 {gap}s 后处理下一个账号...", "INFO", panel.log_tag)
            time.sleep(gap)
    registry.save()
    # 青龙通知（存在 notify.py 则推送）：只推结果行
    try:
        from notify import send  # type: ignore
        send("百度网盘签到", "\n\n".join(results))
        log(f"推送完成，共 {len(results)} 个账号")
    except Exception:
        log("未找到 notify.py 或推送失败，跳过推送")


if __name__ == "__main__":
    main()
