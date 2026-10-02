# qlscript — 青龙面板脚本集

多个青龙面板脚本的汇集仓库，**支持订阅自动创建定时任务**。

> 📖 **[Cookie 获取详细教程（Wiki）](https://github.com/xvkong233/qlscript/wiki/Cookie%E8%8E%B7%E5%8F%96%E6%95%99%E7%A8%8B)** —— BDUSS/STOKEN 的获取、多账号、失效处理

## 脚本清单

| 脚本 | 任务名 | 默认定时 | 环境变量 |
|---|---|---|---|
| [baidu_netdisk.py](baidu_netdisk.py) | 百度网盘多合一签到 | `30 8 * * *` | `BAIDUWP_COOKIE` |

### 百度网盘多合一签到

基于 [Sitoi/dailycheckin](https://github.com/Sitoi/dailycheckin) 的 baiduwp 模块重写并增强，全部接口经真实抓包验证（2026-10）。

功能：**成长值签到 + 每日答题 + PC 客户端积分签到 + 任务中心签到 + 自动补签**（漏签最近优先：每月 5 张 SVIP 无门槛卡优先，金币足够自动补，做任务类跳过并提示）+ 会员信息查询。多账号支持（cookie 用 `&` 或换行分隔）。

**环境变量 `BAIDUWP_COOKIE`**：`BDUSS=xxx; STOKEN=xxx`

多账号两种写法（可混用，按顺序执行）：
- 单变量内分隔：`BAIDUWP_COOKIE` 的值里用 `&` 或换行分隔多份
- 编号轮询：`BAIDUWP_COOKIE`、`BAIDUWP_COOKIE_1`、`BAIDUWP_COOKIE_2` …… 每个变量一个账号（编号连续即可，个别跳号也能识别；某个账号失效不影响其余账号）

获取：浏览器登录 [pan.baidu.com](https://pan.baidu.com) → F12 → Application → Cookies → 复制 `BDUSS` 和 `STOKEN`。

> STOKEN 说明：成长值/答题/PC 积分三个通道仅凭 BDUSS 即可运行；任务中心签到与补签需要 STOKEN。STOKEN 失效时推送会提示"任务中心签到失败: STOKEN 已失效，请更新配置中的完整 cookie"，其余功能不受影响，重新取一次 cookie 更新环境变量即可（频率约为月级）。

## 订阅拉库（自动创建定时任务）

青龙面板 → 订阅管理 → 创建订阅：

| 字段 | 填写 |
|---|---|
| 类型 | GitHub 仓库 |
| 链接 | `https://github.com/xvkong233/qlscript.git` |
| 分支 | `main` |
| 定时规则 | `0 * * * *`（更新订阅的频率，与脚本任务定时无关） |
| 自动创建任务 | 开启 |

每个脚本头部的 `new Env('任务名')` 和 `cron: ...` 注释会被青龙自动识别为任务名和定时规则，之后往本仓库新增脚本、订阅更新后会自动新建对应任务。

**依赖安装**：青龙 → 依赖管理 → Python3 → 创建依赖 → 自动拆分填 `requests`。

## 已知不可自动化的任务

百度网盘任务中心的"观看广告视频"（依赖穿山甲广告 SDK 服务端验证回调）和第三方 App 推广任务（依赖对应 App 真实启动回传）**无法协议化**，已实测：该 App 原生层有证书锁定，无法通过中间人观察或伪造完成上报。这部分收益（约 200 积分/天）需要真实设备行为。

## 致谢

- [Sitoi/dailycheckin](https://github.com/Sitoi/dailycheckin)（MIT）：原始 baiduwp 模块与整体框架
- [whyour/qinglong](https://github.com/whyour/qinglong)：青龙面板

