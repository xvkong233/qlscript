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

  --- 任务中心（任务系统）通道 ---
  2026-10 真机抓包：金币乐园已下线，签到迁移到任务系统 H5
  （/operation/activitys/taskSystem/main），页面打开时自动调用
  /coins/taskcenter/signin，必须带 z / channel / offlinepackage 等完整客户端参数。
  points-center（signinv2/center）仅作旧账号回退。

  重要：z 是 sofire 反欺诈指纹（com.baidu.sofire.ac.FH.gz），由本机按
  「设备 + 登录态」算出，不能跨账号重放。内置 z 只属于抓包账号，
  其它账号跑这条通道只会拿到 errno=2；脚本会把 z 的归属账号记到
  登记表里并在后续运行自动跳过，不再每天白撞。

  BAIDUWP_TASKCENTER     任务中心通道总开关，置 0 完全关闭（只留成长值/答题/PC 积分）
  BAIDUWP_TASKCENTER_WEB 网页端通道（clienttype=5 + MAWEBCUID，不需要 z）开关，默认 1；
                          仅在 cookie 带 MAWEBCUID 时才会被尝试

  BAIDUWP_PROFILE         机型画像（默认 xiaomi17promax）：控制 channel 与 WebView UA 的机型/系统版本。
                          xiaomi17promax = Xiaomi 17 Pro Max / 2509FPN0BC / HyperOS 3 (Android 16)  ← 默认
                          xiaomi15       = Xiaomi 15 / 24129PN74C / HyperOS 2.0 (Android 15)
                          xiaomi14ultra  = Xiaomi 14 Ultra / 24031PN0DC / HyperOS 1.0 (Android 14)
                          xiaomi14       = Xiaomi 14 / 23127PN0CC / HyperOS 1.0 (Android 14)
                          vivo-v2364a    = 原抓包机（内置 z 的来源，需完全复刻时用）
                          型号码取自 khwang9883/MobileModels（小米机型汇总）。
                          客户端的 channel 与 UA 都从同一个 Build 取值，只改一处就会互相矛盾
                          （“channel 写小米、UA 写 vivo”比用错机型更像伪造），脚本会自动报警。

  BAIDUWP_Z               sofire 设备指纹（默认内置 MuMu/vivo V2364A 抓包值；
                          换设备后请用自己的抓包值覆盖）
  BAIDUWP_Z_n             第 n 个账号专用 z（优先于 BAIDUWP_Z）——多账号想走通
                          任务中心通道，必须每账号取自己的 z：在该账号登录的 App 上
                          跑 work/frida/get_clientinfo.py，取 FH.gz(context)
  BAIDUWP_CHANNEL         分发渠道（默认由画象推导 android_<版本>_<机型>_bd-netdisk_1027840c）
  BAIDUWP_CHANNEL_n       第 n 个账号专用渠道（优先于 BAIDUWP_CHANNEL）
  BAIDUWP_UA              WebView UA（默认由画象推导），与 channel 必须同机型/同版本

  BAIDUWP_DEVICE          指定本机使用的任务中心设备标识（全局，覆盖自动派生）
  BAIDUWP_DEVICE_n        第 n 个账号专用的设备标识（优先于 BAIDUWP_DEVICE）
  BAIDUWP_DEVICE_ROTATE   置 1 时为每个账号生成一台全新设备并重新建档（一次性动作，
                          跑完请删除；账号在服务端有设备上限，不能每次运行都换）
  BAIDUWP_DEVICE_POOL     备用设备池，多台用 & 或 , 分隔；遇 9312/8001 时兜底，
                          运行期内每台最多服务一个账号，避免自造 dev repeat
  BAIDUWP_DEVICE_FILE     设备登记表落盘路径，默认脚本同目录
                          .baidu_taskcenter_device.json
  BAIDUWP_DEVICE_RESET    置 1 时清空登记的设备绑定（下次运行重新生成/指定）
  BAIDUWP_DEVICE_COOLDOWN 设备风控冷却秒数，默认 43200（12 小时）
  BAIDUWP_TASKCENTER_LEGACY 置 1 时额外尝试旧版 /coins/taskcenter/signin
                          （当前客户端已不调用该接口，仅老账号兼容用，默认关）

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
    "clienttype": "1", "app": "android",
    "version": "13.34.3", "versioncode": "4228",
}

# ---------------------------------------------------------------------------
# 设备画像（机型指纹）：channel 与 UA 必须同源，否则一眼假
#
# 客户端 channel 的构造（jadx：newhome/fr10.java，mars 公共参数 Platform）：
#     "android_" + Build.VERSION.RELEASE + "_" + Build.MODEL + "_bd-netdisk_" + 后缀
# 网盘本体后缀为 1027840c（真机抓包：android_15_V2364A_bd-netdisk_1027840c，
# Release=15、Model=V2364A 均来自 Build）。
# WebView UA 里又同时带一遍 RELEASE 与 Build.MODEL：
#     Mozilla/5.0 (Linux; Android <RELEASE>; <MODEL> Build/<Build.ID>; wv) ...
# 所以两处必须取自同一个机型画像 —— “channel 写小米、UA 写 vivo”比用错机型
# 本身更像伪造。
#
# 画像均为真实在售/存量机型；默认 xiaomi14（23127PN0CC 是小米 14 国行的
# Build.MODEL，出厂 Android 14 / HyperOS 1.0）。
# ---------------------------------------------------------------------------
CHANNEL_SUFFIX = "1027840c"
DEVICE_PROFILES = {
    # 型号码（Build.MODEL）均取自 khwang9883/MobileModels 的小米机型汇总，
    # 括号里是官方 codename；build_id / chrome 取同代 Android 基线与该机型
    # 出货时的 WebView 大版本，保证「版本号 ↔ 机型」不打架。
    "xiaomi15": {
        # Xiaomi 15（dada）国行 24129PN74C：2024-10 发布，出厂 Android 15 / HyperOS 2.0
        "label": "Xiaomi 15 / 24129PN74C / HyperOS 2.0 (Android 15)",
        "model": "24129PN74C", "release": "15",
        "build_id": "AQ3A.240829.003", "chrome": "131.0.6778.135",
    },
    "xiaomi14ultra": {
        # Xiaomi 14 Ultra（aurora）国行 24031PN0DC：2024-02 发布，出厂 Android 14
        "label": "Xiaomi 14 Ultra / 24031PN0DC / HyperOS 1.0 (Android 14)",
        "model": "24031PN0DC", "release": "14",
        "build_id": "UKQ1.240103.001", "chrome": "121.0.6167.178",
    },
    "xiaomi17promax": {
        # Xiaomi 17 Pro Max（popsicle）2509FPN0BC：2025-09 发布，出厂 Android 16 / HyperOS 3
        "label": "Xiaomi 17 Pro Max / 2509FPN0BC / HyperOS 3 (Android 16)",
        "model": "2509FPN0BC", "release": "16",
        "build_id": "BP2A.250605.031.A3", "chrome": "140.0.7339.51",
    },
    "xiaomi14": {
        # Xiaomi 14（houji）国行 23127PN0CC：2023-10 发布，出厂 Android 14
        "label": "Xiaomi 14 / 23127PN0CC / HyperOS 1.0 (Android 14)",
        "model": "23127PN0CC", "release": "14",
        "build_id": "UKQ1.231003.002", "chrome": "120.0.6099.230",
    },
    "vivo-v2364a": {
        "label": "vivo V2364A（原抓包机，内置 z 的来源）",
        "model": "V2364A", "release": "15",
        "build_id": "V417IR", "chrome": "110.0.5481.154",
    },
}
DEFAULT_PROFILE = "xiaomi17promax"


def _profile_key(name: str) -> str:
    """把环境变量里的画像名归一化；写错就回落到默认机型，并在日志里说一声。"""
    key = (name or "").strip() or DEFAULT_PROFILE
    if key in DEVICE_PROFILES:
        return key
    log(f"BAIDUWP_PROFILE={key} 不在内置画像里，回落到 {DEFAULT_PROFILE}", "WARN")
    return DEFAULT_PROFILE


def _ua_webview(p: dict) -> str:
    """WebView UA（结构对齐真机抓包：版本号 + Build/<id> + wv + Version/4.0）。"""
    return (f"Mozilla/5.0 (Linux; Android {p['release']}; {p['model']} "
            f"Build/{p['build_id']}; wv) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Version/4.0 Chrome/{p['chrome']} Safari/537.36")


def _ua_browser(p: dict) -> str:
    """普通 Chrome UA（用于 REST 接口与网页预热，不带 wv/Version4）。"""
    return (f"Mozilla/5.0 (Linux; Android {p['release']}; {p['model']}) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{p['chrome']} Mobile Safari/537.36")


DEVICE_PROFILE_NAME = _profile_key(os.getenv("BAIDUWP_PROFILE", "").strip())
DEVICE_PROFILE = DEVICE_PROFILES[DEVICE_PROFILE_NAME]
PROFILE_CHANNEL = (f"android_{DEVICE_PROFILE['release']}_{DEVICE_PROFILE['model']}"
                   f"_bd-netdisk_{CHANNEL_SUFFIX}")
PROFILE_UA = _ua_webview(DEVICE_PROFILE)
PROFILE_BROWSER_UA = _ua_browser(DEVICE_PROFILE)

