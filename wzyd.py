"""
new Env('王者营地签到')

cron: 40 8 * * *

王者营地每日签到（青龙订阅版）

功能：王者荣耀 + 王者万象棋 双渠道每日签到，多账号。
     接口与参数均经真实抓包验证（2026-10，营地 App 10.114.0916 / H5 version 3.1.96a）：
     POST https://kohcamp.qq.com/operation/action/newsignin
     body: {"gameId":"20001"(王者)/"30001"(万象棋), "roleId":"<营地角色ID campRoleId>"}

环境变量：
  WZYD_TOKEN        王者频道鉴权参数（必填）：抓包王者营地「福利中心」任意一个
                    kohcamp.qq.com 请求的完整请求头，原样存成 JSON。
                    脚本直接用头里的 gameId/campRoleId 字段自动构造签到请求体，
                    因此通常不需要再配 WZYD_BODY。
  WZYD_BODY         王者频道签到请求体（可选，抓包原样 JSON；配置后原样重放）。
  WZYD_WXQ_TOKEN    万象棋频道鉴权参数（可选）：在「王者万象棋」页签的福利中心里
                    随便抓一个 kohcamp 请求的完整请求头。未配置时只签王者。
  WZYD_WXQ_BODY     万象棋签到请求体（可选，同上）。

  多账号：值内用 ; 或换行分隔多份，也支持编号轮询
                    WZYD_TOKEN、WZYD_TOKEN_1、...（两个频道各自编号一一对应）。
                    注意不要用 & 分隔——它是 userid&token 格式的字段分隔符。

  兼容两种鉴权格式（按内容自动识别）：
    ① 福利中心 H5 的完整请求头 JSON（推荐，含 appid/openid/msdkEncodeParam/sig/
       userId/token/campRoleId/gameId 等，字段齐全时签到体可全自动构造）
    ② userid&token（App 原生抓包，第三段 camproleid 可带）——此格式下
       签到体无法从请求头推导，需同时配置对应的 WZYD_BODY。

  WZYD_DELAY    每日随机延迟上限（分钟），默认 10：脚本启动后随机等待 0~10 分钟
                再执行，使每天实际签到时间不同；设为 0 关闭（手动调试用）。

抓包方法（详见仓库 README）：
  抓包工具过滤 kohcamp.qq.com → 王者营地 App → 「游戏」页签 → 对应游戏图标
  → 「签到/每日福利」进入福利中心 → 随便点开一个请求复制全部请求头。

返回值（实测）：returnCode 0=成功；-105203=今日已签；-105206=操作频繁（自动重试）；
     登录态失效时提示重新抓包更新环境变量（签到态跟随 App 会话，通常数周至数月一换）。

依赖：requests（青龙 依赖管理 -> Python3 -> 安装 requests）
"""

import json
import os
import random
import re
import sys
import time

import requests

TIMEOUT = 15
SIGN_URL = "https://kohcamp.qq.com/operation/action/newsignin"
UA_DEFAULT = "okhttp/4.9.1"
# 每个游戏频道在营地里的 gameId（请求头缺失时兜底，实测 2026-10）
GAME_ID_MAIN = "20001"   # 王者荣耀
GAME_ID_WXQ = "30001"    # 王者万象棋

CHANNEL_MAIN = "王者荣耀"
CHANNEL_WXQ = "王者万象棋"

# 重放时剔除与代理/浏览器相关的头，只留业务与鉴权头
DROP_HEADERS = {
    "host", "connection", "content-length", "content-type", "accept",
    "accept-encoding", "accept-language", "origin", "referer", "cookie",
    "user-agent", "x-requested-with", "sec-fetch-site", "sec-fetch-mode",
    "sec-fetch-dest", "traceparent", "x-log-uid", "x-client-proto",
    "accept-encrypt", "x-surge-skip-scripting",
}


