# 飞行日志查看器 (Flight Log Viewer)
# Copyright (C) 2026 hao051026 (小冉学长)
# 本项目以 GNU GPL-3.0 许可发布，详见 LICENSE 与 NOTICE 文件。
"""
ArduPilot / APM 二进制飞行日志（DataFlash）解析器
===================================================

支持解析 ArduPilot (ArduCopter / ArduPlane / ArduRover / ArduSub) 生成的
二进制 DataFlash 日志（常见扩展名 .bin 或 .log）。

格式说明
--------
一个 .bin 日志文件是一条记录（record）序列。每条记录格式为：

    [0xA3] [0x95] [msg_type (1字节)] [payload...]

前两个字节 0xA3 0x95 是记录头标记；随后一个字节是消息类型号。

特殊的 0xFF 消息类型用于扩展消息：payload 内嵌 0xA3 0x95 头部 + 类型号，
用于区分两条逻辑消息。

文件中的每条逻辑消息都以一条 FMT（格式定义）消息描述其字节布局，格式说明符字符：

    b:int8   B:uint8   h:int16   H:uint16   i:int32   I:uint32
    f:float  n:char[4] N:char[16] Z:char[64] e:int64  E:uint64

FMT 消息自身的固定字节布局（也被用于解析后续各条消息）。
头部消息（AUTO 类 "MAV" / "MSG" / "MODE"）作为元数据记录，随解析一并返回。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

# 字节布局说明符 -> (struct 格式字符, 是否字符串, 缩放因子)
# 参照 ArduPilot AP_Logger 官方说明符表：
#   b=int8 B=uint8 h=int16 H=uint16 i=int32 I=uint32
#   f=float d=double n=char[4] N=char[16] Z=char[64]
#   L=int32(经纬度缩放)  M=uint8(飞行模式)  q=int64 Q=uint64  g=float16
#   legacy: c=int16*100 C=uint16*100 e=int32*100 E=uint32*100（带缩放）
_SPEC_FMT_CHAR: Dict[str, Optional[str]] = {
    "b": "b", "B": "B", "h": "h", "H": "H",
    "i": "i", "I": "I", "f": "f", "d": "d",
    "q": "q", "Q": "Q",
    "L": "i",          # int32，经纬度缩放单位1e7 -> 度数
    "M": "B",          # uint8
    "c": "h", "C": "H", "e": "i", "E": "I",   # legacy 缩放
    "g": "e",          # half float (struct 支持)
    "n": "4s", "N": "16s", "Z": "64s",
}

# 字符串字段（非数值）
_SPEC_STR_LENGTH: Dict[str, int] = {"n": 4, "N": 16, "Z": 64}

# 缩放因子（legacy 缩放 100 倍，除回来）
_SPEC_SCALE: Dict[str, float] = {
    "c": 0.01, "C": 0.01, "e": 0.01, "E": 0.01,  # int*100
    "L": 1e-7,  # 经纬度 int32 * 1e-7 -> 度数
}

_SPEC_STR_LENGTH: Dict[str, int] = {"n": 4, "N": 16, "Z": 64, "M": 64}

# FMT 消息自身的字节布局（type-83 / msg "FMT"）
_FMT_MSG_TYPE = 128
_FMT_LAYOUT: List[Tuple[str, str, str, int]] = [
    # (说明符, 字段名, 语义名, 固定大小)
    ("B", "type", "type", 1),            # 后续消息类型号
    ("B", "length", "length", 1),        # 该消息总长（含头部?）
    ("n", "name", "name", 4),            # 消息名（4 字符）
    ("n", "format", "format", 4),        # 格式说明符（4 字符）
    ("n", "labels", "labels", 4),        # 标签（4 字符）
]

# 头部记录类型：AUTO 消息在 type 字段里写 0x81/0x81? 见 parse_auto_message
_AUTO_MSG_TYPES = {0x80, 0x81, 0x82, 0xA0, 0xA1, 0xA2}


@dataclass
class ArduMessage:
    """一条解析出的日志消息。"""

    type: int                       # 消息类型号
    name: str                       # 4 字符消息名（如 "GPS" / "ATT" / "PM"）
    time: Optional[float] = None    # 可选：TimeUS 字段（微秒）或相对时间
    fields: Dict[str, Any] = field(default_factory=dict)
    is_header: bool = False         # 是否为元数据(MAV/MSG/MODE/PARAM)
    raw_size: Optional[int] = None


@dataclass
class ArduFlightLog:
    """整个日志的解析结果。"""

    filename: str
    messages: List[ArduMessage] = field(default_factory=list)
    formats: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # name -> FMT
    firmware: Optional[str] = None
    frames: List[Dict[str, Any]] = field(default_factory=list)   # 每帧关键数据

    def message_names(self) -> List[str]:
        return sorted({m.name for m in self.messages if not m.is_header})

    def by_name(self, name: str) -> List[ArduMessage]:
        return [m for m in self.messages if m.name == name]


# ----------------------------------------------------------------
# 单个二进制格式实例（struct.Struct 缓存）
# ----------------------------------------------------------------
class _BinFormat:
    __slots__ = ("name", "type", "resolvers", "fmt", "size", "labels", "scales")

    def __init__(self, name: str, typ: int, format_str: str, labels: Union[str, List[str]]):
        self.name = name
        self.type = typ
        # 构造 struct 格式：小端 + 各字段
        fmt_chars = []
        resolvers = []
        scales = []
        for ch in format_str:
            sc = _SPEC_FMT_CHAR.get(ch)
            if sc is None:
                raise ValueError(f"未知格式说明符: {ch!r} (message {name})")
            fmt_chars.append(sc)
            if ch in _SPEC_STR_LENGTH:
                resolvers.append(("str", _SPEC_STR_LENGTH[ch]))
                scales.append(1.0)
            else:
                resolvers.append(("num", sc))
                scales.append(_SPEC_SCALE.get(ch, 1.0))
        self.resolvers = resolvers
        self.scales = scales
        self.fmt = struct.Struct("<" + "".join(fmt_chars))
        self.size = self.fmt.size

        if isinstance(labels, str):
            self.labels = labels.split(",") if labels else []
        else:
            self.labels = list(labels)

    def decode(self, payload: bytes) -> Dict[str, Any]:
        if len(payload) < self.size:
            raise ValueError(f"{self.name}: payload {len(payload)} < expected {self.size}")
        vals = self.fmt.unpack_from(payload, 0)
        out: Dict[str, Any] = {}
        for i, (kind, _meta) in enumerate(self.resolvers):
            label = self.labels[i] if i < len(self.labels) else f"f{i}"
            v = vals[i]
            if kind == "str":
                v = v.split(b"\x00")[0].decode("latin-1", "replace")
            else:
                s = self.scales[i]
                if s != 1.0 and isinstance(v, (int, float)):
                    v = v * s
            out[label] = v
        return out


# ----------------------------------------------------------------
# 线头字符 -> (名字, 格式, 标签) 的兜底映射（若日志缺少 FMT 也可用）
# 真实日志中 FMT 消息会逐条描述格式；此表仅在日志异常时兜底。
# ----------------------------------------------------------------
_FALLBACK_FORMATS: Dict[int, Tuple[str, str, str]] = {}


def _decode_fmt_payload(payload: bytes) -> Tuple[int, int, str, str, str]:
    """从 FMT 消息 payload 中解出 (type, length, name, format, labels)。

    FMT 消息自身的字节布局由 format 说明符 "BBnNZ" 描述：
      uint8 type; uint8 length; char[4] name; char[16] format; char[64] columns
    （此即第一个 FMT 消息所描述的自己，格式字段用固定 N(16)/Z(64) 宽。）
    """
    if len(payload) < 86:
        raise ValueError("FMT payload too short")
    typ, length = payload[0], payload[1]
    name = payload[2:6].split(b"\x00")[0].decode("latin-1", "replace").strip()
    format_s = payload[6:22].split(b"\x00")[0].decode("latin-1", "replace").strip()
    labels = payload[22:86].split(b"\x00")[0].decode("latin-1", "replace").strip()
    return typ, length, name, format_s, labels


def _decode_string_field(v: bytes, length: int) -> str:
    return v[:length].split(b"\x00")[0].decode("latin-1", "replace")


# ----------------------------------------------------------------
# 主解析器
# ----------------------------------------------------------------
def parse_ardupilot_log(data: bytes, filename: str = "") -> ArduFlightLog:
    """解析一个 ArduPilot DataFlash 二进制日志的完整字节内容。"""
    log = ArduFlightLog(filename=filename or "<memory>")
    pos = 0
    n = len(data)
    formats: Dict[int, _BinFormat] = {}
    current_time: Optional[float] = None

    while pos < n:
        # 查找记录头 0xA3 0x95
        # 为容忍部分日志前导字节，逐字节扫描
        if pos + 2 > n:
            break
        if data[pos] != 0xA3 or data[pos + 1] != 0x95:
            pos += 1
            continue
        pos += 2
        if pos >= n:
            break
        msg_type = data[pos]
        pos += 1

        # 扩展消息：payload 内嵌 0xA3 0x95 + 类型号
        if msg_type == 0xFF:
            if pos + 2 > n:
                break
            if data[pos] != 0xA3 or data[pos + 1] != 0x95:
                pos += 1
                continue
            msg_type = data[pos + 2]
            pos += 3

        # 需要 FMT 定义来确定 payload 长度
        # 注意：FMT 记录头恒为 type=128(0x80)，载荷 payload[0] 才是它描述的消息类型。
        # 因此 msg_type==128 时必须优先按 FMT 定义处理（除非 payload[0] 恰好有对应定义）。
        fmt: Optional[_BinFormat] = None
        if msg_type == _FMT_MSG_TYPE:
            # 先解析 FMT payload（每个 FMT 载荷固定 86 字节: type,length,name[4],format[16],columns[64]）
            try:
                typ, length, name, format_s, labels = _decode_fmt_payload(bytes(data[pos:pos + 86]))
            except ValueError:
                pos += 1
                continue
            # 建立新格式（若 payload[0] 已注册过则为重复定义，直接跳过载荷）
            try:
                bf = _BinFormat(name, typ, format_s, labels)
            except Exception:
                pos += 1
                continue
            formats[typ] = bf
            log.formats[name] = {
                "type": typ,
                "name": name,
                "format": format_s,
                "labels": labels,
            }
            bf_len = 86  # FMT 消息 payload 固定长
            if pos + bf_len > n:
                break
            # FMT 消息本身作为一条元数据记录
            ffields = {
                "type": typ,
                "length": length,
                "name": name,
                "format": format_s,
                "labels": labels,
            }
            log.messages.append(ArduMessage(type=_FMT_MSG_TYPE, name="FMT",
                                            fields=ffields, raw_size=bf_len))
            pos += bf_len
            continue

        if msg_type in formats:
            fmt = formats[msg_type]
            size = fmt.size
        else:
            # 未知消息类型且非 FMT，无法解析长度，跳过
            pos += 1
            continue

        # 解析已知格式的消息
        if pos + fmt.size > n:
            # 不完整
            break
        payload = bytes(data[pos:pos + fmt.size])
        pos += fmt.size

        try:
            obj = fmt.decode(payload)
        except Exception:
            continue

        # FMT 消息特殊处理（其实上面分支已处理，仅当 type 恰为 FMT 但已存在 format 时）
        if fmt.type == _FMT_MSG_TYPE:
            continue

        # 计算时间字段
        time = None
        if "TimeUS" in obj:
            time = obj["TimeUS"] / 1e6  # 微秒 -> 秒
        elif "TimeMS" in obj:
            time = obj["TimeMS"] / 1e3  # 毫秒 -> 秒
        elif "time" in obj:
            time = float(obj["time"])
        current_time = time if time is not None else current_time

        # 头部消息（元数据）
        is_header = False
        fname = fmt.name
        iv = obj.get("Id", obj.get("Mode", None))
        if fname in ("MAV", "MSG", "MODE", "PARM", "PARAM"):
            is_header = True
            if fname == "MAV" and "MavType" in obj:
                try:
                    from ctypes import c_int
                    mav_type = obj["MavType"]
                    mav_names = {
                        2: "QUADROTOR", 12: "FIXED_WING", 18: "HELICOPTER",
                        20: "ROVER", 10: "PLANE",
                    }
                    log.firmware = mav_names.get(int(mav_type), f"MAV_TYPE_{mav_type}")
                except Exception:
                    pass
        if not log.firmware and fname == "MSG":
            # MSG 消息的 Message 字段可能含固件信息
            m = obj.get("Message", "")
            if isinstance(m, str) and m and ("Ardu" in m or "MAV_" in m):
                log.firmware = m
        elif fname == "AUTO" and log.firmware is None:
            mod = str(obj.get("Mode", ""))
            if mod:
                log.firmware = mod

        msg = ArduMessage(
            type=fmt.type,
            name=fname,
            time=time,
            fields=obj,
            is_header=is_header,
            raw_size=fmt.size,
        )
        log.messages.append(msg)

    return log


def load_ardupilot_file(path: str) -> ArduFlightLog:
    """从磁盘文件加载并解析一个 ArduPilot .bin/.log 日志。"""
    with open(path, "rb") as f:
        data = f.read()
    return parse_ardupilot_log(data, filename=path)


def export_ardupilot_csv(log: ArduFlightLog, out_path: str, msg_name: str = "GPS"):
    """将某一消息类型按时间序列导出为 CSV（便于人工查看 / 图表）。"""
    import csv

    items = log.by_name(msg_name)
    if not items:
        raise ValueError(f"日志中没有 {msg_name} 消息")
    # 以第一条非头部消息的字段作为列
    all_keys: List[str] = []
    for m in items:
        for k in m.fields:
            if k not in all_keys:
                all_keys.append(k)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=all_keys)
        w.writeheader()
        for m in items:
            w.writerow(m.fields)
    return out_path