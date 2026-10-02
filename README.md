# qlscript — 青龙面板脚本集

多个青龙面板脚本的汇集仓库，**支持订阅自动创建定时任务**。

> 📖 **[Cookie 获取详细教程（Wiki）](https://github.com/xvkong233/qlscript/wiki/Cookie%E8%8E%B7%E5%8F%96%E6%95%99%E7%A8%8B)** —— BDUSS/STOKEN 的获取、多账号、失效处理

## 脚本清单

| 脚本 | 任务名 | 默认定时 | 环境变量 |
|---|---|---|---|
| [baidu_netdisk.py](baidu_netdisk.py) | 百度网盘多合一签到 | `30 8 * * *` | `BAIDUWP_COOKIE` |
| [wzyd.py](wzyd.py) | 王者营地签到 | `40 8 * * *` | `WZYD_TOKEN`、`WZYD_BODY`、`WZYD_WXQ_BODY` |

### 百度网盘多合一签到

基于 [Sitoi/dailycheckin](https://github.com/Sitoi/dailycheckin) 的 baiduwp 模块重写并增强，全部接口经真实抓包验证（2026-10）。

功能：**成长值签到 + 每日答题 + PC 客户端积分签到 + 任务中心签到 + 自动补签**（漏签最近优先：每月 5 张 SVIP 无门槛卡优先，金币足够自动补，做任务类跳过并提示）+ 会员信息查询。多账号支持（cookie 用 `&` 或换行分隔）。

**环境变量 `BAIDUWP_COOKIE`**：`BDUSS=xxx; STOKEN=xxx`

多账号两种写法（可混用，按顺序执行）：
- 单变量内分隔：`BAIDUWP_COOKIE` 的值里用 `&` 或换行分隔多份
- 编号轮询：`BAIDUWP_COOKIE`、`BAIDUWP_COOKIE_1`、`BAIDUWP_COOKIE_2` …… 每个变量一个账号（编号连续即可，个别跳号也能识别；某个账号失效不影响其余账号）

可选环境变量 `BAIDUWP_DELAY`：每日随机延迟上限（分钟），默认 10——脚本启动后随机等待 0~10 分钟再执行，让每天实际签到时间不同（今天 8:31、明天 8:36 这样）；设为 `0` 关闭（手动调试用）。多账号之间也会随机间隔 3~15 秒。

获取：浏览器登录 [pan.baidu.com](https://pan.baidu.com) → F12 → Application → Cookies → 复制 `BDUSS` 和 `STOKEN`。

> STOKEN 说明：成长值/答题/PC 积分三个通道仅凭 BDUSS 即可运行；任务中心签到与补签需要 STOKEN。STOKEN 失效时推送会提示"任务中心签到失败: STOKEN 已失效，请更新配置中的完整 cookie"，其余功能不受影响，重新取一次 cookie 更新环境变量即可（频率约为月级）。

**任务中心设备说明**：任务中心签到接口要求"已注册设备"且存在换号风控（`dev repeat`）。脚本为每个账号生成**固定设备标识**（由 cookie 哈希派生，不随运行变化）；当服务端对新设备收紧时自动回退到共享注册设备。推送中出现"设备校验中(dev repeat)，下次运行自动重试"属正常现象，多账号会按天轮换完成签到。

### 王者营地签到（王者 + 万象棋双渠道）

重放抓包参数完成营地「福利中心-每日签到」，支持**王者荣耀**（gameId 20001）和**王者万象棋**（gameId 30001）两个渠道，多账号。接口经真实抓包验证（2026-10，营地 App 10.114.0916）：`POST kohcamp.qq.com/operation/action/newsignin`，请求体由请求头里的 `gameId` / `campRoleId` 自动构造。

**环境变量**：

| 变量 | 必填 | 说明 |
|---|---|---|
| `WZYD_TOKEN` | ✅ | 王者频道鉴权：福利中心**任意一个** `kohcamp.qq.com` 请求的完整请求头，存成 JSON |
| `WZYD_WXQ_TOKEN` |  | 万象棋频道鉴权：在「王者万象棋」页签的福利中心里抓一个 kohcamp 请求头。不配置则只签王者 |
| `WZYD_BODY` / `WZYD_WXQ_BODY` |  | 可选，签到请求体原样 JSON（默认从请求头自动推导，一般不用配） |
| `WZYD_DELAY` |  | 每日随机延迟上限（分钟），默认 10，`0` 关闭 |

多账号：值内用 `;` 或换行分隔（JSON 值里带分号也没关系，脚本按花括号配对解析）；也支持编号轮询 `WZYD_TOKEN_1`、`WZYD_TOKEN_2` …… 两频道编号一一对应。

**抓包方法**（抓包工具过滤 `kohcamp.qq.com`，如 Stream / Charles / Reqable / mitmproxy）：

1. 王者营地 App → 底部「游戏」页签 → 点「王者荣耀」图标 → 「签到」进入福利中心
2. 随便点开列表里任一 `kohcamp.qq.com` 请求，**复制全部请求头**，原样存成 JSON 填入 `WZYD_TOKEN`（请求头里已带 `gameId:20001` 和 `campRoleId`，脚本据此构造签到请求）
3. 万象棋：回到「游戏」页签 → 点「王者万象棋」图标 → 「每日福利」进入其福利中心，同样抓一个 kohcamp 请求头填 `WZYD_WXQ_TOKEN`

示例（请求头长这样，字段较全，直接整体粘贴即可）：

```json
{"h5Get":"1","serverId":"1285","userId":"…","openid":"…","algorithm":"v2","msdkEncodeParam":"…","campRoleId":"…","sig":"…","encode":"2","roleId":"…","source":"smoba_zhushou","User-Agent":"Mozilla/5.0 …;GameHelper; …","noencrypt":"1","timestamp":"…","cClientVersionName":"10.114.0916","gameId":"20001","cSystem":"android","gameOpenid":"…","appid":"1105200115","token":"…","version":"3.1.96a"}
```

**返回码**（实测）：`returnCode 0`=签到成功；`-105203`=今日已签到；`-105206`=操作频繁（脚本自动等 60s 重试一次）；提示登录失效时重新抓包更新环境变量即可（签到态跟随 App 会话，通常数周至数月一换）。

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