class Account:
    """一个营地账号：各渠道一份「福利中心请求头」（抓包原文），签到体自动推导。"""

    def __init__(self, index: int, main_token: str, wxq_token: str = "",
                 main_body: str = "", wxq_body: str = ""):
        self.index = index
        self.main_token = main_token.strip()
        self.wxq_token = wxq_token.strip()
        self.main_body = main_body.strip()
        self.wxq_body = wxq_body.strip()

    @property
    def label(self) -> str:
        for raw in (self.main_token, self.wxq_token):
            if raw.startswith("{"):
                try:
                    h = json.loads(raw)
                    for key in ("campRoleId", "roleId", "userId"):
                        if h.get(key):
                            return str(h[key])
                except ValueError:
                    break
        raw = self.main_token or self.wxq_token
        if "&" in raw:
            return raw.split("&")[0]
        return f"账号{self.index}"

    # ---------- 鉴权 ----------
    @staticmethod
    def _auth(token_raw: str):
        """返回 (style, headers)。style: msdk=福利中心 H5 请求头 / native=userid&token。"""
        raw = token_raw.strip()
        if raw.startswith("{"):
            obj = json.loads(raw)
            headers = {k: v if isinstance(v, str) else json.dumps(v)
                       for k, v in obj.items() if k.lower() not in DROP_HEADERS}
            return "msdk", headers
        parts = [p.strip() for p in raw.split("&") if p.strip()]
        if len(parts) >= 2:
            return "native", {"userid": parts[0], "token": parts[1]}
        raise ValueError("WZYD_TOKEN 格式无法识别：应为福利中心请求头 JSON（{ 开头）或 userid&token")

    @staticmethod
    def _derive_body(headers: dict, style: str, default_game_id: str, body_raw: str) -> dict:
        """签到体：优先用户提供的原样 JSON；msdk 请求头里就有 gameId/campRoleId，可自动推导。"""
        if body_raw:
            return json.loads(body_raw)
        if style == "msdk":
            game_id = headers.get("gameId") or default_game_id
            role_id = headers.get("campRoleId") or headers.get("roleId") or ""
            if role_id:
                return {"gameId": str(game_id), "roleId": str(role_id)}
            raise ValueError("请求头里没有 campRoleId/roleId，无法构造签到体，请配置对应的 BODY 环境变量")
        raise ValueError("userid&token 格式需要同时配置对应的签到 BODY 环境变量（WZYD_BODY / WZYD_WXQ_BODY）")

    def sign(self, token_raw: str, body_raw: str, default_game_id: str, channel: str) -> str:
        style, headers = self._auth(token_raw)
        payload = self._derive_body(headers, style, default_game_id, body_raw)
        request_headers = {"User-Agent": UA_DEFAULT, "Content-Type": "application/json"}
        request_headers.update(headers)
        try:
            resp = requests.post(SIGN_URL, json=payload, headers=request_headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            return f"签到失败: 网络异常 {e.__class__.__name__}: {e}"
        if resp.status_code != 200:
            return f"签到失败: HTTP {resp.status_code}"
        try:
            data = resp.json()
        except ValueError:
            return "签到失败: 响应非 JSON（接口可能已变更或参数失效）"
        print(f"  [{channel}] gameId={payload.get('gameId')} 响应: {json.dumps(data, ensure_ascii=False)[:220]}",
              flush=True)
        code = data.get("returnCode")
        if code == -105206 or "频繁" in str(data.get("returnMsg", "")):
            print(f"  [{channel}] 触发频控，60s 后重试一次...", flush=True)
            time.sleep(60)
            resp = requests.post(SIGN_URL, json=payload, headers=request_headers, timeout=TIMEOUT)
            data = resp.json()
            print(f"  [{channel}] 重试响应: {json.dumps(data, ensure_ascii=False)[:220]}", flush=True)
        return parse_result(data)

    # ---------- 主流程 ----------
    def run(self) -> str:
        lines = []
        for channel, token_raw, body_raw, gid in (
            (CHANNEL_MAIN, self.main_token, self.main_body, GAME_ID_MAIN),
            (CHANNEL_WXQ, self.wxq_token, self.wxq_body, GAME_ID_WXQ),
        ):
            if not token_raw and not body_raw:
                if channel == CHANNEL_WXQ:
                    lines.append(f"{channel}: 未配置 WZYD_WXQ_TOKEN，跳过")
                continue
            token = token_raw or self.main_token  # 万象棋只配了 BODY 时复用王者请求头
            try:
                result = self.sign(token, body_raw, gid, channel)
            except ValueError as e:
                result = f"签到失败: {e}"
            except json.JSONDecodeError as e:
                result = f"签到失败: JSON 不合法（{e}）"
            lines.append(f"{channel}: {result}")
        return "\n".join(lines)


def parse_result(data: dict) -> str:
    """把营地统一返回 {returnCode, returnMsg} 翻译成人话（码值均为实测）。"""
    code = data.get("returnCode", data.get("code", data.get("ret")))
    msg = str(data.get("returnMsg") or data.get("msg") or data.get("message") or "")
    if code == -105203 or any(word in msg for word in ("重复签到", "已签到")):
        return "今日已签到"
    if code == 0 or (isinstance(code, str) and code in ("0", "200", "success")):
        return "签到成功"
    if code == -105206 or "频繁" in msg:
        return f"签到失败: 操作频繁（{msg or code}），下次运行再试"
    if code is None and not msg:
        return f"签到失败: 无法识别的响应 {json.dumps(data, ensure_ascii=False)[:120]}"
    if any(word in msg for word in ("登录", "失效", "token", "Token")):
        return f"签到失败: {msg or code}（鉴权参数已失效，请重新抓包更新环境变量）"
    return f"签到失败: {msg or code}"


def split_entries(raw: str) -> list:
    """多账号切分。JSON 对象按花括号配对整体提取（请求头 JSON 的值里可能含
    分号——如 User-Agent「...;GameHelper;」——不能按 ; 盲切），
    JSON 之外的非空片段视为 userid&token 格式，按 ; 或换行分隔。"""
    raw = raw or ""
    entries, buf, depth, in_str, esc, started = [], [], 0, False, False, False
    for ch in raw:
        if depth:
            buf.append(ch)
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    entries.append("".join(buf).strip())
                    buf = []
        elif ch == "{":
            if started and buf:
                entries.extend(_split_plain("".join(buf)))
            buf, depth, in_str, esc, started = [ch], 1, False, False, True
        else:
            buf.append(ch)
    if buf:
        tail = "".join(buf)
        if started and depth:  # 括号不完整的残片，原样保留便于报错
            entries.append(tail.strip())
        else:
            entries.extend(_split_plain(tail))
    seen, unique = set(), []
    for e in entries:
        if e and e not in seen:
            seen.add(e)
            unique.append(e)
    return unique


def _split_plain(text: str) -> list:
    return [p.strip() for p in re.split(r"[;\n\r]+", text) if p.strip()]


def load_numbered(base_name: str) -> list:
    """读环境变量，支持单变量多账号 + 编号轮询（断号后连续 3 个缺失停止扫描）。"""
    entries = split_entries(os.getenv(base_name, ""))
    misses = 0
    for i in range(1, 100):
        var = split_entries(os.getenv(f"{base_name}_{i}", ""))
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


def build_accounts() -> list:
    """把王者/万象棋两个频道的鉴权参数按顺序配对成账号。"""
    tokens = load_numbered("WZYD_TOKEN")
    wxq_tokens = load_numbered("WZYD_WXQ_TOKEN")
    bodies = load_numbered("WZYD_BODY")
    wxq_bodies = load_numbered("WZYD_WXQ_BODY")
    if not tokens and wxq_tokens:
        tokens = wxq_tokens  # 只签万象棋的极端用法：以万象棋配置为准
    if not tokens:
        return []
    n = len(tokens)
    for name, vals in (("WZYD_WXQ_TOKEN", wxq_tokens), ("WZYD_BODY", bodies), ("WZYD_WXQ_BODY", wxq_bodies)):
        if vals and len(vals) != n:
            print(f"警告：{name} 有 {len(vals)} 个，与账号数 {n} 不一致，仅前 {min(len(vals), n)} 个生效", flush=True)
    return [Account(i + 1,
                    tokens[i],
                    wxq_tokens[i] if i < len(wxq_tokens) else "",
                    bodies[i] if i < len(bodies) else "",
                    wxq_bodies[i] if i < len(wxq_bodies) else "")
            for i in range(n)]


def random_delay():
    """启动随机延迟（默认 0~10 分钟），让每天实际执行时间有差异。"""
    max_minutes = 10
    raw = os.getenv("WZYD_DELAY", "").strip()
    if raw.isdigit():
        max_minutes = int(raw)
    if max_minutes <= 0:
        return
    seconds = random.randint(0, max_minutes * 60)
    print(f"随机延迟 {seconds // 60} 分 {seconds % 60} 秒后开始（WZYD_DELAY={max_minutes} 分钟内随机）...",
          flush=True)
    time.sleep(seconds)


def main():
    random_delay()
    accounts = build_accounts()
    if not accounts:
        print("未配置环境变量：WZYD_TOKEN（抓包方法见脚本头部注释或仓库 README）")
        sys.exit(1)
    print(f"共 {len(accounts)} 个账号", flush=True)
    results = []
    for i, account in enumerate(accounts, 1):
        header = f"===== 账号 {i} 【{account.label}】====="
        print(header)
        try:
            msg = account.run()
        except Exception as e:  # noqa: BLE001 账号级失败隔离
            msg = f"执行异常: {e.__class__.__name__}: {e}"
        print(msg, "\n")
        if "已失效" in msg or "HTTP 4" in msg:
            msg += "\n（提示：鉴权参数可能无效或已失效，请重新抓包核对对应的环境变量）"
        results.append(f"{header}\n{msg}")
        if i < len(accounts):
            gap = random.randint(3, 15)
            print(f"等待 {gap}s 后处理下一个账号...", flush=True)
            time.sleep(gap)
    try:
        from notify import send  # type: ignore
        send("王者营地签到", "\n\n".join(results))
    except Exception:
        pass


if __name__ == "__main__":
    main()