# 2026-10 真机抓包（App 13.34.3）：任务系统 H5 实际发送的
# /coins/taskcenter/signin 参数。缺 z/channel/offlinepackage 时服务端会在
# 「真要签的那一天」返回 errno=2 param error（已签日会短路返回，不足以验证）。
#   z            sofire 设备指纹 com.baidu.sofire.ac.FH.gz(context)
#   channel      分发渠道 android_<RELEASE>_<MODEL>_bd-netdisk_1027840c
#   offlinepackage 离线包版本表（服务端参数校验用）
# channel/UA 默认由设备画像推导；要换真实机型优先用 BAIDUWP_PROFILE，
# 确实要贴别人抓包值时再用 BAIDUWP_CHANNEL / BAIDUWP_UA（两者请同时换）。
TASK_CHANNEL = os.getenv("BAIDUWP_CHANNEL", "").strip() or PROFILE_CHANNEL
SOFIRE_Z = os.getenv("BAIDUWP_Z", "").strip() or     ("3F6OTvsektth3-SLi2w11NlkNuROxENXQ4tcVJU9Y2bUfkGryNBdGUb7sk"
     "ERYWTmmv2TVskuoIWo5J00p-4VLHA")
TASK_UA = os.getenv("BAIDUWP_UA", "").strip() or PROFILE_UA

# points-center H5（App 任务中心/积分中心 WebView）的请求头：
# 移动端 UA + 页面 Referer，与真实签到链路保持一致
CENTER_HEADERS = {
    "User-Agent": PROFILE_UA,
    "Referer": "https://pan.baidu.com/operation/activitys/points/main",
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
}
TASK_OFFLINE_PACKAGE = {
    "2004": {
        "version": 93
    },
    "8002": {
        "version": 21
    },
    "8102": {
        "version": 81
    },
    "123075": {
        "version": 23
    },
    "123422": {
        "version": 77
    },
    "123437": {
        "version": 9
    },
    "123441": {
        "version": 25
    },
    "123443": {
        "version": 19
    },
    "123465": {
        "version": 31
    },
    "123600": {
        "version": 12
    },
    "123700": {
        "version": 25
    },
    "123750": {
        "version": 21
    },
    "123781": {
        "version": 9
    },
    "123782": {
        "version": 5
    },
    "123787": {
        "version": 4
    },
    "123818": {
        "version": 66
    },
    "123890": {
        "version": 30
    },
    "123941": {
        "version": 15
    },
    "123942": {
        "version": 12
    },
    "200013": {
        "version": 24
    },
    "200017": {
        "version": 27
    },
    "300001": {
        "version": 43
    },
    "600001": {
        "version": 304
    },
    "600002": {
        "version": 70
    },
    "677531": {
        "version": 3
    },
    "677533": {
        "version": 10
    },
    "677536": {
        "version": 3
    },
    "700001": {
        "version": 11
    },
    "700022": {
        "version": 4
    },
    "800002": {
        "version": 29
    },
    "20240708": {
        "version": 33
    },
    "20241211": {
        "version": 4
    },
    "20250911": {
        "version": 48
    },
    "20251117": {
        "version": 32
    },
    "20260101": {
        "version": 9
    },
    "20260316": {
        "version": 3
    },
    "20260527": {
        "version": 7
    }
}
TASK_HEADERS = {
    "User-Agent": TASK_UA,
    "Referer": "https://pan.baidu.com/operation/activitys/taskSystem/main",
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
}
# 内置 z 对应的设备（MuMu 抓包）。若用自己的 BAIDUWP_DEVICE，请同时提供
# 与之匹配的 BAIDUWP_Z；否则任务系统通道可能因 z/devuid 不匹配报 errno=2。
TASK_DEVICE_BUILTIN = "BBC8B8DCC4790CFD232CD628652EFDED|VUWSHHV6D"

# 任务中心设备标识：一次生成、长期复用，且不要同一天喂给多个账号。
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
# 2026-10 真机抓包复核（修正前两版结论）：
#   dex 里确实只有 /coins/taskcenter/signinlist 与 /coins/taskcenter/checkdevmp，
#   但**任务系统 H5**（/operation/activitys/taskSystem/main）的 JS 会动态拼出
#   /coins/taskcenter/signin 并在页面打开时自动签到 —— 所以只扫 dex 会漏掉它。
#   该 H5 请求携带完整客户端参数：
#       z / channel / cuid / devuid / version / versioncode / offlinepackage /
#       themeinfo / rchannel / task_id / task_from / is_growth=0
#   缺 z/channel/offlinepackage 时，未签到账号会得到 errno=2 param error
#   （已签日服务端短路返回，看不出缺参数）。
#   金币乐园（points-center）已下线，/coins/center/signin 的 8001 是活动下线的表现；
#   /coins/center/signinv2 只对旧版/灰度账号有意义。
#
# 设备字段仍然保留并冻结：①H5 每个请求都会带 getClientInfo 的 cuid/devuid；
# ②设备类风控码 9312/9302/9306 与 8001 仍按设备判定；③稳定设备能避免自造 dev repeat。
# 本文件把账号↔设备绑定关系与风控冷却时间戳都持久化到磁盘。
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

# 旧版 /coins/taskcenter/signin 的错误码（已确认该接口不在当前客户端代码里）。
# App 13.34.3 全量 42 个 dex 中只有 "/coins/taskcenter/signinlist" 与
# "/coins/taskcenter/checkdevmp"，不存在 "/coins/taskcenter/signin" 字面量。
# 因此这里的 errno=2/9230 不能解读成「设备未登记」—— 它们只是旧接口的
# 参数/任务契约已经失效（服务端不再为这个入口维护 task_id/task_from）。
TASKCENTER_ERRNO = {
    2: "任务系统通道参数校验失败（缺 z/channel/offlinepackage 等客户端参数，"
       "或客户端版本/渠道不匹配），与设备是否登记无关",
    9230: "任务系统通道通用错误（多为当日已签或活动状态异常）",
    9312: "设备重复：同一台设备正在服务其它账号，或处于服务端校验窗口",
}

# points-center H5（App 任务中心/积分中心实际加载的页面）错误码。
# 来源：points-center 前端风控映射表
#   w={noBinding:9306, phoneRepeat:9302, deviceRepeat:9312,
#      tokenCheckErr:35103, tokenNoAccord:35104, noLogin:-6}
#   f={HTJError:8001, CHEAT_CODE_FREQUENTLY:8011, CHEAT_CODE_FREQUENTLY_OTHER:8024}
CENTER_ERRNO = {
    -6: "BDUSS 无效或未登录",
    8001: "账号或设备异常（H5 鉴权前的风控门 HTJError）",
    8011: "作弊请求过于频繁（CHEAT_CODE_FREQUENTLY）",
    8024: "账号/设备被风控拦截（CHEAT_CODE_FREQUENTLY_OTHER）",
    9302: "手机号重复：同一手机号下多账号",
    9306: "账号未绑定手机号",
    9312: "设备重复：同一设备多账号",
    35100: "获取 AMIS 配置失败（新签到活动未对当前客户端开放/配置缺失，"
           "说明该账号不该走 signinv2）",
    35103: "token 校验失败",
    35104: "token 与账号不匹配",
}
CENTER_RISK_ERRNO = {8001, 8011, 8024}
DEVICE_RISK_ERRNO = {9302, 9306, 9312, 35103, 35104}

# 任务系统通道（/coins/taskcenter/*）错误码的短标签：只用于推送/注释，
# 详细解读走 _tc_advice()，避免把「param error」这种服务端原文直接甩给用户。
TC_ERRNO_SHORT = {
    2: "参数校验未通过",
    9230: "业务层拒绝",
    9312: "设备重复",
}

# 任务中心通道总开关。实测该通道的 z 不是可跨账号重放的参数（见 _tc_advice），
# 多数账号注定失败，只想看其它三项收益时可以关掉，省掉每条通道的请求。
TASKCENTER_ENABLED = os.getenv("BAIDUWP_TASKCENTER", "").strip().lower() not in (
    "0", "false", "off", "no")
# 网页端通道（clienttype=5 + MAWEBCUID，不带 sofire z）：会话本身就是网页端时
# 这条最便宜，且是唯一「不需要 z」的尝试。默认开，置 0 关闭。
TASKCENTER_WEB = os.getenv("BAIDUWP_TASKCENTER_WEB", "").strip().lower() not in (
    "0", "false", "off", "no")
