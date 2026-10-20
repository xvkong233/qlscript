"""
new Env('雨云积分签到')

cron: 50 8 * * *

雨云（Rainyun）积分中心「赚取积分」自动签到 / 自动领任务（青龙订阅版）

功能：每日签到领积分，多账号，可选自动领取积分任务。接口全部从 app.rainyun.com
      前端代码逆向确认（2026-10，chunk-common + 路由 /account/reward/earn 的 chunk 6317）：
        GET  https://api.v2.rainyun.com/user/csrf          取 CSRF 令牌（脚本自动完成）
        GET  https://api.v2.rainyun.com/user/              用户信息（显示账号名/积分）
        GET  https://api.v2.rainyun.com/user/reward/tasks  任务列表（Status: 0去完成/1可领取/2已完成）
        POST https://api.v2.rainyun.com/user/reward/tasks  领取任务奖励
              body: {"task_name":"每日签到","verifyCode":""}
                    需要人机验证时追加: "vticket":"<TCaptcha票据>","vrandstr":"<随机串>"

     字段语义（前端 doneTask 实证，别搞混）：
        verifyCode  = 任务密码（人肉答案）。每日签到留空；「加入Q群/关注B站/抖音/淘宝店」
                      这类任务要填你收到的暗号（如官方号私信结尾4个字）。
        vticket     = 腾讯天御验证码 TCaptcha 的 ticket（appid 2039519451）
        vrandstr    = TCaptcha 回调的随机串
        ★ 10004(CommonCaptchaError) 要的是 vticket/vrandstr，不是 verifyCode。

     鉴权两种通道（自动选择，API Key 优先）：
        [通道A] X-Api-Key 头 —— 免 Cookie/免 CSRF/免人机验证，最稳，推荐。
        [通道B] Cookie 会话 —— Cookie + X-CSRF-Token 头 + RYS 头（fea 常量+时间戳，
                运行时从 app.rainyun.com/fea 拉取，拉不到用内置值）。

环境变量：
  RAINYUN_API_KEY  可选（推荐）：雨云 API 密钥。形如 ryapi_xxxxxxxx。
                   获取：https://app.rainyun.com/account/settings/api-key → 创建/复制。
                   设置后脚本自动走通道A，忽略 RAINYUN_COOKIE。
                   多账号：用 & 或换行分隔，也支持 RAINYUN_API_KEY_1、_2 ...
                   ★ 安全提醒：API 密钥等于账号凭证，只放在青龙环境变量里，别提交进 git。

  RAINYUN_COOKIE   可选：api.v2.rainyun.com 的完整 Cookie（未设 RAINYUN_API_KEY 时使用）。
                   获取：浏览器登录 app.rainyun.com → F12 → 网络(Network) → 随便点一个
                   api.v2.rainyun.com 请求 → 请求标头 → 复制整个 Cookie 的值整段粘贴。
                   注意是 api.v2.rainyun.com 域的 cookie，不是 app.rainyun.com 的。
                   多账号：单变量内用 & 或换行分隔（cookie 内部本来就用分号，别再用分号切，
                   否则会把 rain-session 切碎）；也支持 RAINYUN_COOKIE_1、_2 ...

  RAINYUN_TASK_PASSWORDS  可选：积分任务密码表，用于自动领取需要暗号的任务。
                   格式一（推荐）：任务名=密码;任务名=密码
                       关注雨云B站号=abcd;关注雨云抖音号=最后五个字;关注雨云淘宝店=前四字
                   格式二：JSON  {"关注雨云B站号":"abcd","关注雨云抖音号":"最后五个字"}
                   未配置的任务会列在推送里提示手动领取。

  RAINYUN_CLAIM_ALL  可选，默认 0：设为 1 时，对所有 Status=1 的任务都用（已配置的密码或
                   空密码）尝试领取。用于顺手把可领积分清掉。

  RAINYUN_CAPTCHA_URL / RAINYUN_CAPTCHA_METHOD / RAINYUN_CAPTCHA_DATA
                   可选：外部打码服务（通道 a），仅在遇到 10004 时使用，自动换 TCaptcha 票据。
                   RAINYUN_CAPTCHA_METHOD = GET 或 POST（默认 POST）
                   RAINYUN_CAPTCHA_DATA   = 发给打码服务的 JSON 体，支持两个占位符：
                       {appid} → 2039519451，{url} → https://app.rainyun.com/account/reward/earn
                   响应里只要能递归找到 ticket 和 randstr 字段即可，脚本自动解析。

  RAINYUN_TCAPTCHA_SOLVER
                   可选（推荐，通道 b）：真浏览器求解器路径，指向 solve_tcaptcha.cjs。
                   设置后，遇到 10004 会自动拉起 node + Playwright + 真 Chrome：
                     抓指令条 + 背景图 → 黑帽分割 + 尺度/旋转双不变 NCC 求点击坐标
                     → page.mouse 派发真实点击 → 点击「确定」提交 → 取回 ticket/randstr
                     并带 vticket/vrandstr 重投雨云接口。
                   前置：本机有 node + Playwright + Chrome，且 numpy/Pillow 可用。
                   示例：
                     RAINYUN_TCAPTCHA_SOLVER=/ql/scripts/rainyun/solve_tcaptcha.cjs
                   RAINYUN_TCAPTCHA_TIMEOUT 求解器超时秒数，默认 300。

  RAINYUN_DELAY    每日随机延迟上限（分钟），默认 10：启动后随机等 0~10 分钟再执行，
                   让每天实际签到时间不同；设为 0 关闭（手动调试用）。账号间随机间隔 3~15 秒。

返回码（前端错误码表 chunk-common 89266）：
      code 200=成功；10012=CSRF 失效（脚本自动刷新重试）；
      10004=需要人机验证（CommonCaptchaError，脚本先试打码、不行则给出诊断指引）；
      30011=未达到完成该任务的条件（非验证码问题，多为前置条件未满足或软拦截）；
      30002/30038=登录失效（重新复制 Cookie 或换 API Key）。
      签到结果以重查任务列表 Status=2 为准，不依赖返回包语义。

依赖：requests（青龙 依赖管理 -> Python3 -> 安装 requests）
"""

