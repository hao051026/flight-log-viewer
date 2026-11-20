# 飞行日志查看器 (Flight Log Viewer)
# Copyright (C) 2026 hao051026 (小冉学长)
# 本项目以 GNU GPL-3.0 许可发布，详见 LICENSE 与 NOTICE 文件。
"""
统一入口：根据文件探测格式并加载日志。
"""

from __future__ import annotations

import os

from .分析 import summarize
from .解析器.贝塔解析 import load_betaflight_file
from .解析器.阿德解析 import load_ardupilot_file


def _detect_format(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    # 读取少量字节做内容探测
    with open(path, "rb") as f:
        head = f.read(400)
    if head.startswith(b"BTFL_BLACKBOX") or b"H Product:Blackbox" in head:
        # Blackbox：进一步区分文本(有 fieldnames) 与二进制
        if b"fieldnames" in head or head.count(b"H Field") == 0 and b"H Product" in head:
            pass
        # 判断是否为二进制：数据段含非 ASCII 字节多，且无 fieldnames
        # .BBL/.BFL 通常二进制
        if ext in (".bin", ".log", ".bfl"):
            return "ardupilot"  # .bin 默认 ArduPilot
        if ext in (".bbl",):
            return "bbl_binary"
        return "betaflight"
    if ext in (".bin", ".log"):
        return "ardupilot"
    if ext in (".csv", ".bbl"):
        return "betaflight"
    if b"\xa3\x95" in head:
        return "ardupilot"
    # 文本日志常见于 Betaflight
    return "betaflight"


def load_any(path: str):
    """探测格式并返回对应的解析日志对象（BfFlightLog / ArduFlightLog / BbResult）。"""
    kind = _detect_format(path)
    if kind == "ardupilot":
        return load_ardupilot_file(path)
    if kind == "bbl_binary":
        from .解析器.二进制黑盒解析 import parse_binary_blackbox
        with open(path, "rb") as f:
            return _BinaryLog(parse_binary_blackbox(f.read()), path)
    return load_betaflight_file(path)


class _BinaryLog:
    """包装二进制 Blackbox 解析结果，使其可被 summarize 处理。"""

    def __init__(self, result: dict, filename: str = ""):
        self.result = result
        self.filename = filename
        self.firmware = result.get("firmware")
        self.series = []  # 由 summarize_binary 填充


def summarize_any(log):
    """对任意解析日志对象生成统计摘要（含 series）。"""
    s = summarize(log)
    return s