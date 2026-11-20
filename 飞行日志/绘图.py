# 飞行日志查看器 (Flight Log Viewer)
# Copyright (C) 2026 hao051026 (小冉学长)
# 本项目以 GNU GPL-3.0 许可发布，详见 LICENSE 与 NOTICE 文件。
"""
静态图表绘制（无浏览器环境用 matplotlib 出图）。
"""

from __future__ import annotations

import os
from typing import Optional, List

import numpy as np


def plot_channels(log, summary, out_path: str,
                  channels: Optional[List[str]] = None) -> None:
    """绘制指定通道（或多个）随时间变化的曲线图并保存 PNG。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    # 设置中文字体（Windows 常见字体，避免中文标题显示方块）
    for f in ["Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "SimSun"]:
        try:
            plt.rcParams["font.sans-serif"] = [f, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            break
        except Exception:
            continue

    series = summary.series
    if channels:
        wanted = {c for c in channels}
        # 同时支持中文/英文名匹配
        from .中文映射 import channel_name
        series = [s for s in series if s.name in wanted or channel_name(s.name) in wanted]

    n = len(series)
    if n == 0:
        raise ValueError("没有可绘制的通道")

    ncols = 1
    nrows = n
    fig, axes = plt.subplots(nrows, ncols, figsize=(10, n * 2.2), squeeze=False)
    fig.suptitle(f"飞行日志 - {os.path.basename(summary.source)}", fontsize=14)

    from .中文映射 import series_label as _ser_label
    for i, ser in enumerate(series):
        ax = axes[i][0]
        ax.plot(ser.time_s, ser.values, lw=1, color="#1f77b4")
        ax.set_ylabel(_ser_label(ser.source, ser.name), fontsize=8)
        ax.grid(True, alpha=.25)
        if i < n - 1:
            ax.set_xticklabels([])
    axes[-1][0].set_xlabel("时间 (秒)")

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(out_path, dpi=100)
    plt.close(fig)