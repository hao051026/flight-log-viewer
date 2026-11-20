# 飞行日志查看器 (Flight Log Viewer)
# Copyright (C) 2026 hao051026 (小冉学长)
# 本项目以 GNU GPL-3.0 许可发布，详见 LICENSE 与 NOTICE 文件。
"""
FlightLogViewer 飞行日志分析工具
================================

读取主流开源飞行控制器（Betaflight / INAV / ArduPilot）产生的飞行日志，
解析并可视化。

模块结构
--------
- 飞行日志.解析器.阿德解析 : ArduPilot DataFlash 二进制日志(.bin/.log)
- 飞行日志.解析器.贝塔解析 : Betaflight/INAV Blackbox CSV 日志
- 飞行日志.分析 : 上层统一数据模型与统计摘要
- 飞行日志.网页 : Flask Web 界面（图表可视化）
"""

from .分析 import summarize, FlightData, TimeSeries, FlightSummary
from .解析器.阿德解析 import (
    parse_ardupilot_log, load_ardupilot_file,
    ArduFlightLog, ArduMessage,
)
from .解析器.贝塔解析 import (
    parse_betaflight_log, load_betaflight_file,
    BfFlightLog, BfSession,
)

__version__ = "1.0.0"

__all__ = [
    "summarize", "FlightData", "TimeSeries", "FlightSummary",
    "parse_ardupilot_log", "load_ardupilot_file", "ArduFlightLog", "ArduMessage",
    "parse_betaflight_log", "load_betaflight_file", "BfFlightLog", "BfSession",
    "__version__",
]