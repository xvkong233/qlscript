"""
new Env('雨云积分签到')

cron: 50 8 * * *

雨云（Rainyun）积分中心「赚取积分-每日签到」（青龙订阅版）

功能：每日签到领积分，多账号。接口全部从 app.rainyun.com 前端代码逆向确认（2026-10）：
     GET  https://api.v2.rainyun.com/user/csrf          取 CSRF 令牌（脚本自动完成，无需配置）
     GET  https://api.v2.rainyun.com/user/              用户信息（用于显示账号名/积分）
     GET  https://api.v2.rainyun.com/user/reward/tasks  积分任务列表（Status: 0去完成/1可领取/2已完成）
     POST https://api.v2.rainyun.com/user/reward/tasks  领取任务奖励，body: {"task_name":"每日签到","verifyCode":""}
     鉴权：Cookie 会话 + X-CSRF-Token 头 + RYS 头（fea 常量+时间戳，脚本运行时自动从
           app.rainyun.com/fea 拉取，拉不到用内置值）。

环境变量：
  RAINYUN_COOKIE   必填：api.v2.rainyun.com 的完整 Cookie。
                   获取：浏览器登录 app.rainyun.com → F12 → 网络(Network) → 随便点一个
                   api.v2.rainyun.com 请求 → 请求标头 → 复制整个 Cookie 的值粘贴即可
                   （形如 "xxx=yyy; zzz=aaa"，分号没关系，直接整段粘）。
                   注意不是 app.rainyun.com 域下的 cookie，是 api.v2.rainyun.com 的。

  多账号：单变量内用 & 或换行分隔多份 cookie（cookie 值本身用分号分隔，所以这里
                   不能用分号），也支持编号轮询 RAINYUN_COOKIE、RAINYUN_COOKIE_1、...

  RAINYUN_DELAY    每日随机延迟上限（分钟），默认 10：脚本启动后随机等待 0~10 分钟再执行，
                   使每天实际签到时间不同；设为 0 关闭（手动调试用）。账号间随机间隔 3~15 秒。

返回码（前端错误码表）：code 200=成功（HTTP 风格，实测 2026-10）；10012=CSRF 失效（脚本自动刷新令牌重试）；
     10004=触发滑块验证码（脚本无法过验证，请去网页手动签一次再恢复自动）；
     30002/30038=登录失效（重新复制 Cookie 更新环境变量，会话一般月级有效）。
     签到结果以重查任务列表 Status=2 为准，不依赖返回包语义。

依赖：requests（青龙 依赖管理 -> Python3 -> 安装 requests）
"""

import json
import os
import random
import re
import sys
import time

import requests

API = "https://api.v2.rainyun.com"
FEA_URL = "https://app.rainyun.com/fea"
FEA_FALLBACK = "5aabb7f9538a0db57bb6c767c34810fd"  # 2026-10 抓取，运行时会尝试更新
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TIMEOUT = 15
DAILY_TASK = "每日签到"
# 前端错误码表（app.rainyun.com 前端 chunk-common 模块 89266）
CODE_CSRF_FAILED = 10012
CODE_CAPTCHA = 10004
CODE_LOGIN_REQUIRED = (30002, 30038)


