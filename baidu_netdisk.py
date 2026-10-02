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

  获取方式见仓库 Wiki「Cookie 获取教程」。
  STOKEN 失效特征：推送中出现"任务中心签到失败: STOKEN 已失效"，
            其余功能不受影响，届时重新取一次 cookie 更新环境变量即可。

依赖：requests（青龙 依赖管理 -> Python3 -> 安装 requests）
"""

import hashlib
import json
import os
import re
import sys
import time

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
# 任务中心 signin 仅接受「已注册」设备（新设备报 param error，且注册需真实 App 流程），
# 故签到共用这一个已注册设备；多账号先后签到时若触发 dev repeat（设备换号风控）会自动重试
REGISTERED_DEVICE = "5ACF9C71D2E84B0FA6C8D2E91F3A7B55|dailycheckin"
# 补签方式: 1=SVIP 无门槛卡(每月5张) 2=做任务 3=金币


class BaiduPan:
    def __init__(self, cookie: str):
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
        # 任务中心把「设备+账号」按天绑定（共用设备会报 dev repeat），
        # 因此从 cookie 派生每账号独立且稳定的设备标识（同一账号每天同一设备）
        digest = hashlib.md5(cookie.encode("utf-8")).hexdigest().upper()
        device = f"{digest}|{digest[:8]}"
        self.task_base = {
            **TASK_BASE,
            "cuid": device,
            "devuid": device,
        }

    def _api_get(self, path: str, extra_params: dict, headers: dict = None) -> dict:
        params = dict(QUERY_PARAMS)
        params.update(extra_params)
        resp = self.session.get(API_BASE + path, params=params,
                                headers=headers, timeout=TIMEOUT)
        if resp.status_code != 200:
            raise RuntimeError(f"{path} 请求失败 HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError:
            raise RuntimeError(f"{path} 响应非 JSON（cookie 可能已失效）")

    def _pc_api(self, path: str, params: dict) -> dict:
        resp = self.session.get(API_BASE + path, params=params,
                                headers=PC_HEADERS, timeout=TIMEOUT)
        if resp.status_code != 200:
            raise RuntimeError(f"{path} 请求失败 HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError:
            raise RuntimeError(f"{path} 响应非 JSON（cookie 可能已失效）")

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

    def taskcenter_signin(self) -> str:
        # 每账号固定设备（cookie 哈希派生，不随运行变化）优先；
        # 服务端偶发对新设备收紧(param error)时，回退到共享已注册设备保签到成功。
        # dev repeat 为设备换号临时风控，等待后重试。
        data, last_error = {}, ""
        for device in (self.task_base["cuid"], REGISTERED_DEVICE):
            for attempt in range(3):
                try:
                    data = self._taskcenter_signin_once(device)
                except RuntimeError as e:
                    last_error = str(e)
                    data = {"errno": -1, "error": last_error}
                    break
                last_error = data.get("error") or ""
                if data.get("errno") == 0 or "dev repeat" not in last_error:
                    break
                time.sleep(30 * (attempt + 1))
            if data.get("errno") == 0:
                return f"任务中心签到完成，累计 {(data.get('data') or {}).get('signin_days')} 天"
            if "bduss" in last_error.lower():
                return "任务中心签到失败: STOKEN 已失效，请更新配置中的完整 cookie"
            if "dev repeat" in last_error:
                return "任务中心签到: 设备校验中(dev repeat)，下次运行自动重试"
        if "param error" in last_error:
            return "任务中心签到失败: 设备未注册(param error)，下次运行自动重试"
        return f"任务中心签到失败: {last_error or '未知错误'}"

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


def main():
    cookies = load_cookies()
    if not cookies:
        print("未配置 cookie 环境变量：BAIDUWP_COOKIE（或 BAIDUWP_COOKIE_1、_2 ...）")
        sys.exit(1)
    results = []
    for i, cookie in enumerate(cookies, 1):
        panel = BaiduPan(cookie)
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
            time.sleep(3)
    # 青龙通知（存在 notify.py 则推送）
    try:
        from notify import send  # type: ignore
        send("百度网盘签到", "\n\n".join(results))
    except Exception:
        pass


if __name__ == "__main__":
    main()