import json
import os
import random
import re
import subprocess
import sys
import time

import requests

API = "https://api.v2.rainyun.com"
APP = "https://app.rainyun.com"
FEA_URL = APP + "/fea"
FEA_FALLBACK = "5aabb7f9538a0db57bb6c767c34810fd"  # 2026-10 抓取，运行时会尝试更新
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TIMEOUT = 15
DAILY_TASK = "每日签到"

# TCaptcha（腾讯天御验证码）—— app.rainyun.com 前端实证：new TencentCaptcha("2039519451", cb)
CAPTCHA_APPID = "2039519451"
CAPTCHA_PAGE_URL = APP + "/account/reward/earn"

# 前端错误码表（chunk-common 模块 89266）
CODE_CSRF_FAILED = 10012
CODE_CAPTCHA = 10004        # CommonCaptchaError：需要 TCaptcha 票据
CODE_LOGIN_REQUIRED = (30002, 30038)
CODE_CONDITION_NOT_MET = 30011

# 真浏览器求解器（B 路径）：node + Playwright 过 TCaptcha 点选挑战，产出 ticket/randstr
# 指向 solve_tcaptcha.cjs（支持 --json 机器可读输出）
BROWSER_SOLVER = (os.getenv("RAINYUN_TCAPTCHA_SOLVER") or "").strip()
BROWSER_SOLVER_TIMEOUT = int(os.getenv("RAINYUN_TCAPTCHA_TIMEOUT") or "300")

# 【CWE-602 实证】任务密码白名单硬编码在客户端 chunk 6317.js 的 verifyTasks 里：
#   verifyTasks:{"加入Q群":["我爱雨云"],"加入微信群":["雨云爱我"],
#                "关注雨云淘宝店":["成功加入","关注成功"],
#                "关注雨云B站号":["雨云爱你"],"关注雨云抖音号":["天气狐爱你"]}
# 校验逻辑 doneTask() 里只是 const s=verifyTasks[t]; if(s&&!s.includes(e)) 拒绝 ——
# 纯客户端 Array.includes，服务端从未参与。此处作为内置默认值，可用
# RAINYUN_TASK_PASSWORDS 覆盖。
DEFAULT_TASK_PASSWORDS = {
    "加入Q群": ["我爱雨云"],
    "加入用户群": ["我爱雨云"],
    "加入微信群": ["雨云爱我"],
    "关注雨云淘宝店": ["成功加入", "关注成功"],
    "关注雨云B站号": ["雨云爱你"],
    "关注雨云抖音号": ["天气狐爱你"],
}