class Account:
    def __init__(self, index: int, cookie: str, fea: str):
        self.index = index
        self.cookie = cookie.strip()
        self.fea = fea
        self.csrf = ""
        self.name = ""

    @property
    def label(self) -> str:
        return self.name or f"账号{self.index}"

    def _headers(self) -> dict:
        return {
            "User-Agent": UA,
            "Content-Type": "application/json",
            "Origin": "https://app.rainyun.com",
            "Referer": "https://app.rainyun.com/",
            "Cookie": self.cookie,
            "X-CSRF-Token": self.csrf,
            # 前端 RYS = fea + Date.getTime()/1000（字符串拼接）
            "RYS": f"{self.fea}{round(time.time(), 3)}",
        }

    def _call(self, method: str, path: str, body=None):
        """返回 (envelope|None, err)。envelope 为雨云统一返回 {code, message, data}；
        GET 时 body 作为 query 参数发送（与前端 axios params 一致）。"""
        kwargs = {"headers": self._headers(), "timeout": TIMEOUT}
        if body is not None:
            kwargs["params" if method == "GET" else "json"] = body
        try:
            resp = requests.request(method, API + path, **kwargs)
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
        """雨云成功包络 code=200（HTTP 风格，实测 2026-10）；兼容 0。"""
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
        """GET /user/csrf → data 即令牌。返回错误信息，空串为成功。"""
        data, err = self._call("GET", "/user/csrf")
        if err:
            return err
        if self._login_expired(data):
            return "Cookie 已失效（需要登录）"
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
            return "Cookie 已失效（需要登录）"
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
            return None, "Cookie 已失效（需要登录）"
        if not self._ok(data):
            return None, self._msg(data) or f"code {self._code(data)}"
        tasks = self._payload(data)
        if not isinstance(tasks, list):
            return None, f"任务列表格式异常: {json.dumps(data, ensure_ascii=False)[:120]}"
        return tasks, ""

    def _post_claim(self):
        """POST 领取「每日签到」。返回 (envelope|None, err)；CSRF 失效自动刷新重试一次。"""
        data = None
        for attempt in (1, 2):
            if not self.csrf:
                if err := self.refresh_csrf():
                    return None, err
            data, err = self._call("POST", "/user/reward/tasks",
                                   {"task_name": DAILY_TASK, "verifyCode": ""})
            if err:
                return None, err
            if self._code(data) == CODE_CSRF_FAILED and attempt == 1:
                print("  CSRF 令牌失效，刷新后重试一次...", flush=True)
                self.csrf = ""
                continue
            break
        return data, ""

    def claim_and_verify(self) -> str:
        """领取并以重查任务状态（Status=2）为准。"""
        data, err = self._post_claim()
        if err:
            return f"签到失败: {err}"
        code, msg = self._code(data), self._msg(data)
        if code == CODE_CAPTCHA:
            return "签到失败: 触发滑块验证码，请到网页端手动签到一次后恢复自动"
        if self._login_expired(data):
            return "Cookie 已失效，请重新复制更新 RAINYUN_COOKIE"
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
        return f"签到失败: {msg or code or '提交后任务状态未变为已完成'}"

    # ---------- 主流程 ----------
    def run(self) -> str:
        if err := self.refresh_csrf():
            return f"初始化失败: {err}（Cookie 可能已失效，请重新复制更新 RAINYUN_COOKIE）"
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
        claimable = [t for t in tasks if str(t.get("Status")) == "1" and t.get("Name") != DAILY_TASK]
        if claimable:
            names = "、".join(f"{t.get('Name')}({t.get('Points')}分)" for t in claimable[:6])
            lines.append(f"还有可领取的积分任务: {names}（网页端「赚取积分」页手动领取）")
        return "\n".join(lines)


def split_cookies(raw: str) -> list:
    """cookie 用 & 或换行分隔（cookie 内部本来就以 ; 分隔，不能再用它切多账号）。"""
    parts = [p.strip() for p in re.split(r"[&\n\r]+", raw or "") if p.strip() and "=" in p]
    seen, unique = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def load_numbered(base_name: str) -> list:
    """单变量多账号 + 编号轮询（断号后连续 3 个缺失停止扫描）。"""
    entries = split_cookies(os.getenv(base_name, ""))
    misses = 0
    for i in range(1, 100):
        var = split_cookies(os.getenv(f"{base_name}_{i}", ""))
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


def main():
    random_delay()
    cookies = load_numbered("RAINYUN_COOKIE")
    if not cookies:
        print("未配置环境变量：RAINYUN_COOKIE（获取方法见脚本头部注释或仓库 README）")
        sys.exit(1)
    fea = fetch_fea()
    print(f"共 {len(cookies)} 个账号", flush=True)
    results = []
    for i, cookie in enumerate(cookies, 1):
        account = Account(i, cookie, fea)
        header = f"===== 账号 {i} ====="
        print(header)
        try:
            msg = account.run()
        except Exception as e:  # noqa: BLE001 账号级失败隔离
            msg = f"执行异常: {e.__class__.__name__}: {e}"
        print(msg, "\n")
        if "已失效" in msg or "HTTP 4" in msg:
            msg += "\n（提示：重新复制 api.v2.rainyun.com 的 Cookie 更新环境变量）"
        results.append(f"{header}【{account.label}】\n{msg}")
        if i < len(cookies):
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
