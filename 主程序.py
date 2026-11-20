# 飞行日志查看器 (Flight Log Viewer)
# Copyright (C) 2026 hao051026 (小冉学长)
# 本项目以 GNU GPL-3.0 许可发布，详见 LICENSE 与 NOTICE 文件。
#!/usr/bin/env python3
"""
FlightLogViewer 命令行 / Web 双入口

用法:
    python 主程序.py web [--port 5000]        # 启动 Web 界面
    python 主程序.py info <日志文件>            # 打印日志信息与统计摘要
    python 主程序.py plot <日志文件> --out out.png   # 生成静态曲线图
"""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="飞行日志查看器")
    sub = parser.add_subparsers(dest="cmd")

    web_p = sub.add_parser("web", help="启动 Web 界面")
    web_p.add_argument("--host", default="127.0.0.1")
    web_p.add_argument("--port", type=int, default=5000)

    info_p = sub.add_parser("info", help="打印日志统计摘要")
    info_p.add_argument("file")
    info_p.add_argument("--json", action="store_true", help="以 JSON 输出")

    plot_p = sub.add_parser("plot", help="生成静态曲线图")
    plot_p.add_argument("file")
    plot_p.add_argument("--out", default="flight_plot.png")
    plot_p.add_argument("--channels", nargs="*", help="要绘制的通道名列表")

    args = parser.parse_args()

    # 保证能从任意启动目录导入 飞行日志 包
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    if args.cmd == "web":
        from 飞行日志.网页.应用 import APP
        print(f"FlightLogViewer 运行在 http://{args.host}:{args.port}")
        APP.run(host=args.host, port=args.port, debug=False)
        return 0

    # 文件子命令：自动探测格式
    from 飞行日志.核心 import load_any, summarize_any  # 延迟导入
    log = load_any(args.file)
    summary = summarize_any(log)

    if args.cmd == "info":
        if args.json:
            import json
            print(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2))
        else:
            _print_summary(summary)
        return 0

    if args.cmd == "plot":
        import matplotlib
        matplotlib.use("Agg")
        from 飞行日志.绘图 import plot_channels
        plot_channels(log, summary, args.out, args.channels)
        print(f"图表已保存到 {args.out}")
        return 0

    parser.print_help()
    return 0


def _print_summary(s) -> None:
    from 飞行日志.中文映射 import fmt_name, channel_name
    d = s.as_dict()
    print(f"日志文件: {d['source']}")
    print(f"日志格式: {fmt_name(d['format'])}    飞控固件: {d['firmware'] or '—'}")
    print(f"飞行时长: {d['duration_s']} 秒    采样数: {d['sample_count']}    解锁周期: {d['armed_cycles']}")
    labels = {
        "max_altitude_m": "最高海拔（米）",
        "max_speed_m_s": "最高速度（米/秒）",
        "max_current_a": "最大电流（安培）",
        "max_horizontal_accel_g": "最大水平加速度（g）",
        "battery_min_v": "电池最低电压（伏）",
        "battery_start_v": "电池起始电压（伏）",
        "battery_end_v": "电池结束电压（伏）",
    }
    for k, v in d.items():
        if k in ("source", "format", "firmware", "duration_s", "sample_count",
                 "armed_cycles", "channel_report"):
            continue
        if v is not None:
            print(f"{labels.get(k, k)}: {v}")
    if d.get("channel_report"):
        print("通道统计（最小值 ~ 最大值）：")
        for name, (mn, mx) in d["channel_report"].items():
            print(f"  {channel_name(name)}: {mn:.3f} ~ {mx:.3f}")


if __name__ == "__main__":
    raise SystemExit(main())