CAPTCHA_HELP = (
    "签到失败: 风控要求人机验证（10004）\n"
    "  成因: 雨云风控判定当前为非常规环境 —— 典型组合是「机房 IP + 无浏览器指纹 + "
    "dev-code 设备码与浏览器不一致」。实测同一出口 IP 的浏览器会话打这个接口并不弹验证码。\n"
    "  处理: ①【推荐】配置 RAINYUN_API_KEY，走免人机验证的 API Key 通道；\n"
    "        ② 配置 RAINYUN_TCAPTCHA_SOLVER 指向 solve_tcaptcha.cjs，真浏览器自动过点选挑战；\n"
    "        ③ 配置 RAINYUN_CAPTCHA_URL/METHOD/DATA 接打码平台；\n"
    "        ④ 兜底去网页端手动签到（只解决当天，次日照样触发）。"
)


# ---------------------------------------------------------------- 工具函数
def parse_cookie(raw: str) -> dict:
    """把 'a=b; c=d' 解析成 dict。cookie 值里可能含 '='（如 user-data），按第一个 '=' 切。"""
    jar = {}
    for part in (raw or "").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, val = part.split("=", 1)
        key = key.strip()
        if key:
            jar[key] = val.strip()
    return jar


def cookie_names(raw: str) -> str:
    """只列出 cookie 字段名，用于诊断输出，不泄露任何值。"""
    names = list(parse_cookie(raw).keys())
    return ", ".join(names) if names else "(空)"


def split_values(raw: str, require_eq: bool) -> list:
    """按 & 或换行切多账号。require_eq=True 时要求片段含 '='（用于 cookie）。"""
    parts = []
    for p in re.split(r"[&\n\r]+", raw or ""):
        p = p.strip()
        if not p:
            continue
        if require_eq and "=" not in p:
            continue
        parts.append(p)
    seen, out = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def load_numbered(base_name: str, require_eq: bool) -> list:
    """单变量多账号 + 编号轮询（断号后连续 3 个缺失停止扫描）。"""
    entries = split_values(os.getenv(base_name, ""), require_eq)
    misses = 0
    for i in range(1, 100):
        var = split_values(os.getenv(f"{base_name}_{i}", ""), require_eq)
        if var:
            misses = 0
            entries.extend(var)
        else:
            misses += 1
            if misses >= 3:
                break
    seen, unique = set(), []
    for e in entries:
        if e not in seen:
            seen.add(e)
            unique.append(e)
    return unique


def load_task_passwords() -> dict:
    """RAINYUN_TASK_PASSWORDS：'名字=密码;名字=密码' 或 JSON 对象。返回 {任务名: [候选密码]}。"""
    table = {k: list(v) for k, v in DEFAULT_TASK_PASSWORDS.items()}
    raw = (os.getenv("RAINYUN_TASK_PASSWORDS") or "").strip()
    if not raw:
        return table
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            for k, v in data.items():
                table[str(k)] = [str(x) for x in v] if isinstance(v, list) else [str(v)]
        except ValueError:
            print("RAINYUN_TASK_PASSWORDS JSON 解析失败，已忽略", flush=True)
        return table
    for item in raw.split(";"):
        if "=" not in item:
            continue
        name, code = item.split("=", 1)
        name, code = name.strip(), code.strip()
        if name:
            table[name] = [code]
    return table


def fetch_fea() -> str:
    """RYS 头用的 fea 常量，运行时从前端脚本拉最新的，失败用内置值。"""
    try:
        r = requests.get(FEA_URL, timeout=TIMEOUT, headers={"User-Agent": UA})
        m = re.search(r"fea\s*=\s*['\"]([0-9a-f]+)['\"]", r.text)
        if m:
            return m.group(1)
    except requests.RequestException:
        pass
    return FEA_FALLBACK


