# 百度网盘多合一每日签到（青龙面板版）

基于 [Sitoi/dailycheckin](https://github.com/Sitoi/dailycheckin) 的 baiduwp 模块重写并增强，全部接口经真实抓包验证（2026-10）。原模块使用正则解析、无状态预检、失败时会泄露 cookie，本版全部修复并新增三个通道。

## 功能

| 功能 | 接口通道 | 说明 |
|---|---|---|
| 会员成长值签到 | `membership/level` (H5) | 先查状态再签到，幂等 |
| 每日答题 | `membergrowv2` | 题目接口直接下发答案，自动作答 |
| PC 客户端积分签到 | `coins/pc/signin` | 每日 +5~8 积分，仅 BDUSS 即可 |
| 任务中心签到 | `coins/taskcenter/signin` | 新版 App 通道，需 BDUSS+STOKEN |
| **自动补签** | `supptasklist` / `suppsignin` | 漏签按**最近优先**自动补：每月 5 张 SVIP 无门槛卡优先，金币足够自动补，做任务类跳过并提示 |
| 会员信息查询 | `membership/user` | 等级 + 成长值 |

多账号：cookie 用 `&` 或换行分隔，逐账号执行。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `BAIDUWP_COOKIE` | ✅ | `BDUSS=xxx; STOKEN=xxx`，多账号用 `&` 或换行分隔 |

**获取 cookie**：浏览器登录 [pan.baidu.com](https://pan.baidu.com) → F12 → Application → Cookies → 复制 `BDUSS` 和 `STOKEN`。

> STOKEN 说明：成长值/答题/PC 积分三个通道仅凭 BDUSS 即可运行；任务中心签到与补签需要 STOKEN。STOKEN 失效时推送会提示"任务中心签到失败: STOKEN 已失效，请更新配置中的完整 cookie"，其余功能不受影响，重新取一次 cookie 更新环境变量即可（频率约为月级）。

## 青龙部署

```
拉库: 本仓库
定时: 30 8 * * *
命令: python3 baidu_netdisk.py
依赖: requests
```

通知自动对接青龙自带 `notify.py`（存在即推送，缺省只打印日志）。

## 已知不可自动化的任务

任务中心的"观看广告视频"（依赖穿山甲广告 SDK 服务端验证回调）和第三方 App 推广任务（依赖对应 App 真实启动回传）**无法协议化**，已实测：该 App 原生层有证书锁定，无法通过中间人观察或伪造完成上报。这部分收益（约 200 积分/天）需要真实设备行为。

## 致谢

- [Sitoi/dailycheckin](https://github.com/Sitoi/dailycheckin)（MIT）：原始 baiduwp 模块与整体框架