# 官方 H5 getNewSignList() 固定参数：action=1（日常签到）+ ptype=5（会员积分中心）
CENTER_ACTION = "1"
CENTER_PTYPE = "5"


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
          "devices":  {"<device>": {"cooldown_until": 0, "is_new_device": null}},
          "zc":       {"uid": "<z 的来源账号 uid>", "z_fp": "<z 指纹前8位>"}
        }

    zc（z-owner）：内置 sofire z 只对「抓包时登录的那个账号」有效，这是实测结论
    （同一份 z/channel/offlinepackage，只有抓包账号能过参数校验，其余账号一律
    errno=2）。把它记下来，后续运行就不会让其它账号每天白撞一次。
    """

    def __init__(self, path: str):
        self.path = path
        self.data = {"version": 1, "accounts": {}, "devices": {},
                     "growth": {}, "zc": {}, "web": {}}
        self._run_shared_users = {}      # device -> account_key（仅本次进程运行期）
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self.data["accounts"] = raw.get("accounts") or {}
                self.data["devices"] = raw.get("devices") or {}
                self.data["growth"] = raw.get("growth") or {}
                self.data["zc"] = raw.get("zc") or {}
                self.data["web"] = raw.get("web") or {}
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

    def note_registration(self, device: str, status: str, detail: str = ""):
        """记录「首次登录设备上报」的结果。

        status: reported（checkdevmp 返回 errno=0，上报成功，服务端已收到该 devuid）
                param_error（errno=2：参数/风控层未过，设备信息根本没被受理）
                login_error（cookie 失效）
        注意：checkdevmp 是**单向上报**（CheckDeviceUniqueJob 是 BaseReportJob，
        返回值 App 不使用），所以只能确认「报上去了」，不能确认「已建档」。
        """
        item = self.data["devices"].setdefault(device, {})
        item["registration"] = {"status": status, "detail": detail,
                                "at": time.time()}
        self.save()

    def registration(self, device: str) -> dict:
        return (self.data["devices"].get(device) or {}).get("registration") or {}

    def clear_registration(self, device: str):
        item = self.data["devices"].get(device)
        if isinstance(item, dict):
            item.pop("registration", None)
            self.save()

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

    def set_z_owner(self, uid: str, z: str):
        """记住内置 z 的来源账号（首个通过参数校验的账号）。

        绑定 z 指纹：用户换了 BAIDUWP_Z 之后指纹变了，owner 结论自动作废重学，
        不会因为一条过期的登记把新 z 也当成「只属于某个老账号」。
        """
        if not uid:
            return
        self.data["zc"] = {
            "uid": str(uid),
            "z_fp": hashlib.md5(str(z).encode("utf-8")).hexdigest()[:8],
            "at": time.time(),
        }
        self.save()

    def set_web_verdict(self, account_key: str, cuid: str, status: str):
        """记住「网页端通道」的实测结论，避免每天拿同一套参数白撞。

        只记 errno=2 这种「该入口同样要 z」的结论；绑定 cuid 指纹，
        cookie 换代/换设备标识后自动失效。14 天后重试（法规/风控都会变）。
        """
        if not account_key or not cuid:
            return
        self.data.setdefault("web", {})[account_key] = {
            "cuid_fp": hashlib.md5(str(cuid).encode("utf-8")).hexdigest()[:8],
            "status": status,
            "at": time.time(),
        }
        self.save()

    def web_verdict(self, account_key: str, cuid: str) -> dict:
        item = (self.data.get("web") or {}).get(account_key) or {}
        if not item or not cuid:
            return {}
        if item.get("cuid_fp") != hashlib.md5(str(cuid).encode("utf-8")).hexdigest()[:8]:
            return {}
        if time.time() - float(item.get("at") or 0) > 14 * 86400:
            return {}
        return item

    def z_owner(self) -> dict:
        """返回 z 的归属记录；超过 14 天就当没学过（避免旧结论永久生效）。"""
        item = self.data.get("zc") or {}
        if not item.get("uid"):
            return {}
        if time.time() - float(item.get("at") or 0) > 14 * 86400:
            return {}
        return item

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
                "User-Agent": PROFILE_BROWSER_UA,
                "Referer": "https://pan.baidu.com/wap/svip/growth/task",
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        # 不要写死 Cookie 头：那样服务端下发的 Set-Cookie（BAIDUID/PANWEB/BDCLND…）
        # 永远发不回去，H5 的会话上下文就断了。
        self._load_cookies_into_jar(cookie)
        self._warmed = False
        self.registry = registry or DeviceRegistry(DEVICE_STATE_FILE)
        # 账号 uid 只用来做设备派生的稳定锚点，取不到则退化为 STOKEN/cookie 哈希
        self.uid = ""
        self.account_key = ""
        self.device = ""
        self._resolve_device_identity()
        # 补签通道（signinlist/supptasklist/suppsignin）与签到通道共用同一台设备，
        # 并统一带上任务系统 H5 的完整客户端参数（z/channel/offlinepackage…）。
        self.task_base = self._taskcenter_params(self.device)
        log(f"账号识别: uid={self.uid or '(未取到)'} account_key={self.account_key} "
            f"cookie=[BDUSS/STOKEN 已隐藏]", "INFO", self.log_tag)
        log(f"任务中心设备: {self.device}（来源: "
            f"{'环境变量指定' if self.device != self._legacy_device(self.cookie) else '登记表/老算法'}）",
            "INFO", self.log_tag)
        z_label, z_value = self._tc_z_source()
        # z 来源直接决定任务系统通道能不能成：内置值只属于抓包账号
        log(f"任务系统 z: 来源={z_label} 长度={len(z_value)}"
            + ("（非本账号专属：仅当本账号就是抓包账号时才会通过参数校验）"
               if z_label == "内置抓包值" else ""),
            "INFO", self.log_tag)

    def _load_cookies_into_jar(self, cookie: str):
        """把 cookie 串放进 requests 的 CookieJar（而不是写死 Cookie 头）。

        H5 页面加载时会从服务端拿到 BAIDUID / PANWEB 等 cookie，后续请求
        要能把它们带回去；写死 Cookie 头会让这些 Set-Cookie 永远失效。
        """
        jar = self.session.cookies
        for part in re.split(r"[;\n]+\s*", cookie):
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            name, value = name.strip(), value.strip()
            if not name:
                continue
            try:
                jar.set(name, value, domain=".baidu.com", path="/")
            except Exception:                # noqa: BLE001 单条坏 cookie 不阻塞
                pass

    def _warmup_session(self):
        """按 H5 页面加载顺序预热会话：首页 -> points 页 -> AMIS 配置。

        作用：拿到服务端下发的 BAIDUID/PANWEB 等 cookie，并建立活动配置上下文。
        旧的「写死 Cookie 头」实现拿不到这些 Set-Cookie，风控侧看到的会话不完整。
        """
        if getattr(self, "_warmed", False):
            return
        self._warmed = True
        session = getattr(self, "session", None)
        if session is not None:
            for url in ("https://pan.baidu.com/",
                        "https://pan.baidu.com/operation/activitys/points/main"):
                try:
                    resp = session.get(url, timeout=TIMEOUT, stream=True,
                                       headers=CENTER_HEADERS)
                    resp.close()
                except requests.RequestException as e:
                    log(f"  预热 {url} 失败: {e.__class__.__name__}: {e}",
                        "DEBUG", self.log_tag)
            log_debug(f"  会话 cookie: {sorted(session.cookies.keys())}",
                      self.log_tag)
        try:
            conf = self._pc_api("/act/api/conf", {"conf_key": "pointCenterBase2"})
            log_debug(f"  AMIS 配置预热 -> errno={conf.get('errno')}", self.log_tag)
        except (RuntimeError, requests.RequestException) as e:
            log(f"  AMIS 配置预热失败: {e.__class__.__name__}: {e}",
                "DEBUG", self.log_tag)

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

    @staticmethod
    def _new_device() -> str:
        """生成一台「形态合法」的新设备号：32 位大写 HEX | 8 位大写字母数字。

        形态对齐 App（DeviceId.getCUID 的产物，如
        `BBC8B8DCC4790CFD232CD628652EFDED|VUWSHHV6D`）。服务端不校验其内容
        （审计报告 §3.2），但它必须**长期稳定**：每次运行都换就等于每天一台新设备，
        会撞账号的设备上限（/netdisk/device_over_limit）。

        用随机而不是 md5(账号)：派生值可预测且所有账号同构，没必要留这个指纹。
        """
        head = "".join(random.choice("0123456789ABCDEF") for _ in range(32))
        tail = "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789")
                       for _ in range(8))
        return f"{head}|{tail}"

    def _resolve_device_identity(self):
        self.uid = self.get_uid()
        self.account_key = self._account_key()
        if os.getenv("BAIDUWP_DEVICE_RESET", "").strip() in ("1", "true", "True"):
            self.registry.data["accounts"].pop(self.account_key, None)
            self.registry.data["zc"] = {}          # 连同「z 属于哪个账号」一起重学
            self.registry.save()
        override = (os.getenv(f"BAIDUWP_DEVICE_{self.index}", "").strip()
                    or os.getenv("BAIDUWP_DEVICE", "").strip())
        if override and not _is_valid_device(override):
            print(f"  BAIDUWP_DEVICE 形态异常已忽略: {override[:24]}...", flush=True)
            override = ""
        rotate = os.getenv("BAIDUWP_DEVICE_ROTATE", "").strip() in ("1", "true", "True")
        if override:
            # 显式指定时不动登记表里原有的绑定，去掉环境变量即可恢复
            self.device = override
        elif rotate and not override:
            # 设备轮换：换一台全新的（账号设备上限有限，所以这是一次性动作，不是每天跑）
            self.device = self._new_device()
            self.registry.bind(self.account_key, self.device)
            self.registry.clear_registration(self.device)
            log(f"设备轮换: 本账号换用新设备 {self.device}（旧的就此作废）",
                "WARN", self.log_tag)
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

    @staticmethod
    def _redact(params: dict) -> dict:
        """日志脱敏：z 是 sofire 设备指纹令牌，BDUSS/STOKEN 是凭据。

        DEBUG 日志会把整个参数串打出来，z 一旦落盘/进日志就等于把设备指纹
        送出去了（它 87 字符，能把 200 字的摘要全部占满，顺便把其它参数挤掉）。
        """
        out = dict(params or {})
        for key in ("z", "BDUSS", "STOKEN", "bduss", "stoken"):
            if out.get(key):
                out[key] = _mask_credential(out[key], keep=6)
        return out

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
        log_debug(f"GET {path} params={brief(self._redact(params))} -> "
                  f"{brief(data, 160)} ({cost:.2f}s)", self.log_tag)
        return data

    def _api_get(self, path: str, extra_params: dict, headers: dict = None) -> dict:
        params = dict(QUERY_PARAMS)
        params.update(extra_params)
        return self._http_get(path, params, headers)

    def _pc_api(self, path: str, params: dict, headers: dict = None) -> dict:
        if headers is None:
            if path.startswith("/coins/taskcenter/"):
                # 任务系统 H5（taskSystem/main）的 UA/Referer 与 points-center 不同
                headers = TASK_HEADERS
            elif path.startswith("/coins/center/"):
                # points-center H5 通道用移动端 UA + 页面 Referer
                headers = CENTER_HEADERS
            else:
                headers = PC_HEADERS
        return self._http_get(path, params, headers)

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
        # 签到前读到的余额是旧值，回读一次才能反映本次奖励（否则会少报 +6 之类的增量）
        balance = inner.get("points_balance")
        try:
            fresh = self._pc_api("/coins/pc/signinlist",
                                 {"clienttype": "8", "win64": "1", "vip": "2"})
            if fresh.get("errno") == 0:
                balance = (fresh.get("data") or {}).get("points_balance", balance)
        except (RuntimeError, requests.RequestException):
            pass
        return f"积分签到成功，当前积分余额 {balance}"

    # ---------- 4. 任务中心辅助：设备链 / 旧通道 ----------
    def _web_cuid_info(self) -> tuple:
        """取网页端设备标识：返回 (来源, 值)。两者都是**服务端下发的**。

          MAWEBCUID  网页端 CUID（web_xxx），最贴近网页会话；
          BAIDUID    浏览器身份，预热 pan.baidu.com 时由 Set-Cookie 下发
                     （形如 `XXXX:FG=1`，取 `:` 前的部分）。

        青龙里通常只填 `BDUSS`/`STOKEN`，所以只认粘贴串会永远拿不到 ——
        先看粘贴串，再看会话 Jar（_warmup_session 之后就有 BAIDUID 了）。
        两个都没有返回 ("", "")。
        """
        m = re.search(r"MAWEBCUID=([^;,\s]+)", self.cookie)
        if m:
            return "MAWEBCUID", m.group(1)
        jar = getattr(self, "session", None)
        if jar is not None:
            try:
                values = {c.name: c.value for c in jar.cookies if c.value}
            except Exception:            # noqa: BLE001 取不到就当没有
                values = {}
            if values.get("MAWEBCUID"):
                return "MAWEBCUID", values["MAWEBCUID"]
            if values.get("BAIDUID"):
                # BAIDUID 的完整形态是 `<hash>:FG=1`，设备标识只取冒号前那段
                return "BAIDUID", str(values["BAIDUID"]).split(":")[0]
        return "", ""

    def _web_cuid(self) -> str:
        return self._web_cuid_info()[1]

    def _taskcenter_signin_web(self, web_cuid: str = "") -> dict:
        """走网页端通道签一次：clienttype=5(wap) + 网页 CUID，不带安卓伪装。

        动机：脚本的会话本来就是网页端拿的（PANWEB=1 / BDCLND / MAWEBCUID），
        而任务中心请求一直用 clienttype=1&app=android&channel=android_* 伪装 App，
        同时还得携带需要真机的 sofire z。会话类型与客户端声明不一致，
        是这条链路一直只能靠 z 硬碰的原因。

        这里是**唯一不需要 z 的尝试**：设备用服务端自己下发的 MAWEBCUID，
        参数只用网页端会带的 task_id/task_from/is_growth，成本一次请求。
        走 _pc_api（与其它任务中心请求同一出口），便于离线测试统一桩。
        """
        web_cuid = web_cuid or self._web_cuid()
        params = {
            "clienttype": "5",                  # wap/H5，与会话来源一致
            "cuid": web_cuid, "devuid": web_cuid,
            "task_id": "1666916321758720", "task_id_str": "1666916321758720",
            "task_from": "task_sys_daily", "is_growth": "0",
        }
        return self._pc_api("/coins/taskcenter/signin", params)

    def _taskcenter_today_signed(self):
        """读任务系统签到日历，判断今天是否已签。True/False/None(取不到)。

        任务系统 H5 的 /coins/taskcenter/signinlist 返回 signed_today /
        signin_days / day / signin_list，是当前签到状态的权威来源。
        """
        params = self._taskcenter_params(self.device)
        params.update({
            "task_id": "1666916321758720", "task_id_str": "1666916321758720",
            "task_from": "task_sys_daily", "is_growth": "0",
        })
        try:
            cal = self._pc_api("/coins/taskcenter/signinlist", params)
        except (RuntimeError, requests.RequestException):
            return None
        if cal.get("errno") != 0:
            return None
        inner = cal.get("data") or {}
        # 任务系统日历的权威字段
        if inner.get("signed_today") is not None:
            return bool(inner.get("signed_today"))
        if inner.get("signed") is not None:
            return bool(inner.get("signed"))
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
        channel = self._task_channel()
        params = {
            "cuid": device, "devuid": device,
            "time": str(ts),
            "rand": str(random.randint(100000, 999999)),
            "channel": channel,
        }
        if self.uid:
            params["rchannel"] = hashlib.md5(
                f"{APP_CLIENT_AK}{self.uid}{ts}{channel}".encode("utf-8")
            ).hexdigest()
        return params

    def _tc_z_source(self) -> tuple:
        """返回 (来源标签, z)。标签用来判断这份 z 是不是「本账号自己的」。"""
        own = os.getenv(f"BAIDUWP_Z_{self.index}", "").strip()
        if own:
            return f"BAIDUWP_Z_{self.index}", own
        shared = os.getenv("BAIDUWP_Z", "").strip()
        if shared:
            return "BAIDUWP_Z", shared
        return "内置抓包值", SOFIRE_Z

    def _task_z(self) -> str:
        """按账号取 sofire z：BAIDUWP_Z_n > BAIDUWP_Z > 内置抓包值。"""
        return self._tc_z_source()[1]

    def _task_channel(self) -> str:
        """按账号取 channel：BAIDUWP_CHANNEL_n > BAIDUWP_CHANNEL > 内置抓包值。"""
        return (os.getenv(f"BAIDUWP_CHANNEL_{self.index}", "").strip()
                or os.getenv("BAIDUWP_CHANNEL", "").strip() or TASK_CHANNEL)

    def _taskcenter_params(self, device: str) -> dict:
        """任务系统 H5（taskSystem/main）的完整客户端参数（App 13.34.3 抓包）。"""
        ts = int(time.time())
        channel = self._task_channel()
        return {
            "z": self._task_z(),
            "clienttype": "1",
            "channel": channel,
            "cuid": device,
            "devuid": device,
            "version": TASK_BASE["version"],
            "versioncode": TASK_BASE["versioncode"],
            "offlinepackage": json.dumps(TASK_OFFLINE_PACKAGE,
                                         separators=(",", ":")),
            "themeinfo": "0",
            "app": "android",
            "rchannel": hashlib.md5(
                f"{APP_CLIENT_AK}{self.uid or '0'}{ts}{channel}".encode("utf-8")
            ).hexdigest(),
        }

    def _taskcenter_signin_once(self, device: str, extra: dict = None) -> dict:
        """任务系统 H5 当前通道：GET /coins/taskcenter/signin（全量客户端参数）。"""
        params = self._taskcenter_params(device)
        if extra:
            params.update(extra)
        params.update({
            "task_id": "1666916321758720", "task_id_str": "1666916321758720",
            "task_from": "task_sys_daily", "is_growth": "0",
        })
        return self._pc_api("/coins/taskcenter/signin", params)

    def _taskcenter_checkdev(self, device: str) -> dict:
        """App 的 PointCenterApi.checkDeviceUnique()：GET /coins/taskcenter/checkdevmp。

        用来确认「本账号下这台设备是不是新设备（即没有登记记录）」：
        errno == 0 -> 服务端认为该设备是新的（未登记）。
        这一步同时把设备信息上报给任务中心，等价于 App 打开任务中心首页时做的事。
        """
        return self._pc_api("/coins/taskcenter/checkdevmp",
                            self._taskcenter_params(device))

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

    def ensure_device_registered(self) -> str:
        """首次登录时把本账号设备上报到云端（设备登记），每账号只做一次。

        逆向依据（App 13.34.3，见审计报告 §十三）：
          * 设备号是**客户端生成**的：CUID3StartupTask.run()
              AppCommon.DEVUID = PersonalConfig["deviceId"]
                              ?: DeviceId.getCUID(context)   # 首次启动生成并落盘
            服务端没有「下发设备号」的接口，所以「新设备」只需一个新 devuid。
          * App 里唯一把设备报给任务中心的入口：
              PointCenterApi.checkDeviceUnique()
                -> GET /coins/taskcenter/checkdevmp
            它在 CheckDeviceUniqueJob（BaseReportJob）里跑，属后台上报，
            响应 data 是字符串且 App 不解析 —— 即「只报不看」。
          * 设备维度有上限与解绑（/netdisk/device_over_limit、/api/device/setmain、
            /device/unbind），所以换设备是一次性动作，不能每次运行都换。

        所以：“注册”= 本地生成一台新设备后，带全量客户端参数上报一次。
        是否被受理只能看 errno：0 = 服务端收到；2 = 参数/风控层就没过
        （z 不属本账号时必然如此），那个结果会落盘，下次运行自动重试。
        """
        state = self.registry.registration(self.device)
        if state.get("status") == "reported":
            stamp = time.strftime("%Y-%m-%d %H:%M",
                                  time.localtime(float(state.get("at") or 0)))
            log(f"  设备登记: 本账号设备已在 {stamp} 上报过，跳过",
                "DEBUG", self.log_tag)
            return ""

        self._warmup_session()
        try:
            resp = self._taskcenter_checkdev(self.device)
        except (RuntimeError, requests.RequestException) as e:
            log(f"  设备登记: 上报请求失败 {e.__class__.__name__}: {e}",
                "WARN", self.log_tag)
            return ""
        errno = resp.get("errno")
        msg = str(resp.get("error") or resp.get("errmsg") or "")
        log(f"  设备登记: checkdevmp -> errno={errno} error={msg or '无'} "
            f"data={brief(resp.get('data'), 80)}", "INFO", self.log_tag)

        if errno == 0:
            self.registry.note_registration(self.device, "reported")
            # 注意：checkdevmp 只回报 errno，不区分「新设备」还是「已在册」，
            # 所以这里只说“已上报”，不说“已建档/新设备”（避免过度断言）。
            log(f"  设备登记: 完成。设备 {self.device} 已上报（checkdevmp errno=0）；"
                f"之后一直用它，不再每天换", "INFO", self.log_tag)
            return f"设备登记: 首次登录已上报设备（…{self.device[-8:]}）"
        if errno == -6 or self._is_login_error(msg):
            self.registry.note_registration(self.device, "login_error", msg)
            log("  设备登记: cookie 失效，无法上报（需含 STOKEN 的完整 cookie）",
                "ERR", self.log_tag)
            return ""
        self.registry.note_registration(self.device, "param_error", msg or str(errno))
        log("  设备登记: 参数/风控层未通过，本次没报上去（与服务端是否认识该设备无关）；"
            f"配好本账号专属的 BAIDUWP_Z_{self.index} 后会自动重试",
            "WARN", self.log_tag)
        return ""

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
        """在指定设备上尝试签到；仅 dev repeat 做退避重试。返回 (data, error)。

        退避只在「确实还有下一次尝试」时才睡。上一版即使 tries=1 也会在
        最后一次失败后 sleep 15s，实测三账号白等了 45s，日志还会打出
        「15s 后重试(1/1)」这种与事实不符的行。
        """
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
            if attempt + 1 >= tries:
                break                    # 最后一次不必再睡：没有下一次了
            wait = 15 * (attempt + 1)
            log(f"    设备重复触发风控(dev repeat)，{wait}s 后重试"
                f"({attempt + 1}/{max(1, tries - 1)})...", "WARN", self.log_tag)
            time.sleep(wait)
        return data, error

    @staticmethod
    def _tc_success(data: dict) -> str:
        """任务系统签到成功后的归一化结果行。"""
        inner = (data.get("data") if isinstance(data, dict) else None) or {}
        days = inner.get("signin_days")
        suffix = f"，已连续签到 {days} 天" if days else ""
        if inner.get("signed") == 1:
            return f"任务中心签到: 今日已签到{suffix}"
        return f"任务中心签到: 完成{suffix}"

    def _tc_advice(self, errno, error: str) -> str:
        """把任务系统通道的错误码翻译成「下一步该做什么」——只进日志，不进推送。"""
        if errno == 2:
            if self._tc_z_source()[0] == f"BAIDUWP_Z_{self.index}":
                return ("errno=2 是鉴权之前的参数校验，与「设备未登记」无关。"
                        "本账号已配置专属 z，说明 z 与设备/channel 不配套："
                        "z 必须来自同一台设备（devuid 与抓包的 devuid 一致），"
                        "或同时用 BAIDUWP_DEVICE_n 指定那台设备")
            return ("errno=2 是鉴权之前的参数校验，与「设备未登记」无关。"
                    "实测同一份 z/channel/offlinepackage，只有抓包账号能过校验，"
                    "其余账号一律拿 2 —— z 是 sofire 按「设备+登录态」算出的指纹，"
                    "不是可跨账号重放的静态参数。要让本账号走通，只能给它自己的："
                    "在该账号登录的 App 上跑 work/frida/get_clientinfo.py 取 "
                    "FH.gz(context)，写入 BAIDUWP_Z_%d（建议连 BAIDUWP_CHANNEL_%d 一起）"
                    % (self.index, self.index))
        if errno == 9230:
            return ("errno=9230 是任务系统业务层拒绝。抓包账号用它自己的 z 也会拿到，"
                    "且日历显示今日未签，所以不是「重复签到」——是服务端对该账号的"
                    "活动/任务状态另有判定，客户端侧没有可补的参数")
        if errno == 9312:
            return ("errno=9312 设备重复：这台设备正在服务其它账号，"
                    "或处于服务端校验窗口（已写冷却，不会连续重撞）")
        return f"errno={errno} error={error or '无'}（未收录的错误码，已保留原始响应）"

    # ---------- 4. 任务中心签到（官方 H5 通道） ----------
    def _center_api(self, path: str, params: dict, device: str = "") -> dict:
        """points-center H5 通道：按官方 getClientInfo 带上设备字段。

        H5 页面在 App WebView 里会给每个请求补 clienttype=1 + cuid/devuid
        （module 23477: d = await bridge.invoke("getClientInfo")）。
        """
        p = {"clienttype": "1", "cuid": device or self.device,
             "devuid": device or self.device}
        p.update(params or {})
        return self._pc_api(path, p)

    @staticmethod
    def _parse_sign_calendar(payload: dict) -> dict:
        """解析「今天签没签 / 连续天数」，兼容三种官方响应形状。

          A) H5 signininfo:   data.signin_state.SignedToday
          B) 原生 App:        data.today_signined / data.con_signin_cnt
          C) taskcenter 日历: data.start_time + data.date + signin_list[].day/signed
        """
        inner = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(inner, dict):
            return {"signed": None, "days": None, "version": None}
        state = inner.get("signin_state")
        state = state if isinstance(state, dict) else {}
        signed = None
        # "signed" 是 /coins/center/home 的字段（H5 就是用它决定 signToday）
        for key in ("SignedToday", "signed_today", "today_signined",
                    "todaySignined", "is_signin", "signed"):
            if key in state:
                signed = bool(state.get(key))
                break
            if key in inner:
                signed = bool(inner.get(key))
                break
        days = None
        for key in ("signin_days", "con_signin_cnt", "signin_cnt",
                    "signinCount", "continuous_days"):
            val = inner.get(key)
            if isinstance(val, bool):
                continue
            if isinstance(val, int) or (isinstance(val, str) and val.isdigit()):
                days = int(val)
                break
        start, now = inner.get("start_time"), inner.get("date")
        items = inner.get("signin_list") or inner.get("list") or []
        if isinstance(items, list) and start and now:
            try:
                today = (int(now) - int(start)) // 86400 + 1
            except (TypeError, ValueError):
                today = None
            if today:
                if signed is None:
                    for item in items:
                        if isinstance(item, dict) and item.get("day") == today:
                            signed = bool(item.get("signed") or item.get("is_signin"))
                            break
                if days is None:
                    days = sum(1 for it in items if isinstance(it, dict)
                               and (it.get("signed") or it.get("is_signin")))
        version = None
        for key in ("signin_version", "signinVersion", "sign_version"):
            val = inner.get(key)
            if isinstance(val, bool):
                continue
            if isinstance(val, int) or (isinstance(val, str) and val.lstrip("-").isdigit()):
                version = int(val)
                break
        return {"signed": signed, "days": days, "version": version}

    def _center_sign_state(self, device: str = "") -> dict:
        """读签到状态，顺序对齐客户端（signininfo -> signinlist -> 原生日历）。

        返回 {"signed": True/False/None, "days": int|None, "source": str,
              "invalid": bool}；invalid 表示 cookie 失效（取不到结论）。
        """
        probes = (
            # H5 的权威状态源：getHomeInfo() 用 data.signed 决定 signToday，
            # 用 data.signin_version 决定走新签到(signinv2)还是旧签到(center/signin)
            ("H5 home", "/coins/center/home", {"ptype": CENTER_PTYPE}),
            ("H5 signininfo", "/coins/center/signininfo",
             {"action": CENTER_ACTION, "ptype": CENTER_PTYPE}),
            ("H5 signinlist", "/coins/center/signinlist",
             {"action": CENTER_ACTION, "ptype": CENTER_PTYPE}),
            ("App signinlist", "/coins/taskcenter/signinlist",
             {"ptype": CENTER_PTYPE}),
        )
        invalid = False
        version = None
        for name, path, params in probes:
            try:
                data = self._center_api(path, params, device)
            except (RuntimeError, requests.RequestException) as e:
                log(f"  签到状态({name}) 读取失败: {e.__class__.__name__}: {e}",
                    "WARN", self.log_tag)
                continue
            errno = data.get("errno")
            error = str(data.get("error") or data.get("errmsg") or "")
            if errno != 0:
                if errno == -6 or self._is_login_error(error):
                    invalid = True
                log(f"  签到状态({name}) -> errno={errno} error={error or '无'}",
                    "INFO", self.log_tag)
                continue
            info = self._parse_sign_calendar(data)
            info["source"] = name
            # 能拿到 200+errno=0 就说明会话有效，不因前一个探针的 -6 误判为失效
            info["invalid"] = False
            if info["version"] is not None:
                version = info["version"]
            log(f"  签到状态({name}) -> today_signed={info['signed']} "
                f"连续天数={info['days']} 签到版本={info['version']}",
                "INFO", self.log_tag)
            if info["signed"] is not None or info["days"] is not None:
                if info["version"] is None:
                    info["version"] = version
                return info
        return {"signed": None, "days": None, "version": version,
                "source": "未取到", "invalid": invalid}

    def _dump_center_home(self, label: str):
        """失败时把 /coins/center/home 的关键字段与全文打进日志/落盘。

        H5 的 signToday 与 signin_version 都来自这个接口：它是判断「今天该不该签、
        该走 signinv2 还是 center/signin」的权威来源。
        """
        try:
            home = self._center_api("/coins/center/home", {"ptype": CENTER_PTYPE})
        except (RuntimeError, requests.RequestException) as e:
            log(f"  center/home 读取失败: {e.__class__.__name__}: {e}",
                "WARN", self.log_tag)
            return
        if home.get("errno") != 0:
            log(f"  center/home errno={home.get('errno')} "
                f"error={home.get('error') or home.get('errmsg')}",
                "WARN", self.log_tag)
            return
        inner = home.get("data") or {}
        keys = ("signed", "signin_version", "signin_days", "signin_double_award",
                "received_sign_reward", "next_sign_reward_days", "new_player",
                "is_newbie", "points_balance", "inactive", "can_reissue")
        summary = {k: inner.get(k) for k in keys if k in inner}
        log(f"  center/home 关键字段({label}): {brief(summary, 320)}",
            "INFO", self.log_tag)
        path = dump_json(home, "center_home_dump.json")
        if path:
            log(f"  center/home 全文已落盘: {path}", "INFO", self.log_tag)

    @staticmethod
    def _is_login_error(text) -> bool:
        raw = str(text or "")
        low = raw.lower()
        return "bduss" in low or "login" in low or "登录" in raw

    def _center_sign_once(self, device: str, path: str = "/coins/center/signinv2") -> dict:
        """按官方 H5 getNewSignList() 的参数签一次（action=1 / ptype=5）。"""
        params = {
            "action": CENTER_ACTION, "ptype": CENTER_PTYPE,
            "app": TASK_BASE["app"], "version": TASK_BASE["version"],
            "versioncode": TASK_BASE["versioncode"],
        }
        return self._center_api(path, params, device)

    def _center_sign_call(self, device: str, path: str = "/coins/center/signinv2") -> dict:
        try:
            return self._center_sign_once(device, path)
        except (RuntimeError, requests.RequestException) as e:
            return {"errno": -1, "error": f"{e.__class__.__name__}: {e}"}

    def _finish_center_sign(self, data: dict, device: str = "") -> str:
        """签到成功后回读日历补连续天数（客户端 getNewSignList 的第二步）。

        device：真正签到成功的设备（账号自有或备用池）；只清除这台设备的冷却，
        避免把刚刚因风控被隔离的账号自有设备“洗白”而下次白撞。
        """
        device = device or self.device
        days = None
        # 客户端 getNewSignList() 的第二步：签完回读 /coins/center/signinlist
        try:
            cal = self._center_api("/coins/center/signinlist",
                                   {"action": CENTER_ACTION, "ptype": CENTER_PTYPE},
                                   device)
            if cal.get("errno") == 0:
                days = self._parse_sign_calendar(cal).get("days")
        except (RuntimeError, requests.RequestException):
            pass
        inner = data.get("data") if isinstance(data, dict) else None
        if days is None and isinstance(inner, dict):
            for key in ("signin_days", "con_signin_cnt", "signin_cnt"):
                if isinstance(inner.get(key), int):
                    days = inner[key]
                    break
        self.registry.set_cooldown(device, 0, self.account_key)
        suffix = f"，已连续签到 {days} 天" if days else ""
        return f"任务中心签到: 完成{suffix}"

    def _center_sign_device_retry(self) -> tuple:
        """设备类风控时换一台备用已登记设备再试一次 signinv2。

        返回 (data, device, notes)；成功时保持该设备在本轮运行中的独占
        （acquire_shared 不释放），避免同一轮的其它账号又撞上去。
        """
        notes = []
        for label, device in self._device_candidates()[1:]:
            if self.registry.in_cooldown(device):
                left = self.registry.cooldown_left(device)
                notes.append(f"{label}(风控冷却中，约{max(1, left // 3600)}h后解除)")
                continue
            if not self.registry.acquire_shared(device, self.account_key):
                notes.append(f"{label}(本次运行已被其它账号占用)")
                continue
            log(f"  换用{label}: {device}", "INFO", self.log_tag)
            data = self._center_sign_call(device)
            errno = data.get("errno")
            error = str(data.get("error") or data.get("errmsg") or "")
            log(f"  {label} signinv2 -> errno={errno} error={error or '无'}",
                "INFO", self.log_tag)
            if errno == 0:
                return data, device, notes
            self.registry.release_shared(device)
            notes.append(f"{label}({CENTER_ERRNO.get(errno, error or errno)})")
            if errno in DEVICE_RISK_ERRNO:
                continue
            break
        return None, "", notes

    def taskcenter_signin(self) -> str:
        """任务中心（任务系统）签到：按「成本从低到高」逐条通道尝试。

        逆向依据（App 13.34.3 真机抓包，2026-10）：
          * 任务系统 H5（/operation/activitys/taskSystem/main）打开即自动签到，
            调用 GET /coins/taskcenter/signin，带全量客户端参数
            （z/channel/cuid/devuid/version/versioncode/offlinepackage/themeinfo/
             rchannel/task_id/task_from/is_growth=0）。
          * z 是 sofire 反欺诈指纹（com.baidu.sofire.ac.FH.gz），由本机按
            「设备 + 登录态」算出。实测同一份 z 只有抓包账号能过参数校验，
            其余账号一律 errno=2 —— 它不是可跨账号重放的静态参数，这条通道
            天然只对 z 的来源账号有效。
          * 任务系统日历 /coins/taskcenter/signinlist 的 signed_today 是状态权威源。
          * points-center（signinv2/center/signin）仅作旧账号回退。

        通道顺序（每条都便宜，且互不依赖）：
          0) 熔断：已签 / 通道关闭 / 内置 z 已知属他账号 -> 不发请求直接判
          1) 网页端 clienttype=5 + MAWEBCUID（唯一不需要 z 的尝试，1 次请求）
          2) 任务系统 App 通道（z + 全量参数）
          3) 内置设备配对重试（冷却/占用中则跳过，不再空转 15s）
          4) points-center -> 旧 H5 signin -> 旧原生（需显式开启）
        """
        if not TASKCENTER_ENABLED:
            log("任务中心签到: 已关闭（BAIDUWP_TASKCENTER=0），跳过全部通道",
                "INFO", self.log_tag)
            return "任务中心签到: 已关闭（BAIDUWP_TASKCENTER=0）"

        self._warmup_session()

        # 状态权威源：任务系统日历
        tc_signed = self._taskcenter_today_signed()
        log(f"任务系统签到日历: today_signed={tc_signed}", "INFO", self.log_tag)
        if tc_signed is True:
            return "任务中心签到: 今日已签到"

        notes = []
        last_errno, last_error = None, ""
        z_label, z_value = self._tc_z_source()
        z_fp = hashlib.md5(z_value.encode("utf-8")).hexdigest()[:8]
        owner = self.registry.z_owner()
        owner_uid = str(owner.get("uid") or "")
        # 内置/全局 z 已被实测证明属于某个账号时，其它账号不再每天白撞一次：
        # z 指纹一变（用户换了 BAIDUWP_Z）就自动作废重学。
        z_foreign = bool(z_label != f"BAIDUWP_Z_{self.index}" and owner_uid
                         and owner.get("z_fp") == z_fp
                         and self.uid and owner_uid != self.uid)

        if z_foreign:
            log(f"  任务系统通道: 内置 z 属于 uid={owner_uid}（此前运行通过过参数校验），"
                f"本账号 uid={self.uid} 未配置 BAIDUWP_Z_{self.index} -> 跳过该通道",
                "WARN", self.log_tag)
            notes.append(f"任务系统通道(z 属账号 {owner_uid}，未配 BAIDUWP_Z_{self.index})")
        else:
            # 1) 网页端通道：会话本身就是网页端，且不需要 sofire z
            cuid_kind, web_cuid = self._web_cuid_info()
            seen = self.registry.web_verdict(self.account_key, web_cuid)
            if TASKCENTER_WEB and web_cuid and seen.get("status") != "param_error":
                log(f"  网页端通道: 设备标识用服务端下发的 {cuid_kind}"
                    f"（{_mask_credential(web_cuid, 6)}）", "DEBUG", self.log_tag)
                try:
                    web = self._taskcenter_signin_web(web_cuid)
                except (RuntimeError, requests.RequestException) as e:
                    web = {"errno": -1, "error": f"{e.__class__.__name__}: {e}"}
                w_errno = web.get("errno")
                w_msg = str(web.get("error") or web.get("errmsg") or "")
                log(f"  网页端通道(clienttype=5 + {cuid_kind}，无 z) -> errno={w_errno} "
                    f"error={w_msg or '无'}", "INFO", self.log_tag)
                if w_errno == 0:
                    return self._tc_success(web)
                if w_errno == -6 or self._is_login_error(w_msg):
                    return "任务中心签到: 失败（完整 cookie 已失效，需含 STOKEN）"
                if w_errno == 2:
                    # 该入口也走 z 校验：记下来，14 天内不再用同一套参数白撞
                    self.registry.set_web_verdict(self.account_key, web_cuid, "param_error")
                    notes.append("网页端通道(参数校验未通过，说明该入口也要 z)")
                else:
                    notes.append(
                        f"网页端通道({TC_ERRNO_SHORT.get(w_errno, w_msg or w_errno)})")
            elif seen.get("status") == "param_error":
                log("  网页端通道: 此前实测 errno=2（该入口同样要 z），跳过"
                    "（14 天后或换设备标识会自动重试）", "INFO", self.log_tag)
            else:
                log("  cookie/Jar 里没有 MAWEBCUID 或 BAIDUID"
                    "（或网页端通道被 BAIDUWP_TASKCENTER_WEB=0 关闭），跳过网页端通道",
                    "INFO", self.log_tag)

            # 2) 任务系统 App 通道（真机链路，带 z）
            tc_data, tc_error = self._taskcenter_signin_device(self.device, tries=1)
            tc_errno = tc_data.get("errno")
            tc_msg = str(tc_data.get("error") or "")
            log(f"  任务系统通道 signin -> errno={tc_errno} error={tc_msg or '无'}",
                "INFO", self.log_tag)
            if tc_errno == 0:
                return self._tc_success(tc_data)
            if tc_errno == -6 or self._is_login_error(tc_msg):
                return "任务中心签到: 失败（完整 cookie 已失效，需含 STOKEN）"

            if "dev repeat" in tc_msg or tc_errno == 9312:
                # 现代路径原先不写冷却，导致同轮下一个账号拿同一台设备再撞一次
                self.registry.set_cooldown(self.device, DEV_REPEAT_COOLDOWN,
                                           self.account_key)
                log(f"  设备已写 {max(1, DEV_REPEAT_COOLDOWN // 3600)}h 冷却，"
                    "后续运行不再重撞", "WARN", self.log_tag)
            elif tc_errno == 9230 and z_label != f"BAIDUWP_Z_{self.index}":
                # 过了参数校验 = 这份 z 属于本账号，记下来给其它账号做熔断
                self.registry.set_z_owner(self.uid, z_value)

            notes.append(f"任务系统通道({TC_ERRNO_SHORT.get(tc_errno, tc_msg or tc_errno)})")
            log(f"  错误码解读: {self._tc_advice(tc_errno, tc_msg)}",
                "INFO" if tc_errno == 2 else "WARN", self.log_tag)

            # 3) 内置设备配对重试：只对「内置 z 的来源账号」有意义，
            #    并且必须先过冷却/占用两道门，否则必滞 dev repeat。
            if (tc_errno in (2, 9230) and self.device != TASK_DEVICE_BUILTIN
                    and z_label == "内置抓包值"):
                builtin = TASK_DEVICE_BUILTIN
                if self.registry.in_cooldown(builtin):
                    left = self.registry.cooldown_left(builtin)
                    log(f"  内置设备处于风控冷却（约 {max(1, left // 3600)}h 后解除），"
                        "跳过配对重试", "WARN", self.log_tag)
                    notes.append("内置设备(风控冷却中)")
                elif not self.registry.acquire_shared(builtin, self.account_key):
                    log("  内置设备本次运行已被其它账号占用，跳过配对重试",
                        "WARN", self.log_tag)
                    notes.append("内置设备(本次运行已被其它账号占用)")
                else:
                    log(f"  内置 z 配对设备重试: {builtin}", "WARN", self.log_tag)
                    retry, _retry_err = self._taskcenter_signin_device(builtin, tries=1)
                    r_errno = retry.get("errno")
                    r_msg = str(retry.get("error") or "")
                    log(f"  任务系统通道(内置设备) -> errno={r_errno} "
                        f"error={r_msg or '无'}", "INFO", self.log_tag)
                    if r_errno == 0:
                        # 保持本轮独占，避免同轮其它账号又撞上去
                        return self._tc_success(retry)
                    if "dev repeat" in r_msg or r_errno == 9312:
                        self.registry.set_cooldown(builtin, DEV_REPEAT_COOLDOWN,
                                                   self.account_key)
                    else:
                        self.registry.release_shared(builtin)
                    notes.append(
                        f"内置设备({TC_ERRNO_SHORT.get(r_errno, r_msg or r_errno)})")

        # 4) 回退：points-center 通道（旧版/灰度账号仍可能走这里）
        state = self._center_sign_state()
        if state.get("invalid"):
            log("任务中心签到失败: 服务端返回 bduss 错误，cookie 缺少有效 STOKEN",
                "ERR", self.log_tag)
            return "任务中心签到: 失败（完整 cookie 已失效，需含 STOKEN）"
        if state.get("signed") is True:
            days = state.get("days")
            suffix = f"，已连续签到 {days} 天" if days else ""
            return f"任务中心签到: 今日已签到{suffix}"

        version = state.get("version")
        version_name = {0: "旧版", 1: "灰度(CAN_BE_NEW)", 2: "新版"}.get(version, "未知")
        log(f"  签到版本 signin_version={version}（{version_name}）", "INFO", self.log_tag)

        # H5 的 handleAbtest(): isCanUseNewSign ? initNewSigninlist(signinv2)
        #                                   : handleAutoSign(/coins/center/signin)
        # 旧版/灰度账号根本不走 signinv2，硬打只会拿到 35100「获取amis配置失败」。
        if version in (0, 1):
            log("  signin_version 表明官方客户端走 /coins/center/signin，"
                "跳过 signinv2（该接口只对新签活动开放）", "INFO", self.log_tag)
            notes.append(f"signinv2(按版本 {version} 跳过)")
        else:
            # 4.1) 官方 H5 新签通道：/coins/center/signinv2
            data = self._center_sign_call(self.device)
            errno = data.get("errno")
            error = str(data.get("error") or data.get("errmsg") or "")
            log(f"  官方客户端通道 signinv2 -> errno={errno} error={error or '无'}",
                "INFO", self.log_tag)
            if errno == 0:
                return self._finish_center_sign(data)
            if errno == -6 or self._is_login_error(error):
                return "任务中心签到: 失败（完整 cookie 已失效，需含 STOKEN）"
            last_errno, last_error = errno, error
            notes.append(f"官方通道 signinv2({CENTER_ERRNO.get(errno, error or errno)})")

            # 服务端可能上一轮已经签过（并发/上一条请求已落地）：失败后先回读状态再定性
            recheck = self._center_sign_state(self.device)
            if recheck.get("signed") is True:
                days = recheck.get("days")
                suffix = f"，已连续签到 {days} 天" if days else ""
                log("  signinv2 返回错误，但官方日历显示今日已签到 —— 按已签处理",
                    "WARN", self.log_tag)
                return f"任务中心签到: 今日已签到{suffix}"

            # 4.2) 账号/设备类风控 -> 换一台备用已登记设备再试一次
            if errno in DEVICE_RISK_ERRNO or errno == 8001:
                self.registry.set_cooldown(self.device, DEV_REPEAT_COOLDOWN, self.account_key)
                alt_data, alt_device, alt_notes = self._center_sign_device_retry()
                notes.extend(alt_notes)
                if alt_data is not None and alt_data.get("errno") == 0:
                    return self._finish_center_sign(alt_data, alt_device)

        # 4.3) 旧 H5 通道（有鉴权前风控门，脚本侧通常只会拿到 8001）
        web_data = self._center_sign_call(self.device, "/coins/center/signin")
        web_errno = web_data.get("errno")
        web_error = str(web_data.get("error") or web_data.get("errmsg") or "")
        log(f"  旧 H5 通道 signin -> errno={web_errno} error={web_error or '无'}",
            "INFO", self.log_tag)
        if web_errno == 0:
            return self._finish_center_sign(web_data)
        if web_errno == -6 or self._is_login_error(web_error):
            return "任务中心签到: 失败（完整 cookie 已失效，需含 STOKEN）"
        if web_errno in CENTER_RISK_ERRNO:
            notes.append(f"旧 H5 通道({CENTER_ERRNO.get(web_errno, web_error or web_errno)})")
            log("  旧 H5 通道的风控门在鉴权之前（账号/设备维度），脚本没有 "
                "sofire 指纹 z，无法通过；新签通道(signinv2)本来就不需要它",
                "WARN", self.log_tag)
        else:
            last_errno, last_error = web_errno, web_error

        # 4) 旧原生 taskcenter 通道（默认关闭；当前客户端已不再调用）
        if os.getenv("BAIDUWP_TASKCENTER_LEGACY", "").strip() in ("1", "true", "True"):
            legacy = self._taskcenter_signin_legacy()
            if legacy and "失败" not in legacy:
                return legacy
            notes.append(legacy or "旧原生 taskcenter 通道失败")

        if version not in (0, 1):
            self._dump_center_home("收尾诊断")
        detail = "；".join([n for n in notes if n]) or (last_error or "未知原因")
        hint = CENTER_ERRNO.get(last_errno) or TASKCENTER_ERRNO.get(last_errno) or ""
        log(f"任务中心签到失败明细: {detail}", "ERR", self.log_tag)
        if hint:
            log(f"  错误码解读(errno={last_errno}): {hint}", "ERR", self.log_tag)
        return f"任务中心签到: 失败（{detail}）"

    def _taskcenter_signin_legacy(self) -> str:
        """任务系统通道失败后的旧兼容链路（仅 BAIDUWP_TASKCENTER_LEGACY=1 启用）。

        保留原设备降级逻辑：
          * 设备标识必须长期稳定（App 是一次生成永久复用）；
          * dev repeat 只说明该设备进入服务端校验窗口，应换下一台继续；
          * 每台设备失败即写冷却时间戳，下次运行不再无脑重撞。
        """
        # 先读旧接口的签到日历；今天已签就不再折腾设备
        signed = self._taskcenter_today_signed()
        log(f"  旧原生通道签到日历: today_signed={signed}", "INFO", self.log_tag)
        if signed is True:
            return "任务中心签到: 今日已签到"

        notes = []
        need_register = False
        dumped = False          # 任务中心首页诊断每账号最多取一次
        last_errno = None       # 最后一次 signin 失败的服务端错误码
        # 网页端通道优先试一次：会话本来就是网页端的，用服务端下发的 MAWEBCUID
        # 而不是脚本伪装的安卓设备，可能根本不触发设备登记校验。
        if self._web_cuid():
            try:
                web_data = self._taskcenter_signin_web()
            except (RuntimeError, requests.RequestException) as e:
                web_data = {"errno": -1, "error": str(e)}
            web_err = str(web_data.get("error") or web_data.get("show_msg") or "")
            log(f"  网页端通道(clienttype=5 + MAWEBCUID) -> errno={web_data.get('errno')} "
                f"error={web_err or '无'}", "INFO", self.log_tag)
            if web_data.get("errno") == 0:
                days = (web_data.get("data") or {}).get("signin_days")
                return f"任务中心签到: 完成，累计 {days} 天"
            if "bduss" in web_err.lower() or "login" in web_err.lower():
                return "任务中心签到: 失败（完整 cookie 已失效，需含 STOKEN）"
            notes.append(f"网页端通道({web_err or web_data.get('errno')})")
        else:
            log("  cookie 里没有 MAWEBCUID，跳过网页端通道", "INFO", self.log_tag)
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
            last_errno = data.get("errno")
            is_new = self._probe_device_register(label, device)
            if is_new is False:
                # checkdevmp 说这台设备「不是新的」—— 再走设备参数重试毫无意义，
                # 直接把真实错误码、解读和任务中心首页状态打出来。
                hint = TASKCENTER_ERRNO.get(data.get("errno"), "")
                log(f"  设备已在册但签到仍失败: errno={data.get('errno')} "
                    f"error={error or '无'}" + (f"  —— {hint}" if hint else ""),
                    "WARN", self.log_tag)
                if not dumped:
                    self._dump_taskcenter_state(label)
                    dumped = True
                # 共享设备在本账号下失败时释放占用，让同轮其它账号还能试
                if shared:
                    self.registry.release_shared(device)
                notes.append(f"{label}(checkdevmp 非新但旧接口仍拒绝 errno={data.get('errno')})")
                continue
            # 旧接口返回非 dev-repeat（或取不到 checkdevmp 结论）：保留上一版的
            # 「补 rchannel/rand/time 再试一次」实验，仅作兼容观察。
            # 注意：旧接口 errno=2 已确认是接口契约失效，不是设备未登记。
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
            last_errno = data.get("errno")
            notes.append(f"{label}(旧接口未放行)")
            # 与 checkdevmp 结论无关：旧接口下同类失败也要留一份任务中心首页证据。
            if not dumped:
                self._dump_taskcenter_state(label)
                dumped = True
            continue


        if notes and not dumped:
            self._dump_taskcenter_state("收尾诊断")
        detail = "；".join(notes) if notes else "无可用设备"
        if need_register:
            log(f"任务中心签到(旧原生通道)失败明细: {detail}", "ERR", self.log_tag)
            hint = TASKCENTER_ERRNO.get(last_errno, "")
            if hint:
                log(f"  服务端错误码解读(errno={last_errno}): {hint}", "ERR", self.log_tag)
            log("  该接口是旧版原生 taskcenter 通道：App 13.34.3 全量 dex 中已无 "
                "\"/coins/taskcenter/signin\" 字面量，当前客户端签到走 H5 "
                "signinv2；旧接口的 errno=2 不代表设备未登记", "ERR", self.log_tag)
            log("  如主链路仍不稳定，可保留 BAIDUWP_TASKCENTER_LEGACY=1 观察，"
                "或将其关闭以减少无关请求", "ERR", self.log_tag)
            if last_errno not in (2, None):
                return (f"任务中心签到(旧原生通道): 失败（服务端返回 "
                        f"errno={last_errno}）")
            return "任务中心签到(旧原生通道): 失败（旧接口契约已失效）"
        log(f"旧原生通道失败明细: {detail}", "WARN", self.log_tag)
        return f"任务中心签到(旧原生通道): 失败（{detail}）"

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
            # 首次登录（本账号第一次跑）先把设备上报到云端，之后一直复用同一台
            self.emit(self.ensure_device_registered())
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


def device_profile_warnings() -> list:
    """校验「channel / WebView UA / 机型画像」三者是否自洽。

    真实客户端里三者的取值都来自同一个 Build：channel 是
    android_<RELEASE>_<MODEL>_bd-netdisk_<后缀>，UA 里又有
    Android <RELEASE>; <MODEL> Build/<id>。只改一处就会出现
    “channel 写小米、UA 写 vivo”这种自相矛盾 —— 它比“用错机型”更容易被判定为伪造。
    """
    warns = []
    prof = DEVICE_PROFILE
    m_chan = re.search(r"^android_([0-9.]+)_([^_]+)_bd-netdisk_", TASK_CHANNEL)
    m_ua = re.search(r"Android ([0-9.]+);\s*([^;]+?)\s+Build/", TASK_UA)
    if not m_chan:
        warns.append(f"channel 形态不认识（应为 android_<版本>_<机型>_bd-netdisk_<后缀>）："
                     f"{TASK_CHANNEL}")
    if not m_ua:
        warns.append(f"UA 里找不到 'Android <版本>; <机型> Build/<id>' 结构：{TASK_UA[:60]}…")
    if m_chan and m_ua:
        chan_rel, chan_model = m_chan.group(1), m_chan.group(2)
        ua_rel, ua_model = m_ua.group(1), m_ua.group(2)
        if chan_model != ua_model:
            warns.append(f"channel 机型({chan_model}) 与 UA 机型({ua_model}) 不一致"
                         " —— 这是“一眼假”的头号特征")
        if chan_rel != ua_rel:
            warns.append(f"channel Android 版本({chan_rel}) 与 UA 版本({ua_rel}) 不一致")
        if chan_model != prof["model"]:
            warns.append(f"channel 机型({chan_model}) 与机型画像({prof['model']}) 不一致"
                         "（自己改过 BAIDUWP_CHANNEL？）")
    return warns


def log_device_profile():
    """开局打一次设备画像与指纹参数，并自查自洽性。"""
    log(f"设备画像: {DEVICE_PROFILE_NAME} — {DEVICE_PROFILE['label']}")
    log(f"  channel: {TASK_CHANNEL}")
    log(f"  UA: {TASK_UA}")
    warns = device_profile_warnings()
    for w in warns:
        log(f"  指纹不自洽: {w}", "WARN")
    if not warns:
        log("  指纹自洽: channel / UA / 机型同源", "DEBUG")
    # 内置 z 是从 vivo V2364A 的 MuMu 实例上抓的：机型画像换成小米 14 后，
    # 如果服务端拿 z 与声明的机型对账，就会“机器是同一个人脸不对”。
    if not os.getenv("BAIDUWP_Z", "").strip() and DEVICE_PROFILE_NAME != "vivo-v2364a":
        log("  z 来源: 内置抓包值（来自 vivo V2364A），与当前机型画像不同源；"
            "若该通道要求 z 与机型一致，请用 BAIDUWP_PROFILE=vivo-v2364a，"
            "或提供这台机型的 BAIDUWP_Z / BAIDUWP_Z_n", "WARN")


def main():
    random_delay()
    log_device_profile()
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