# ---------------------------------------------------------------- 打码（通道B 兜底）
def _fill_placeholders(node):
    """递归把 {appid} / {url} 占位符替换掉。"""
    if isinstance(node, dict):
        return {k: _fill_placeholders(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill_placeholders(v) for v in node]
    if isinstance(node, str):
        return node.replace("{appid}", CAPTCHA_APPID).replace("{url}", CAPTCHA_PAGE_URL)
    return node


def _find_ticket(node):
    """在打码服务返回的任意嵌套结构里找 ticket / randstr。"""
    ticket, randstr = None, None

    def walk(n):
        nonlocal ticket, randstr
        if isinstance(n, dict):
            for k, v in n.items():
                lk = str(k).lower()
                if isinstance(v, str):
                    if lk == "ticket" and not ticket:
                        ticket = v
                    elif lk in ("randstr", "rand_str") and not randstr:
                        randstr = v
                else:
                    walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(node)
    return ticket, randstr


def solve_captcha():
    """调外部打码服务换 TCaptcha 票据。返回 ((ticket, randstr)|None, 错误信息)。"""
    url = (os.getenv("RAINYUN_CAPTCHA_URL") or "").strip()
    if not url:
        return None, "未配置 RAINYUN_CAPTCHA_URL"
    method = (os.getenv("RAINYUN_CAPTCHA_METHOD") or "POST").strip().upper()
    raw = (os.getenv("RAINYUN_CAPTCHA_DATA") or "").strip()
    payload = {}
    if raw:
        try:
            payload = json.loads(raw)
        except ValueError:
            return None, "RAINYUN_CAPTCHA_DATA 不是合法 JSON"
        payload = _fill_placeholders(payload)
    try:
        if method == "GET":
            resp = requests.get(url, params=payload, timeout=30)
        else:
            resp = requests.post(url, json=payload, timeout=30)
    except requests.RequestException as e:
        return None, f"打码服务网络异常 {e.__class__.__name__}: {e}"
    try:
        data = resp.json()
    except ValueError:
        return None, f"打码服务返回非 JSON（HTTP {resp.status_code}）"
    ticket, randstr = _find_ticket(data)
    if not ticket:
        return None, f"打码服务未返回 ticket: {json.dumps(data, ensure_ascii=False)[:160]}"
    return (ticket, randstr or ""), ""


def solve_captcha_via_browser():
    """B 路径：调 Node + Playwright 真浏览器自动化过 TCaptcha 点选挑战。

    原理（已实测）：真 Chrome 里 TCaptcha 下发「按顺序点选」硬挑战；
    抓取指令条 + 背景图 → 黑帽分割 + 尺度/旋转双不变 NCC 求坐标 →
    page.mouse 派发真实点击 → ★必须点击「确定」提交 → 回调取得 ticket/randstr。

    返回 ((ticket, randstr)|None, 错误信息)。
    """
    if not BROWSER_SOLVER:
        return None, "未配置 RAINYUN_TCAPTCHA_SOLVER"
    if not os.path.exists(BROWSER_SOLVER):
        return None, f"求解器脚本不存在: {BROWSER_SOLVER}"
    try:
        proc = subprocess.run(
            ["node", BROWSER_SOLVER, "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=BROWSER_SOLVER_TIMEOUT,
            cwd=os.path.dirname(os.path.abspath(BROWSER_SOLVER)) or None,
        )
    except subprocess.TimeoutExpired:
        return None, f"浏览器求解器超时（{BROWSER_SOLVER_TIMEOUT}s）"
    except Exception as e:  # noqa: BLE001
        return None, f"浏览器求解器调用失败 {e.__class__.__name__}: {e}"
    for line in (proc.stdout or "").splitlines():
        if not line.startswith("TCAP_JSON "):
            continue
        try:
            d = json.loads(line[len("TCAP_JSON "):])
        except ValueError:
            continue
        if d.get("ok") and d.get("ticket"):
            return (d["ticket"], d.get("randstr") or ""), ""
        return None, ("浏览器求解器未取到票据: "
                      + str(d.get("error") or json.dumps(d, ensure_ascii=False)[:120]))
    tail = " | ".join((proc.stderr or "").strip().splitlines()[-3:])
    return None, f"浏览器求解器无有效输出（exit={proc.returncode}）{tail}"


# ---------------------------------------------------------------- 账号
class Account:
    def __init__(self, index: int, mode: str, cred: str, fea: str = ""):
        self.index = index
        self.mode = mode                 # "api_key" | "cookie"
        self.fea = fea
        self.csrf = ""
        self.name = ""
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": UA,
            "Content-Type": "application/json",
            "Origin": APP,
            "Referer": APP + "/",
        })
        if mode == "api_key":
            self.session.headers["X-Api-Key"] = cred
        else:
            self.session.cookies.update(parse_cookie(cred))
            # 用 cookie jar 而非固定 Cookie 头：雨云会在响应里轮换 rain-session，
            # jar 能自动接管，固定头会一直用旧值。

    @property
    def label(self) -> str:
        return self.name or f"账号{self.index}"

    def _headers(self) -> dict:
        h = {}
        if self.mode == "cookie":
            h["RYS"] = f"{self.fea}{round(time.time(), 3)}"   # 前端 RYS = fea + Date.getTime()/1000
            if self.csrf:
                h["X-CSRF-Token"] = self.csrf
        return h

    def _call(self, method: str, path: str, body=None):
        """返回 (envelope|None, err)。GET 时 body 作为 query 参数发送。"""
        kwargs = {"headers": self._headers(), "timeout": TIMEOUT}
        if body is not None:
            kwargs["params" if method == "GET" else "json"] = body
        try:
            resp = self.session.request(method, API + path, **kwargs)
        except requests.RequestException as e:
            return None, f"网络异常 {e.__class__.__name__}: {e}"
        try:
            return resp.json(), None
        except ValueError:
            return None, f"HTTP {resp.status_code} 响应非 JSON"

    @staticmethod
    def _code(data) -> int:
        return (data.get("code") or 0) if isinstance(data, dict) else 0

    @staticmethod
    def _ok(data) -> bool:
        """雨云成功包络 code=200；兼容 0/201/204。"""
        return Account._code(data) in (0, 200, 201, 204)

    @staticmethod
    def _msg(data) -> str:
        return str(data.get("message") or "") if isinstance(data, dict) else ""

    @staticmethod
    def _payload(data):
        return data.get("data") if isinstance(data, dict) else None

    def _login_expired(self, data) -> bool:
        return self._code(data) in CODE_LOGIN_REQUIRED

    # ---------- 各接口 ----------
    def refresh_csrf(self) -> str:
        """GET /user/csrf → data 即令牌。通道A 不需要。返回错误信息，空串为成功。"""
        if self.mode == "api_key":
            return ""
        data, err = self._call("GET", "/user/csrf")
        if err:
            return err
        if self._login_expired(data):
            return "登录已失效（API Key 无效或 Cookie 过期）"
        token = self._payload(data)
        if not token or not isinstance(token, str):
            return f"获取 CSRF 令牌失败: {json.dumps(data, ensure_ascii=False)[:120]}"
        self.csrf = token
        return ""

    def load_profile(self) -> str:
        """GET /user/ → 用户信息。返回错误信息，空串为成功。"""
        data, err = self._call("GET", "/user/", body={"no_cache": True})
        if err:
            return err
        if self._login_expired(data):
            return "登录已失效（需要重新获取 Cookie / API Key）"
        if not self._ok(data):
            return self._msg(data) or f"code {self._code(data)}"
        user = self._payload(data) or {}
        self.name = str(user.get("Name") or "")[:32]
        points = next((user[k] for k in ("Points", "points", "Point") if user.get(k) is not None), None)
        balance = next((user[k] for k in ("Balance", "balance") if user.get(k) is not None), None)
        extra = "，".join(x for x in (
            f"积分 {points}" if points is not None else "",
            f"余额 {balance}" if balance is not None else "",
        ) if x)
        print(f"  用户信息: {self.name or '未知'}{f'（{extra}）' if extra else ''}", flush=True)
        return ""

    def get_tasks(self):
        """返回 (tasks|None, err)。tasks: [{Name, Status, Points, Detail}]。"""
        data, err = self._call("GET", "/user/reward/tasks")
        if err:
            return None, err
        if self._login_expired(data):
            return None, "登录已失效（需要重新获取 Cookie / API Key）"
        if not self._ok(data):
            return None, self._msg(data) or f"code {self._code(data)}"
        tasks = self._payload(data)
        if not isinstance(tasks, list):
            return None, f"任务列表格式异常: {json.dumps(data, ensure_ascii=False)[:120]}"
        return tasks, ""

    def _post_task(self, task_name: str, verify_code: str = ""):
        """POST 领取任务。返回 (envelope|None, err)。

        处理链：CSRF 失效 → 刷新重试；10004 → 打码拿 TCaptcha 票据，带
        vticket/vrandstr 重投一次。
        """
        body = {"task_name": task_name, "verifyCode": verify_code}
        data, captcha_tried = None, False
        for attempt in range(1, 4):
            if self.mode == "cookie" and not self.csrf:
                if err := self.refresh_csrf():
                    return None, err
            data, err = self._call("POST", "/user/reward/tasks", body)
            if err:
                return None, err
            code = self._code(data)
            if code == CODE_CSRF_FAILED and attempt == 1:
                print("  CSRF 令牌失效，刷新后重试一次...", flush=True)
                self.csrf = ""
                continue
            if code == CODE_CAPTCHA and not captcha_tried:
                captcha_tried = True
                print("  风控要求人机验证（10004），尝试自动过验证码...", flush=True)
                cap, cap_err = (None, "")
                if (os.getenv("RAINYUN_CAPTCHA_URL") or "").strip():
                    print("    [a] 尝试打码平台...", flush=True)
                    cap, cap_err = solve_captcha()
                if not cap and BROWSER_SOLVER:
                    print("    [b] 改用真浏览器求解 TCaptcha 点选挑战（约 10~40s）...", flush=True)
                    cap, cap_err = solve_captcha_via_browser()
                if not cap:
                    print(f"    自动过验证码失败: {cap_err}", flush=True)
                    return data, ""
                body = {"task_name": task_name, "verifyCode": verify_code,
                        "vticket": cap[0], "vrandstr": cap[1]}
                print(f"    已取得 TCaptcha 票据（randstr={cap[1]}），带 vticket/vrandstr 重投...", flush=True)
                continue
            return data, ""
        return data, ""

    def claim_and_verify(self) -> str:
        """领取「每日签到」，并以重查任务状态（Status=2）为准判定结果。

        ★ 不要用返回码当判据：实测 30011「未达到完成这个任务的条件」在
        领取成功时也会返回（已用 关注B站/关注淘宝店 两个任务实测：返回 30011
        但积分各 +1000）。唯一可靠判据是复查任务列表 Status。
        """
        data, err = self._post_task(DAILY_TASK)
        if err:
            return f"签到失败: {err}"
        code, msg = self._code(data), self._msg(data)
        if code == CODE_CAPTCHA:
            return CAPTCHA_HELP
        if self._login_expired(data):
            return "登录已失效，请重新获取 RAINYUN_COOKIE 或改用 RAINYUN_API_KEY"
        print("  已提交领取请求，复查任务状态...", flush=True)
        time.sleep(2)
        tasks, err = self.get_tasks()
        if err:
            return f"签到请求已提交，但复查任务状态失败: {err}"
        daily = next((t for t in tasks if t.get("Name") == DAILY_TASK), None)
        if daily is not None and str(daily.get("Status")) == "2":
            return "签到成功"
        if "已" in msg and ("签" in msg or "领取" in msg):
            return "今日已签到"
        if code == CODE_CONDITION_NOT_MET:
            return (f"签到失败: {msg or code}\n"
                    f"  （已复查任务状态，Status 仍非 2）。注意 30011 不是可靠的成功判断位，\n"
                    f"  实测同一台机器上 关注B站/关注淘宝店 返回 30011 但实际已领到分。\n"
                    f"  若这是「每日签到」，基本可确定是风控要求 TCaptcha 票据 —— 浏览器里\n"
                    f"  点一次会先弹验证码，过了才真正入账。")
        return f"签到失败: {msg or code or '提交后任务状态未变为已完成'}"

    def claim_extra(self, tasks: list, passwords: dict, claim_all: bool) -> list:
        """尝试领取「每日签到」以外的可领取任务。返回结果行列表。"""
        lines = []
        targets = [t for t in tasks if str(t.get("Status")) == "1" and t.get("Name") != DAILY_TASK]
        for t in targets:
            name = str(t.get("Name"))
            codes = passwords.get(name, [])
            if not codes:
                if not claim_all:
                    continue
                codes = [""]
            outcome = None
            for code in codes:
                data, err = self._post_task(name, code)
                if err:
                    outcome = f"失败（{err}）"
                    break
                rc = self._code(data)
                if rc == CODE_CAPTCHA:
                    outcome = "风控要求人机验证，未能自动领取"
                    break
                # ★ 不信返回码，复查该任务 Status 才算数（实测 30011 也可能是成功）
                time.sleep(1.5)
                fresh, _ = self.get_tasks()
                cur = next((x for x in (fresh or []) if x.get("Name") == name), None)
                if cur is not None and str(cur.get("Status")) == "2":
                    outcome = f"领取成功（+{t.get('Points')}分）"
                    break
                if rc == CODE_CONDITION_NOT_MET:
                    outcome = (f"未领取成功（{self._msg(data) or rc}；已复查 Status 仍非 2，"
                               f"不再重试其他密码）")
                    break
                outcome = f"失败（{self._msg(data) or rc}）"
            lines.append(f"  {name}: {outcome}")
            time.sleep(random.uniform(1.0, 3.0))
        return lines

    # ---------- 主流程 ----------
    def run(self, passwords: dict, claim_all: bool) -> str:
        if err := self.refresh_csrf():
            return f"初始化失败: {err}"
        if err := self.load_profile():
            print(f"  用户信息获取失败（不影响签到）: {err}", flush=True)

        tasks, err = self.get_tasks()
        if err:
            return f"签到失败: {err}"
        daily = next((t for t in tasks if t.get("Name") == DAILY_TASK), None)
        if daily is None:
            return f"任务列表里没有「{DAILY_TASK}」（接口可能已变更）"

        if str(daily.get("Status")) == "2":
            result = "今日已签到"
        else:
            result = self.claim_and_verify()

        lines = [f"每日签到: {result}"]

        claimed = self.claim_extra(tasks, passwords, claim_all)
        if claimed:
            lines.append("自动领取的其他任务:")
            lines.extend(claimed)
            fresh, _ = self.get_tasks()
            if fresh:
                tasks = fresh

        claimable = [t for t in tasks if str(t.get("Status")) == "1" and t.get("Name") != DAILY_TASK]
        if claimable:
            names = "、".join(f"{t.get('Name')}({t.get('Points')}分)" for t in claimable[:6])
            lines.append(f"还有可领取的积分任务: {names}")
            lines.append("  （网页端「赚取积分」页手动领取；或用 RAINYUN_TASK_PASSWORDS "
                         "配置任务密码 / RAINYUN_CLAIM_ALL=1 让脚本自动领）")
        return "\n".join(lines)


