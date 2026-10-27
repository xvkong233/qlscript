#!/usr/bin/env python3
"""在真机/模拟器上现场生成 sofire z，并写进脚本能直接读的缓存文件。

为什么必须"上设备"：
    z = com.baidu.sofire.ac.FH.gz(context)
    - 87 字符，base64url 解码是 65 字节随机数据（带密钥签名，不是明文 JSON）；
    - 生成逻辑在 native（libnetdisk-security*.so），且 SDK 在 App 进程里
      FH.init(context, "200019", "5a346d07e37763095a270a277baf00e2", {1})，
      算的时候能读到"当前登录的是哪个账号"；
    - 所以同一份 z 只有它的来源登录态能用（跨账号重放必拿 errno=2）。

结论：z 不能离线拼，只能在设备上"开票"。本脚本负责开后把票送进队列，
      不用再手工复制环境变量。

用法（MuMu 默认 127.0.0.1:16384，真机用 -D <serial> 或 -U）：

    # 1) 设备上跑 frida-server（真机需 root；MuMu 直接可跑）
    adb push frida-server /data/local/tmp/ && adb shell "chmod 755 /data/local/tmp/frida-server"
    adb shell "nohup /data/local/tmp/frida-server -D &"

    # 2) 在该账号已登录的 App 界面上（保持前台/后台均可）
    python tools/z_provider.py --serial 127.0.0.1:16384

    # 3) 直接跑签到脚本即可，z 会按 uid 自动命中
    python baidu_netdisk.py

多账号：在 App 里切一个账号跑一次，再切下一个跑一次；缓存文件按 uid 分条，
互不覆盖（这正是"每账号一台设备/一张票"的正确姿势）。
"""
import argparse
import json
import os
import sys
import time

try:
    import frida
except ImportError:
    sys.exit("需要 frida：pip install frida（客户端，不是 frida-tools 也行）")

JS = r"""
Java.perform(function () {
    var out = {};
    function safe(name, fn) {
        try { fn(); } catch (e) { console.log("[!] " + name + " -> " + e); }
    }
    var ActivityThread = Java.use("android.app.ActivityThread");
    var app = ActivityThread.currentApplication();
    if (app === null) { console.log("[!] currentApplication 为空"); send(out); return; }
    var ctx = app.getApplicationContext();

    // 1) sofire 指纹：现场开票
    safe("FH.gz", function () {
        var FH = Java.use("com.baidu.sofire.ac.FH");
        out.z = String(FH.gz(ctx));
        console.log("[z] len=" + out.z.length);
    });

    // 2) 分发渠道（channel 与 z 是同一次现场产物，必须一起带走）
    safe("channel", function () {
        var R = Java.use("com.baidu.netdisk.network.request.RequestCommonParams");
        out.channel = String(R.getChannel());
        console.log("[channel] " + out.channel);
    });

    // 3) 设备号（devuid = AppCommon.DEVUID，安装维度冻结）
    safe("devuid", function () {
        var AC = Java.use("com.baidu.netdisk.kernel.architecture.AppCommon");
        out.devuid = String(AC.DEVUID.value);
        console.log("[devuid] " + out.devuid);
    });

    // 4) 当前登录 uid —— 缓存按它归档，多账号才不会互相覆盖
    safe("uid", function () {
        var AU = Java.use("com.baidu.netdisk.account.AccountUtils");
        out.uid = String(AU.getInstance().getUid());
        console.log("[uid] " + out.uid);
    });

    // 5) WebView UA（脚本侧可选，用来自查机型是否自洽）
    safe("ua", function () {
        var WS = Java.use("android.webkit.WebSettings");
        out.ua = String(WS.getDefaultUserAgent(ctx));
        console.log("[ua] " + out.ua);
    });

    send(out);
});
"""


def main():
    ap = argparse.ArgumentParser(description="在设备上生成 sofire z 并写入脚本缓存")
    ap.add_argument("--serial", default="127.0.0.1:16384",
                    help="frida 设备地址（MuMu 默认 127.0.0.1:16384；真机传 USB serial）")
    ap.add_argument("--process", default="com.baidu.netdisk", help="目标进程名")
    ap.add_argument("--pid", type=int, default=0, help="直接指定 pid（优先于 --process）")
    ap.add_argument("--out", default="", help="输出文件（默认脚本目录 .baidu_sofire_z.json）")
    args = ap.parse_args()

    out_path = args.out or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".baidu_sofire_z.json")

    device = frida.get_device(args.serial, timeout=8)
    target = args.pid or args.process
    print(f"[*] 连接 {args.serial} -> {target}")
    session = device.attach(target)
    holder = {}

    def on_message(msg, data):
        if msg.get("type") == "send":
            holder.update(msg.get("payload") or {})
        else:
            print(msg)

    script = session.create_script(JS)
    script.on("message", on_message)
    script.load()
    time.sleep(2.5)
    session.detach()

    z, uid = holder.get("z"), holder.get("uid")
    if not z or not uid:
        sys.exit(f"[x] 没拿到 z 或 uid（z={bool(z)} uid={uid}）。"
                 "确认 App 已登录、frida-server 在跑、包名正确。")

    data = {"version": 1, "entries": {}}
    if os.path.isfile(out_path):
        try:
            with open(out_path, encoding="utf-8") as f:
                old = json.load(f)
            if isinstance(old, dict) and isinstance(old.get("entries"), dict):
                data["entries"] = old["entries"]
        except (OSError, ValueError):
            pass
    data["entries"][str(uid)] = {
        "z": z,
        "channel": holder.get("channel") or "",
        "device": holder.get("devuid") or "",
        "ua": holder.get("ua") or "",
        "captured_at": time.time(),
    }
    tmp = f"{out_path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)

    print(f"\n[√] 已写入 {out_path}")
    print(f"    uid={uid}")
    print(f"    z  ={z[:18]}…（len={len(z)}）")
    print(f"    channel={holder.get('channel')}")
    print(f"    devuid ={holder.get('devuid')}")
    print("\n提示：z 有保鲜期（脚本默认 24h，BAIDUWP_Z_TTL_H 可调），")
    print("      每天签到前跑一次本脚本即可；多账号逐个切换后各跑一次。")


if __name__ == "__main__":
    main()
