# 飞行日志查看器 (Flight Log Viewer)
# Copyright (C) 2026 hao051026 (小冉学长)
# 本项目以 GNU GPL-3.0 许可发布，详见 LICENSE 与 NOTICE 文件。
#!/usr/bin/env python3
"""
生成用于测试的样例飞行日志：
- samples/sample_ardupilot.bin  —— 符合 ArduPilot DataFlash 二进制格式的合成日志
- samples/sample_betaflight.csv —— 符合 Betaflight Blackbox CSV 格式的合成日志

样例数值是模拟飞行数据，仅用于验证解析器与可视化管道，不代表真实飞行。
"""

from __future__ import annotations

import math
import os
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(os.path.dirname(HERE), "样例")


# ---------------------------------------------------------------
# ArduPilot DataFlash 二进制合成
# ---------------------------------------------------------------
# 记录格式: [0xA3][0x95][type(1)][payload...]
# FMT 消息自身布局: BBnNZ  (type,length,name[4],format[16],columns[64])
# 消息格式说明符:
#   Q=uint64  e? 实际用: Q(uint64 TimeUS), B(uint8), b(int8),
#   h(int16), H(uint16), i(int32), I(uint32), f(float), n(char[4]), N(char[16]), Z(char[64])
# 这里统一使用: Q=uint64(8B), B=uint8(1B), h=int16(2B), f=float(4B), i=int32(4B), c=char(1B)

def _fmt_ser(fmt: str) -> str:
    """将 ArduPilot 说明符映射为 Python struct 对齐字符（均无对齐）。"""
    m = {
        "b": "b", "B": "B", "h": "h", "H": "H",
        "i": "i", "I": "I", "f": "f",
        "d": "d", "n": "4s", "N": "16s", "Z": "64s", "c": "c",
    }
    out = []
    for ch in fmt:
        out.append(m[ch])
    return "".join(out)


def make_ardupilot_bin(path):
    out = bytearray()

    def add_record(msg_type, payload):
        out.extend(b"\xa3\x95")
        out.append(msg_type)
        out.extend(payload)

    # 定义消息结构（Type, message name, format 说明符, labels, struct 模板）
    # 仅使用解析器明确支持的说明符，保证自描述自洽：
    #   Q=uint64(8) i=int32(4) f=float(4) B=uint8(1) h=int16(2) I=uint32(4) Z=char[64]
    msg_defs = [
        (1, "GPS", "Qiiff", "TimeUS,Lat,Lng,Alt,Spd"),
        (2, "IMU", "Qfff",  "TimeUS,AccX,AccY,AccZ"),
        (3, "ATT", "Qfff",  "TimeUS,Roll,Pitch,Yaw"),
        (4, "BAT", "Qff",   "TimeUS,Volt,Curr"),
        (5, "MSG", "QZ",    "TimeUS,Message"),
    ]

    # 先写所有 FMT 消息（type=128）
    for typ, name, fmt, labels in msg_defs:
        name_b = name.encode()[:4].ljust(4, b"\x00")
        format_b = fmt.encode()[:16].ljust(16, b"\x00")
        labels_b = labels.encode()[:64].ljust(64, b"\x00")
        # FMT payload: type(1) length(1) name(4) format(16) columns(64)
        payload = struct.pack("<BB", typ, 0) + name_b + format_b + labels_b
        add_record(128, payload)

    # 写一条 MSG 头部（固件信息）
    msgmsg = "FIRMWARE:ArduCopter V4.5.1 beta".encode()[:64].ljust(64, b"\x00")
    add_record(5, struct.pack("<Q64s", 1_000_000, msgmsg))

    # 数据
    t0 = 2_000_000  # 微秒
    n_pts = 900
    for i in range(n_pts):
        t = t0 + i * 50_000  # 50ms 间隔
        tt = (t - t0) / 1e6
        # GPS (频率低：每 5 点一次)
        if i % 5 == 0:
            lat = 394005000 + i * 5
            lng = 116005000 + i * 3
            gps = struct.pack("<Qiiff",
                              t, lat, lng, 400 + i * 2, 5 + 0.1 * i)
            add_record(1, gps)
        # IMU
        ax = 0.2 * math.sin(tt * 2)
        ay = 0.15 * math.cos(tt * 1.7)
        az = 9.8 + 0.5 * math.sin(tt * 3)
        add_record(2, struct.pack("<Qfff", t, ax, ay, az))
        # ATT
        roll = 15 * math.sin(tt * 1.2)
        pitch = 10 * math.cos(tt * 0.9)
        yaw = (90 + 180 * (tt / 10)) % 360
        add_record(3, struct.pack("<Qfff", t, roll, pitch, yaw))
        # BAT
        volt = 24.8 - 0.3 * (i / n_pts)
        curr = 3.0 + 2.0 * abs(math.sin(tt))
        add_record(4, struct.pack("<Qff", t, volt, curr))

    with open(path, "wb") as f:
        f.write(bytes(out))
    print(f"已生成 ArduPilot 样例: {path} ({len(out)} 字节)")


# ---------------------------------------------------------------
# Betaflight Blackbox CSV 合成
# ---------------------------------------------------------------
def make_betaflight_csv(path):
    lines = []
    lines.append("H Product:Blackbox")
    lines.append("H Data version:2")
    lines.append("H firmware_type:Betaflight")
    lines.append("H firmware_revision:4.4.0")
    lines.append("H board:SPRACINGF4EVO")
    lines.append("H interval:250")
    lines.append("H fieldnames:time,loopIteration,throttle,vbat,rssi,altitude,current")
    lines.append("")
    n = 1000
    for i in range(n):
        t_us = i * 250
        loop = i
        thr = 1000 + 500 * (0.5 + 0.5 * math.sin(i / 60))
        vbat = 24.0 - 0.002 * i
        rssi = 70 + 20 * abs(math.sin(i / 100))
        alt = 200 * (1 - math.exp(-i / 300)) + 5 * math.sin(i / 40)
        curr = 3 + 2 * abs(math.sin(i / 50))
        lines.append(f"{t_us},{loop},{thr:.1f},{vbat:.3f},{rssi:.1f},{alt:.2f},{curr:.2f}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"已生成 Betaflight 样例: {path}")


if __name__ == "__main__":
    os.makedirs(SAMPLES, exist_ok=True)
    make_ardupilot_bin(os.path.join(SAMPLES, "样例阿德日志.bin"))
    make_betaflight_csv(os.path.join(SAMPLES, "样例贝塔日志.csv"))