# ---------------------------------------------------------------- 主入口
def random_delay():
    max_minutes = 10
    raw = os.getenv("RAINYUN_DELAY", "").strip()
    if raw.isdigit():
        max_minutes = int(raw)
    if max_minutes <= 0:
        return
    seconds = random.randint(0, max_minutes * 60)
    print(f"随机延迟 {seconds // 60} 分 {seconds % 60} 秒后开始（RAINYUN_DELAY={max_minutes} 分钟内随机）...",
          flush=True)
    time.sleep(seconds)


def load_accounts() -> list:
    """返回 [(mode, credential)]，API Key 通道优先。"""
    keys = load_numbered("RAINYUN_API_KEY", require_eq=False)
    if keys:
        return [("api_key", k) for k in keys]
    cookies = load_numbered("RAINYUN_COOKIE", require_eq=True)
    return [("cookie", c) for c in cookies]


def main():
    random_delay()
    accounts = load_accounts()
    if not accounts:
        print("未配置环境变量：RAINYUN_API_KEY（推荐）或 RAINYUN_COOKIE"
              "（获取方法见脚本头部注释或仓库 README）")
        sys.exit(1)

    passwords = load_task_passwords()
    claim_all = (os.getenv("RAINYUN_CLAIM_ALL", "").strip() == "1")
    fea = fetch_fea() if any(m == "cookie" for m, _ in accounts) else ""
    has_captcha = bool((os.getenv("RAINYUN_CAPTCHA_URL") or "").strip())

    print(f"共 {len(accounts)} 个账号，通道: {accounts[0][0]}"
          f"，自动打码: {'已配置' if has_captcha else '未配置'}", flush=True)
    if accounts[0][0] == "cookie":
        print(f"  cookie 字段: {cookie_names(accounts[0][1])}", flush=True)

    results = []
    for i, (mode, cred) in enumerate(accounts, 1):
        account = Account(i, mode, cred, fea)
        header = f"===== 账号 {i} ====="
        print(header)
        try:
            msg = account.run(passwords, claim_all)
        except Exception as e:  # noqa: BLE001 账号级失败隔离
            msg = f"执行异常: {e.__class__.__name__}: {e}"
        print(msg, "\n")
        if "已失效" in msg or "HTTP 4" in msg:
            msg += "\n（提示：重新获取 Cookie，或改用 RAINYUN_API_KEY 走免验证通道）"
        results.append(f"{header}【{account.label}】\n{msg}")
        if i < len(accounts):
            gap = random.randint(3, 15)
            print(f"等待 {gap}s 后处理下一个账号...", flush=True)
            time.sleep(gap)
    try:
        from notify import send  # type: ignore
        send("雨云积分签到", "\n\n".join(results))
    except Exception:
        pass


if __name__ == "__main__":
    main()
