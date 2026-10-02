"""
new Env('王者营地签到')

cron: 40 8 * * *

王者营地每日签到（青龙订阅版）

功能：王者荣耀 + 王者万象棋 双渠道每日签到，多账号。

原理：营地签到接口只认「抓包参数」本身，脚本不做任何加解密——
     把抓到的请求头/请求体原样重放即可，参数由用户自行抓包获取。

环境变量：
  WZYD_TOKEN        账号鉴权参数（必填），两种格式按内容自动识别：
                      ① H5/MSDK 参数 JSON（营地 App「签到」H5 页抓包，含
                         msdkEncodeParam/sig/openid 等字段）→ 走 /operation/action/signin
                      ② userid&token（App 原生签到接口抓包，可带第三段 camproleid）
                         → 走 /operation/action/newsignin
                    多账号用 ; 或换行分隔；也支持编号轮询
                    WZYD_TOKEN、WZYD_TOKEN_1、WZYD_TOKEN_2、...（与 ① 格式混用亦可）

  WZYD_BODY         王者荣耀签到请求体（抓包原样 JSON，含 roleId），必填。
  WZYD_WXQ_BODY     王者万象棋签到请求体（抓包原样 JSON），可选——
                    未配置时只签王者荣耀。万象棋角色与王者角色不同，需单独抓包。
  WZYD_WXQ_TOKEN    万象棋专用鉴权参数（可选，格式同 WZYD_TOKEN；默认复用对应账号的 WZYD_TOKEN）。
                    多账号分隔/编号规则与 WZYD_TOKEN 相同。

  BODY/TOKEN 的多账号分隔符均为 ; 或换行（不要用 & —— userid&token 格式里
  & 是字段分隔符），并按顺序与账号一一配对。

  WZYD_DELAY    每日随机延迟上限（分钟），默认 10：脚本启动后随机等待 0~10 分钟
                再执行，使每天实际签到时间不同；设为 0 关闭（手动调试用）。

抓包方法：抓包工具（Stream/Charles/Reqable 等）过滤 kohcamp.qq.com，
     打开王者营地 App → 营地福利 → 游戏签到，分别在「王者荣耀」「王者万象棋」
     页签点一次签到，取两次 POST 请求：
       - 请求体 JSON → 填 WZYD_BODY / WZYD_WXQ_BODY
       - 鉴权：H5 抓包取请求头中 appid/openid/msdkEncodeParam/sig/userId/source/
         encode/timestamp/algorithm/version 组成 JSON 填 WZYD_TOKEN；
         若抓到的是 userid/token 两个请求头，则按 userid&token 填写。

返回值识别：营地接口统一 returnCode（0=成功）+ returnMsg；
     登录失效特征是 returnMsg 提示登录/token，重新抓一次参数更新环境变量即可。

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
# 两种签到通道：按鉴权参数格式自动选择（H5/MSDK 参数 vs App 原生 userid&token）
SIGN_H5_URL = "https://kohcamp.qq.com/operation/action/signin"
SIGN_NATIVE_URL = "https://kohcamp.qq.com/operation/action/newsignin"
UA_H5 = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Mobile/15E148 Safari/604.1")
UA_NATIVE = "okhttp/4.9.1"

CHANNEL_MAIN = "王者荣耀"
CHANNEL_WXQ = "王者万象棋"


class Account:
    """一个营地账号：鉴权参数 + 各渠道签到请求体（均为抓包原文）。"""

    def __init__(self, index: int, token_raw: str, main_body_raw: str,
                 wxq_body_raw: str = "", wxq_token_raw: str = ""):
        self.index = index
        self.token_raw = token_raw.strip()
        self.main_body_raw = main_body_raw.strip()
        self.wxq_body_raw = wxq_body_raw.strip()
        self.wxq_token_raw = wxq_token_raw.strip()
        self._style = None
        self._headers = None

    @property
    def label(self) -> str:
        try:
            role = json.loads(self.main_body_raw).get("roleId")
            if role:
                return str(role)
        except (ValueError, AttributeError):
            pass
        return f"账号{self.index}"

    # ---------- 鉴权 ----------
    def _auth(self, token_raw: str):
        """返回 (style, headers)。style 决定走 H5 signin 还是原生 newsignin。"""
        raw = (token_raw or self.token_raw).strip()
        if raw.startswith("{"):
            # 参考格式里 encode 可能是数字（"encode": 2），requests 要求请求头必须是字符串
            return "msdk", {k: v if isinstance(v, str) else json.dumps(v)
                            for k, v in json.loads(raw).items()}
        parts = [p.strip() for p in raw.split("&") if p.strip()]
        if len(parts) >= 2:
            return "native", {"userid": parts[0], "token": parts[1]}
        raise ValueError(
            "WZYD_TOKEN 格式无法识别：应为 MSDK 参数 JSON（{ 开头）或 userid&token")

    def sign(self, body_raw: str, token_raw: str = "", channel: str = "") -> str:
        """重放一个渠道的签到请求，返回人话结果。"""
        style, auth_headers = self._auth(token_raw)
        try:
            payload = json.loads(body_raw)
        except ValueError as e:
            return f"签到失败: 请求体不是合法 JSON（{e}）"
        headers = {"User-Agent": UA_H5 if style == "msdk" else UA_NATIVE,
                   "Content-Type": "application/json"}
        headers.update(auth_headers)
        url = SIGN_H5_URL if style == "msdk" else SIGN_NATIVE_URL
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            return f"签到失败: 网络异常 {e.__class__.__name__}: {e}"
        if resp.status_code != 200:
            return f"签到失败: HTTP {resp.status_code}"
        try:
            data = resp.json()
        except ValueError:
            return "签到失败: 响应非 JSON（接口可能已变更或参数失效）"
        print(f"  [{channel}] 响应: {json.dumps(data, ensure_ascii=False)[:300]}", flush=True)
        return parse_result(data)

    # ---------- 主流程 ----------
    def run(self) -> str:
        lines = []
        for channel, body_raw, token_raw in (
            (CHANNEL_MAIN, self.main_body_raw, ""),
            (CHANNEL_WXQ, self.wxq_body_raw, self.wxq_token_raw),
        ):
            if not body_raw:
                if channel == CHANNEL_WXQ:
                    lines.append(f"{channel}: 未配置 WZYD_WXQ_BODY，跳过")
                continue
            try:
                result = self.sign(body_raw, token_raw, channel)
            except ValueError as e:  # token 格式/JSON 解析错误
                result = f"签到失败: {e}"
            lines.append(f"{channel}: {result}")
        return "\n".join(lines)


def parse_result(data: dict) -> str:
    """把营地统一返回 {returnCode, returnMsg} 翻译成人话。"""
    code = data.get("returnCode", data.get("code", data.get("ret")))
    msg = str(data.get("returnMsg") or data.get("msg") or data.get("message") or "")
    if any(word in msg for word in ("已签到", "重复", "already")):
        return "今日已签到" if "已签到" in msg else f"今日已签到（{msg}）"
    if code == 0 or (isinstance(code, str) and code in ("0", "200", "true", "success")):
        return "签到成功"
    if code is None and not msg:
        return f"签到失败: 无法识别的响应 {json.dumps(data, ensure_ascii=False)[:120]}"
    if any(word in msg for word in ("登录", "失效", "token", "Token", "登录态")):
        return f"签到失败: {msg or code}（鉴权参数已失效，请重新抓包更新环境变量）"
    return f"签到失败: {msg or code}"


def split_entries(raw: str) -> list:
    """多账号切分：; 或换行（& 保留给 userid&token 格式当字段分隔符）。"""
    return [p.strip() for p in re.split(r"[;\n\r]+", raw or "") if p.strip()]


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
    """按顺序把 token 与两个渠道的 body 一一配对；数量不一致时直接报错并说明格式。"""
    tokens = load_numbered("WZYD_TOKEN")
    wxq_tokens = load_numbered("WZYD_WXQ_TOKEN")
    main_bodies = load_numbered("WZYD_BODY")
    wxq_bodies = load_numbered("WZYD_WXQ_BODY")
    if not tokens:
        return []
    if len(main_bodies) != len(tokens):
        raise SystemExit(
            f"环境变量配置不匹配：WZYD_TOKEN 有 {len(tokens)} 个账号，"
            f"WZYD_BODY 有 {len(main_bodies)} 个请求体。\n"
            "两者需按顺序一一对应，多账号用 ; 或换行分隔（示例见脚本头部注释）。\n"
            "注意：WZYD_WXQ_BODY（万象棋）是独立变量，不要把它的内容混进 WZYD_BODY。")
    accounts = []
    for i, (token, body) in enumerate(zip(tokens, main_bodies)):
        accounts.append(Account(i + 1, token, body,
                                wxq_bodies[i] if i < len(wxq_bodies) else "",
                                wxq_tokens[i] if i < len(wxq_tokens) else ""))
    if wxq_bodies and len(wxq_bodies) != len(tokens):
        print(f"警告：WZYD_WXQ_BODY 有 {len(wxq_bodies)} 个，与账号数 {len(tokens)} 不一致，"
              f"仅前 {min(len(wxq_bodies), len(tokens))} 个账号会签万象棋", flush=True)
    if wxq_tokens and len(wxq_tokens) != len(tokens):
        print(f"警告：WZYD_WXQ_TOKEN 有 {len(wxq_tokens)} 个，与账号数 {len(tokens)} 不一致，"
              f"多余部分忽略，缺失的账号复用 WZYD_TOKEN", flush=True)
    return accounts


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
        print("未配置环境变量：WZYD_TOKEN / WZYD_BODY（抓包方法见脚本头部注释）")
        sys.exit(1)
    print(f"共 {len(accounts)} 个账号", flush=True)
    results = []
    for i, account in enumerate(accounts, 1):
        header = f"===== 账号 {i} 【{account.label}】====="
        print(header)
        try:
            msg = account.run()
        except json.JSONDecodeError as e:
            msg = f"执行异常: 鉴权参数 JSON 不合法（{e}）"
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
