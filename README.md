# qlscript — 青龙面板脚本集

多个青龙面板脚本的汇集仓库，**支持订阅自动创建定时任务**。

> 📖 **[Cookie 获取详细教程（Wiki）](https://github.com/xvkong233/qlscript/wiki/Cookie%E8%8E%B7%E5%8F%96%E6%95%99%E7%A8%8B)** —— BDUSS/STOKEN 的获取、多账号、失效处理

## 脚本清单

| 脚本 | 任务名 | 默认定时 | 环境变量 |
|---|---|---|---|
| [baidu_netdisk.py](baidu_netdisk.py) | 百度网盘多合一签到 | `30 8 * * *` | `BAIDUWP_COOKIE` |
| [wzyd.py](wzyd.py) | 王者营地签到 | `40 8 * * *` | `WZYD_TOKEN`、`WZYD_BODY`、`WZYD_WXQ_BODY` |
| [rainyun.py](rainyun.py) | 雨云积分签到 | `50 8 * * *` | `RAINYUN_API_KEY` 或 `RAINYUN_COOKIE` |
| [svyun.py](svyun.py) | 速维云签到 | `10 9 * * *` | `SVYUN_ACCOUNT` |

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

**任务中心签到通道说明（2026-10 真机抓包 + 2026-10-27 实跑修正）**：金币乐园（points-center）已下线，签到迁移到**任务系统 H5**（`/operation/activitys/taskSystem/main`）。页面打开时会自动调用 `/coins/taskcenter/signin`，**必须带完整客户端参数**：`z`（sofire 设备指纹）、`channel`（分发渠道）、`cuid/devuid`、`version/versioncode`、`offlinepackage`、`themeinfo`、`rchannel`、`task_id/task_from`、`is_growth=0`。缺 `z/channel/offlinepackage` 时，未签到账号会得到 `errno=2 param error`（已签日服务端会短路返回，看不出缺参数）。脚本已按这条真实链路执行，points-center 的 `signinv2/center` 仅作旧账号回退。三项客户端参数可用 `BAIDUWP_Z` / `BAIDUWP_CHANNEL` / `BAIDUWP_UA` 覆盖，多账号可用 `BAIDUWP_Z_n` / `BAIDUWP_CHANNEL_n` 给第 n 个账号单独指定（默认值是 MuMu Android 15 + App 13.34.3 的抓包值；换设备后建议用自己的抓包值）。设备标识仍会冻结复用（`BAIDUWP_DEVICE_n` / `BAIDUWP_DEVICE_POOL`），用于 `9312/8001` 这类账号/设备风控的降级；历史上把 `errno=2` 解读成「设备未登记」的结论已被推翻。

> **`z` 不能借给别人用（2026-10-27 三账号实跑结论）**：同一份 `z/channel/offlinepackage/version`，只有抓包账号能过参数校验（得到业务错误 `9230`），另两个账号一律 `errno=2`；拿内置设备去重试那两个账号，又变成 `9312 dev repeat`。所以 `z` 是按「设备 + 登录态」算出的指纹，不是可跨账号重放的静态参数。脚本现在的做法是：① 先试**不需要 z** 的网页端通道（`clienttype=5` + 服务端下发的 `MAWEBCUID`）；② 走 App 通道时，一旦发现这份 z 已属于另一个账号，后续运行对该账号直接熔断，不再每天白撞；③ 想真正走通，就给每个账号抓自己的 z：在已登录该账号的 App 上跑 `work/frida/get_clientinfo.py`，把输出的 `BAIDUWP_Z=<该账号的 z>` 填成 `BAIDUWP_Z_1` / `BAIDUWP_Z_2` ……（脚本启动日志会打印 `任务系统 z: 来源=...`，一眼能看出用的是谁的）。整条任务中心通道可用 `BAIDUWP_TASKCENTER=0` 关闭，网页端通道用 `BAIDUWP_TASKCENTER_WEB=0` 关闭。

**机型指纹（2026-10-27 APK 复核）**：客户端 `channel` 的构造是
`"android_" + Build.VERSION.RELEASE + "_" + Build.MODEL + "_bd-netdisk_1027840c"`
（`newhome/fr10.java` 里的 mars 公共参数 `Platform`，网盘本体后缀 `1027840c`），
WebView UA 里又带一遍 `Android <RELEASE>; <MODEL> Build/<Build.ID>`。所以脚本改成**机型画像驱动**：
`BAIDUWP_PROFILE` 默认 `xiaomi14`（Xiaomi 14 / `23127PN0CC` / HyperOS 1.0 / Android 14），
channel、WebView UA、网页 UA、REST UA 全部从同一份 Build 推导，开局会自查并在不自洽时告警
（"channel 写小米、UA 写 vivo"比用错机型更像伪造）。可选项：`xiaomi14-hyperos2`（同机 Android 15）、
`vivo-v2364a`（原抓包机，内置 z 的来源）。改画像只需一个变量，不要单独改 `BAIDUWP_CHANNEL`/`BAIDUWP_UA`。

**首次登录在云端建档（2026-10-27 APK 复核）**：设备号是**客户端生成**的（`CUID3StartupTask` → `DeviceId.getCUID()` → `PersonalConfig["deviceId"]`，服务端不下发设备号），App 把设备报给任务中心的唯一入口是 `PointCenterApi.checkDeviceUnique()` → `GET /coins/taskcenter/checkdevmp`（`CheckDeviceUniqueJob` 后台上报，只报不看）。所以脚本的做法是：**该账号第一次跑时本地生成一台新设备（`32位HEX|8位`）→ 用 `checkdevmp` 上报 → 结果落盘，之后一直用同一台**；已上报过就不再发请求。想换设备（一次性）：`BAIDUWP_DEVICE_ROTATE=1`，跑一次后删除（账号在服务端有设备上限，不能天天换）。注意：设备登记**不会**绕过 `signin` 的 `z` 门槛，它解决的是「每账号一台独立设备、不再共享 MuMu 设备吃 `dev repeat`」。登记状态存在 `.baidu_taskcenter_device.json` 的 `devices[<设备>].registration`，详见审计报告 §十三。

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

### 雨云积分签到

完成 [app.rainyun.com](https://app.rainyun.com/account/reward/earn)「积分中心 → 赚取积分 → 每日签到 + 自动领积分任务」，多账号。接口从雨云前端代码逆向确认（2026-10）：`POST api.v2.rainyun.com/user/reward/tasks`（`{"task_name":"每日签到"}`），签到结果以重查任务列表状态为准；CSRF 令牌与 `RYS` 防护头脚本自动处理。

**通道A（推荐）`RAINYUN_API_KEY`**：雨云 API 密钥，形如 `ryapi_xxxxxxxx`。

获取：登录 [app.rainyun.com](https://app.rainyun.com) → 用户中心 → [API 密钥](https://app.rainyun.com/account/settings/api-key) → 创建/复制。此通道用 `X-Api-Key` 头，**免 Cookie、免 CSRF、免人机验证**，是绕开 `10004` 的首选。多账号用 `&` 或换行分隔，也支持 `RAINYUN_API_KEY_1`、`_2` ……

**通道B（兜底）`RAINYUN_COOKIE`**：`api.v2.rainyun.com` 的完整 Cookie。

获取：浏览器登录 [app.rainyun.com](https://app.rainyun.com) → F12 → 网络(Network) → 随便点一个 `api.v2.rainyun.com` 请求 → 请求标头 → 复制整个 `Cookie` 的值整段粘贴（形如 `xxx=yyy; zzz=aaa`）。注意是 `api.v2.rainyun.com` 域下的请求，不是 `app.rainyun.com` 的 cookie。

多账号：值内用 `&` 或换行分隔（cookie 内部用分号分隔，所以多账号分隔符不能用分号）；也支持编号轮询 `RAINYUN_COOKIE`、`RAINYUN_COOKIE_1`、`RAINYUN_COOKIE_2` ……

可选环境变量 `RAINYUN_DELAY`：每日随机延迟上限（分钟），默认 10，`0` 关闭。多账号之间随机间隔 3~15 秒。

可选环境变量 `RAINYUN_TASK_PASSWORDS`：需要暗号的任务密码表，格式 `任务名=密码;任务名=密码` 或 JSON `{"关注雨云B站号":"abcd"}`。配置后脚本自动领取对应任务（如官方号私信结尾 4 个字）。

可选环境变量 `RAINYUN_CLAIM_ALL`：设为 `1` 时对所有 `Status=1` 的任务都用（已配置密码或空密码）尝试领取，顺手清掉可领积分。

可选环境变量 `RAINYUN_CAPTCHA_URL` / `RAINYUN_CAPTCHA_METHOD`（`GET`/`POST`）/ `RAINYUN_CAPTCHA_DATA`：外部打码服务，仅在通道B遇到 `10004` 时使用，脚本自动换腾讯 TCaptcha 票据（`vticket`/`vrandstr`）后重投。`RAINYUN_CAPTCHA_DATA` 支持 `{appid}`（= `2039519451`）与 `{url}` 两个占位符，响应里能递归找到 `ticket`/`randstr` 即可。

可选环境变量 `RAINYUN_TCAPTCHA_SOLVER`（推荐）：指向真浏览器求解器 `solve_tcaptcha.cjs` 的路径。设置后遇到 `10004` 会自动拉起 node + Playwright + 真 Chrome，抓指令条/背景图 → 黑帽分割 + 尺度/旋转双不变 NCC 求点击坐标 → 派发真实鼠标点击 → 点击「确定」提交 → 取回 `ticket`/`randstr` 并带 `vticket`/`vrandstr` 重投。配套脚本在仓库 `tcaptcha-audit/`（`solve_tcaptcha.cjs` + `solve_click.py`）。还有 `RAINYUN_TCAPTCHA_TIMEOUT`（求解器超时秒数，默认 300）。

**返回码**：`code 200`=成功（实测）；`10012`=CSRF 失效（脚本自动刷新令牌重试）；`10004`=风控要求人机验证（需 TCaptcha 的 `vticket`/`vrandstr`，**不是** `verifyCode` 字段；先试自动打码，不行则给出诊断指引）；`30011`=**账号级统一拦截**（见下方警示）；`10002`=输入参数无效；`30002/30038`=登录失效（重新复制更新，或改装 API 密钥）。

> ⚠️ **关于 `10004` 的真相**：雨云把腾讯天御验证码（appid `2039519451`）挂在**领取接口**上，但它是**风控触发**而非硬性要求 —— 实测同一出口 IP 的浏览器会话打这个接口并不弹验证码。青龙机房 IP + 无浏览器指纹 + `dev-code` 设备码不匹配这三者叠加，才会把风险分顶到「必须人机验证」。因此「网页手动签一次就好」是错觉：手动签完当天任务变 `Status=2`，看起来恢复了，次日照样触发。别浪费时间在 sleep 和 UA 上。
>
> **补充（2026-10 实测）**：`10004` 只拦**会话（Cookie）通道**；`X-Api-Key` 通道完全豁免 —— 同样的裸 body 用 API Key 发送从不返回 `10004`。所以只要配上 `RAINYUN_API_KEY`，青龙上那个永远过不去的验证码就从根上消失了。

> ⚠️ **关于 `30011` 的真相（最容易踩坑的一个）**：`30011 未达到完成这个任务的条件` **不是可靠的成功/失败判据**。实测两件事：
> 1. 用 API Key 对**任意** `task_name` 发 POST（包括**不存在的任务名**、`Status=0` 的、`Status=2` 的、`Status=1` 的）都返回同一个 `30011`（只有空参数才报 `10002`），说明它是个泛化的「当前不可领 / 条件未满足」响应，服务端不会告诉你到底哪个条件没过；
> 2. 但**真正领取成功时它也可能返回 `30011`** —— 实测 `关注雨云B站号`、`关注雨云淘宝店` 两个任务返回 `30011`，积分却各 `+1000`（5000 → 6500 → 8500）。
>
> **唯一可靠判据是复查任务列表的 `Status`（或积分变化）。** 脚本已按此实现：提交后一律重查 `Status==2`，`30011` 不再直接报失败。
>
> 而 `每日签到` 的 `30011` 则基本可确定是**风控要求 TCaptcha 票据**：浏览器里点「领取奖励」会先弹验证码，滑过去才真正入账（你可以在 DevTools 里看到两次 POST：第一次无 `vticket`，第二次带上）。

> 🔍 **任务密码是前端硬编码的（CWE-602：客户端强行实施服务端安全机制）**：「关注B站/抖音/淘宝店、加入Q群/微信群」这类任务的密码白名单直接写在客户端 chunk 里 —— `verifyTasks:{"加入Q群":["我爱雨云"],"加入微信群":["雨云爱我"],"关注雨云淘宝店":["成功加入","关注成功"],"关注雨云B站号":["雨云爱你"],"关注雨云抖音号":["天气狐爱你"]}`，校验只是 `if(s && !s.includes(e)) 拒绝`，服务端未参与。脚本已把这些值作为内置默认（可用 `RAINYUN_TASK_PASSWORDS` 覆盖），作为服务端权威兜底的审计取证件。

> ⚠️ **关于 `10004` 的真相**：雨云把腾讯天御验证码（appid `2039519451`）挂在**领取接口**上，但它是**风控触发**而非硬性要求 —— 实测同一出口 IP 的浏览器会话打这个接口并不弹验证码。青龙机房 IP + 无浏览器指纹 + `dev-code` 设备码不匹配这三者叠加，才会把风险分顶到「必须人机验证」。因此「网页手动签一次就好」是错觉：手动签完当天任务变 `Status=2`，看起来恢复了，次日照样触发。别浪费时间在 sleep 和 UA 上。

### 速维云签到

完成 [速维云](https://www.svyun.com/plugin/86/index.htm)「每日签到 + 转盘抽奖」，多账号。速维云是基于魔方财务系统搭建的云服务器商家，脚本走其通用 console API（2026-10 线上验证）：账号密码自动登录（密码 AES-128-CBC 加密，魔方财务前端通用密钥，**无需抓包**），签到后自动把签到/连签奖励的抽奖次数全部用完并汇总奖品。

**环境变量 `SVYUN_ACCOUNT`**：`用户名:密码`，用户名即注册/登录速维云用的邮箱或手机号，例如 `user@example.com:Pass1234`。分隔符也认全角冒号或 `----`；密码里含冒号没关系，按第一个冒号切分。

多账号：值内用 `&` 或换行分隔；也支持编号轮询 `SVYUN_ACCOUNT`、`SVYUN_ACCOUNT_1`、`SVYUN_ACCOUNT_2` …… 注意：密码里含 `&` 时请改用换行或编号变量分隔账号。

可选环境变量 `SVYUN_DELAY`：每日随机延迟上限（分钟），默认 10，`0` 关闭。多账号之间随机间隔 3~15 秒。

**依赖**：`pycryptodome`（青龙 → 依赖管理 → Python3 → 创建依赖 → 填 `pycryptodome`）。

**提示**：推送里展示连签/累计天数与抽奖奖品汇总；提示「验证码/安全验证」= 触发登录风控，先去浏览器登录一次再试；提示密码问题请核对 `用户名:密码` 格式。登录态（JWT）由脚本每次运行自动获取，无需手动维护 token。

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

**依赖安装**：青龙 → 依赖管理 → Python3 → 创建依赖 → 自动拆分填 `requests`（速维云签到还需要 `pycryptodome`，一并添加即可）。

## 已知不可自动化的任务

百度网盘任务中心的"观看广告视频"（依赖穿山甲广告 SDK 服务端验证回调）和第三方 App 推广任务（依赖对应 App 真实启动回传）**无法协议化**，已实测：该 App 原生层有证书锁定，无法通过中间人观察或伪造完成上报。这部分收益（约 200 积分/天）需要真实设备行为。

## 致谢

- [Sitoi/dailycheckin](https://github.com/Sitoi/dailycheckin)（MIT）：原始 baiduwp 模块与整体框架
- [TomyJan/SvYunAutoSign](https://github.com/TomyJan/SvYunAutoSign)：速维云 console API 端点与登录密码加密参数参考
- [whyour/qinglong](https://github.com/whyour/qinglong)：青龙面板

