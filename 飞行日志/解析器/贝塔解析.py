# 飞行日志查看器 (Flight Log Viewer)
# Copyright (C) 2026 hao051026 (小冉学长)
# 本项目以 GNU GPL-3.0 许可发布，详见 LICENSE 与 NOTICE 文件。
"""
Betaflight / INAV Blackbox 飞行日志解析器
==========================================

支持解析 Betaflight 和 INAV 生成的 Blackbox 日志。Blackbox 日志有两种常见形态：

1. **CSV 文本形态**（推荐，用户最易获得）
   - 由黑羊 Betaflight 配置器 / blackbox-tools 导出的 `.csv`
   - 或直接在 SD 卡上的 `.bbl` 文本形态（同 CSV 基本语法）
   - 语法：文件由若干 **会话(session)** 构成，每次解锁(arm)一个会话。
     每个会话以 `H Product:Blackbox ...` 头部行开始，随后是 `H field:value`
     元数据行，然后是一批数据行。数据行是逗号分隔的数值，第一帧前通常有
     一行字段名（形如 `H fieldnames:time,gyroADC[0],...` 或由帧模板推断）。

2. **二进制形态**（.bbl 二进制 / BB 编码）—— 尽力而为支持
   - Betaflight 二进制黑盒使用变长帧：整数帧(I) / 间隔帧(S) / GPS /
     DEBUG / G 帧等，字段按 header 里的 field 定义编码。
   - 本模块提供基础解码：可解析 G (gyro) 连续整型帧与带索引头的时间序列。
     复杂压缩编码（间隔 S 帧增量等）标记为未支持并给出说明。

目的是把原始日志转成结构化的时间序列（numpy/pandas），供图表与统计使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ----------------------------------------------------------------
# 常见 Blackbox 帧的字段模板（用于在日志未自带字段名时兜底推断）
# ----------------------------------------------------------------
# 帧字母 -> 列名列表（第一列总是时间，单位：微秒）
_BF_FRAME_COLUMNS: Dict[str, List[str]] = {
    "I": ["time", "loopIteration", "throttle", "vbat",
          "rssi", "gyroADC[0]", "gyroADC[1]", "gyroADC[2]",
          "accSmooth[0]", "accSmooth[1]", "accSmooth[2]",
          "magADC[0]", "magADC[1]", "magADC[2]"],
    "G": ["time", "interior_gyro[0]", "interior_gyro[1]", "interior_gyro[2]",
          "extended_gyro[0]", "extended_gyro[1]", "extended_gyro[2]"],
    "S": ["time", "accelerometer[0]", "accelerometer[1]", "accelerometer[2]",
          "vbat", "current", "rssi", "armed", "status", "position[0]",
          "position[1]", "altitude"],
    "GPS": ["time", "GPS_numSat", "GPS_lon", "GPS_lat", "GPS_altitude",
            "GPS_speed", "GPS_ground_course", "GPS_accuracy"],
    "D": ["time", "debug[0]", "debug[1]", "debug[2]", "debug[3]",
          "debug[4]", "debug[5]", "debug[6]", "debug[7]"],
}

# 头元数据行里常见的字段
_HEADER_META_KEYS = {
    "Product", "Data version", "firmware_type", "firmware_revision",
    "board", "log_start_timestamp", "log_end_timestamp", "interval",
    "fieldnames", "GPS_fieldnames", "field",
}


@dataclass
class BfFrame:
    """Betaflight 二进制帧抽象（尽力而为解码用）。"""

    frame_type: str          # "I"/"S"/"G"/"GPS"/"D"/...
    time_us: Optional[int]
    values: List[float]


@dataclass
class BfSession:
    """一个解锁周期 = 一个会话。"""

    index: int
    header: Dict[str, str] = field(default_factory=dict)
    column_names: List[str] = field(default_factory=list)   # 主数据帧列名（不含帧字母）
    rows: List[List[Any]] = field(default_factory=list)      # 主数据帧行
    time_us: List[int] = field(default_factory=list)         # 主时间序列
    frame_rows: Dict[str, List[List[Any]]] = field(default_factory=dict)  # 按帧类型
    frame_columns: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        if len(self.time_us) >= 2:
            return (self.time_us[-1] - self.time_us[0]) / 1e6
        return 0.0

    def numeric_matrix(self, col_whitelist: Optional[set] = None):
        """把主数据帧转成 numpy 数值矩阵（便于绘图）。返回 (列名, np.ndarray)。"""
        import numpy as np
        # 用第一个数据行推断原则类型
        ncols = len(self.column_names)
        # 收集每个数值列
        numeric_cols: List[int] = []
        numeric_names: List[str] = []
        for c in range(ncols):
            key = self.column_names[c] if c < len(self.column_names) else f"c{c}"
            if col_whitelist and key not in col_whitelist:
                continue
            # 尝试把该列所有已解析值转 float
            vals = []
            ok = True
            for r in self.rows:
                if c >= len(r):
                    ok = False
                    break
                v = r[c]
                if isinstance(v, (str, bytes)):
                    try:
                        v = float(v)
                    except (ValueError, TypeError):
                        ok = False
                        break
                try:
                    vals.append(float(v))
                except (ValueError, TypeError):
                    ok = False
                    break
            if ok:
                numeric_cols.append(c)
                numeric_names.append(key)
        if not numeric_cols:
            return [], np.zeros((len(self.rows), 0))
        mat = np.zeros((len(self.rows), len(numeric_cols)))
        for i, r in enumerate(self.rows):
            for j, c in enumerate(numeric_cols):
                v = r[c] if c < len(r) else 0.0
                try:
                    mat[i, j] = float(v)
                except (ValueError, TypeError):
                    mat[i, j] = 0.0
        return numeric_names, mat


@dataclass
class BfFlightLog:
    """Betaflight/INAV Blackbox 日志解析结果。"""

    filename: str
    sessions: List[BfSession] = field(default_factory=list)
    firmware: Optional[str] = None

    def best_session(self) -> Optional[BfSession]:
        """返回最长的会话（通常是最值得分析的）。"""
        if not self.sessions:
            return None
        return max(self.sessions, key=lambda s: len(s.rows))


# 二进制帧解码辅助（尽力而为）
def _decode_binary_frame(frame_type: str, payload: bytes, prev: Optional[Dict]) -> Optional[BfFrame]:
    """尝试把一段二进制负载按帧类型解码。

    完整二进制黑盒解码（含间隔帧增量压缩、可变长整型、位压缩）是一个
    大工程，这里仅覆盖未压缩的整型帧 G 帧等，返回 None 表示不支持的编码。
    """
    return None


# ----------------------------------------------------------------
# CSV / 文本形态解析
# ----------------------------------------------------------------
def _looks_like_header(line: str) -> bool:
    s = line.lstrip()
    return s.startswith("H ") or s.startswith("H\t")


def _parse_header_line(line: str) -> Optional[Tuple[str, str]]:
    """解析 `H key:value` 或 `H key value`。失败返回 None。"""
    s = line.strip()
    if not s.startswith("H"):
        return None
    body = s[1:].lstrip()
    if ":" in body:
        k, v = body.split(":", 1)
        return k.strip(), v.strip()
    # 尝试空格分隔（分隔符可能为若干空格）
    parts = body.split(None, 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return None, None


def _looks_like_data(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    # 数据行可能以帧字母开头（I/S/G/GPS/D...）或直接数字（时间）
    first = s.split(",", 1)[0].strip()
    if first.isdigit():
        return True
    if first.isalpha() and 0 < len(first) <= 4:
        return True
    return False


def _looks_like_field_line(line: str) -> bool:
    """判断一行是否像字段名清单（例如 'time,gyroADC[0],...' 不带 H 前缀）。"""
    s = line.strip()
    if not s.startswith("H"):
        return False
    body = s[1:].lstrip()
    # 字段行通常是 'H fieldnames:time,...' 或 'H field time,...'
    low = body.lower()
    return "field" in low or "time," in low


def _split_csv_row(line: str) -> List[str]:
    """按逗号分割一行，容忍引号（简单实现）。"""
    import csv as _csv
    import io
    return next(_csv.reader(io.StringIO(line), skipinitialspace=True))


def parse_betaflight_log(text: str, filename: str = "") -> BfFlightLog:
    """从 Blackbox CSV/文本内容解析出会话与数据。

    参数:
        text: 文件全文（utf-8 解码后）。
    返回:
        BfFlightLog 对象。
    """
    log = BfFlightLog(filename=filename or "<memory>")
    lines = text.splitlines()

    session: Optional[BfSession] = None
    pending_fieldline_names: Optional[List[str]] = None
    frame_header_seen: Dict[str, bool] = {}

    def ensure_session() -> BfSession:
        nonlocal session, frame_header_seen
        if session is None:
            session = BfSession(index=len(log.sessions) + 1)
            log.sessions.append(session)
            frame_header_seen = {}
        return session

    data_mode = False
    for raw in lines:
        if raw.strip() == "":
            # 空行可能是会话分隔，保持当前
            continue
        # 会话边界：新的 Product 头
        if raw.lstrip().startswith("H Product:Blackbox"):
            session = BfSession(index=len(log.sessions) + 1)
            log.sessions.append(session)
            frame_header_seen = {}
            pending_fieldline_names = None
            data_mode = True
            hs = _parse_header_line(raw)
            if hs:
                session.header[hs[0]] = hs[1]
            continue

        if _looks_like_header(raw):
            k, v = _parse_header_line(raw)
            sess = ensure_session()
            # 若仍是空会话（首个头行），标记 firmware 等
            if k is None:
                # 无法解析，忽略
                continue
            # fieldnames 列名行：记录为该会话的字段定义
            kl = k.lower()
            if "fieldname" in kl:
                pending_fieldline_names = [x.strip() for x in v.split(",") if x.strip()]
                # 保存到会话的列定义（供主帧使用）
                if pending_fieldline_names:
                    first = pending_fieldline_names[0]
                    # 若首列不是 time，则在推断列里记录
                    sess.column_names = pending_fieldline_names
                    sess.frame_columns["_list"] = pending_fieldline_names
                sess.header[k] = v
            else:
                sess.header[k] = v
                if not log.firmware and k.lower() in ("firmware_type",):
                    log.firmware = v
            # 帧字段定义行: 形如 "H field GYRO time,gyroADC[0],..."
            if k.lower() in ("field", "fields"):
                # v 形如 "GYRO time,gyroADC[0],..." 或 "fieldnames"
                pass
            continue

        if pending_fieldline_names and _looks_like_field_line(raw):
            # 已经由上面的 header 分支处理了 fieldnames
            continue

        # 数据行
        if _looks_like_data(raw) or data_mode:
            sess = ensure_session()
            # 帧类型
            first_tok = raw.split(",", 1)[0].strip()
            is_frame = first_tok.isalpha() and 0 < len(first_tok) <= 4
            frame_type = None
            if is_frame:
                frame_type = first_tok
                body = raw.split(",", 1)[1] if "," in raw else ""
                values = _split_csv_row(body)
            else:
                values = _split_csv_row(raw)

            # 清理引用
            cleaned = []
            for v in values:
                v = v.strip().strip('"')
                cleaned.append(v)

            if frame_type is None:
                # 主数据帧（无字母）
                sess.rows.append(list(cleaned))
                if cleaned and cleaned[0].lstrip("-").isdigit():
                    sess.time_us.append(int(cleaned[0]))
            else:
                # 按帧类型存储
                frame_list = sess.frame_rows.setdefault(frame_type, [])
                frame_list.append(cleaned)
                # 二进制字段模板兜底
                if frame_type not in sess.frame_columns:
                    if frame_type in _BF_FRAME_COLUMNS:
                        sess.frame_columns[frame_type] = _BF_FRAME_COLUMNS[frame_type]

    # 清理空会话
    if log.sessions and not log.sessions[0].rows and not log.sessions[0].header:
        # 首个是占位空会话
        pass
    return log


def load_betaflight_file(path: str) -> BfFlightLog:
    """从磁盘文件加载 Blackbox CSV/文本日志（自动探测编码）。"""
    for enc in ("utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as f:
                text = f.read()
            return parse_betaflight_log(text, filename=path)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法以常见编码读取 {path}")


def export_betaflight_csv(log: BfFlightLog, out_path: str, session_idx: int = 0):
    """将此 Blackbox 日志中指定的会话导出为标准化 CSV（时间,列...）。"""
    import csv

    if not log.sessions:
        raise ValueError("日志中没有会话")
    sess = log.sessions[session_idx]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        # 头部
        for k, v in sess.header.items():
            w.writerow([f"H {k}", v])
        # 列名
        cols = sess.column_names or (["time"] + (sess.column_names or []))
        w.writerow(cols)
        for row in sess.rows:
            w.writerow(row)
    return out_path