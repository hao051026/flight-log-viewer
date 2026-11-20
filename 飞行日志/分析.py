# 飞行日志查看器 (Flight Log Viewer)
# Copyright (C) 2026 hao051026 (小冉学长)
# 本项目以 GNU GPL-3.0 许可发布，详见 LICENSE 与 NOTICE 文件。
"""
高层数据模型与统计摘要
======================
为 Web 界面提供统一的、与具体日志格式无关的飞行日志表示与统计输出。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class TimeSeries:
    """一段带时间轴和名称的一维数据，供绘图。"""

    name: str                     # 通道名（如 "gyroADC[0]" / "GPS_altitude"）
    source: str                   # 帧/消息类型来源（如 "I" / "GPS" / "ATT"）
    time_s: np.ndarray            # 时间轴（秒，相对起点）
    values: np.ndarray            # 数值


@dataclass
class FlightSummary:
    """一份日志的顶层统计摘要。"""

    source: str                    # 日志文件名
    format: str                    # "Betaflight" / "INAV" / "ArduPilot"
    firmware: Optional[str] = None
    duration_s: float = 0.0
    sample_count: int = 0
    armed_cycles: int = 0
    max_altitude_m: Optional[float] = None
    max_speed_m_s: Optional[float] = None
    max_current_a: Optional[float] = None
    max_horizontal_accel_g: Optional[float] = None
    battery_min_v: Optional[float] = None
    battery_start_v: Optional[float] = None
    battery_end_v: Optional[float] = None
    channel_report: Dict[str, Tuple[float, float]] = field(default_factory=dict)   # 通道 -> (min, max)

    def as_dict(self) -> Dict[str, Any]:
        d = {
            "source": self.source,
            "format": self.format,
            "firmware": self.firmware,
            "duration_s": round(self.duration_s, 3),
            "sample_count": int(self.sample_count),
            "armed_cycles": int(self.armed_cycles),
            "max_altitude_m": self.max_altitude_m,
            "max_speed_m_s": self.max_speed_m_s,
            "max_current_a": self.max_current_a,
            "max_horizontal_accel_g": self.max_horizontal_accel_g,
            "battery_min_v": self.battery_min_v,
            "battery_start_v": self.battery_start_v,
            "battery_end_v": self.battery_end_v,
            "channel_report": {k: [round(v[0], 3), round(v[1], 3)]
                               for k, v in self.channel_report.items()},
        }
        # 转成 json 安全
        for k, v in list(d.items()):
            if isinstance(v, np.generic):
                d[k] = v.item()
        return d


def _to_float_series(times_us: List[float], vals: List[Any]) -> Optional[TimeSeries]:
    if len(vals) == 0:
        return None
    try:
        f = np.array([float(v) for v in vals], dtype=np.float64)
        t = np.array([float(v) for v in times_us], dtype=np.float64)
    except (ValueError, TypeError):
        return None
    if len(t) == 0:
        return None
    t = (t - t[0]) / 1e6
    return TimeSeries(name="", source="", time_s=t, values=f)


class FlightData:
    """统一的飞行数据容器：由各解析器结果填充。"""

    def __init__(self, summary: FlightSummary, series: List[TimeSeries]):
        self.summary = summary
        self.series = series

    def merged(self, name: str) -> Optional[TimeSeries]:
        """取某一通道在整个日志中的合并时间序列（按时间排序）。"""
        pass


# ----------------------------------------------------------------
# 从 ArduPilot 日志构建摘要与序列
# ----------------------------------------------------------------
def summarize_ardupilot(log) -> FlightSummary:
    from .解析器.阿德解析 import ArduFlightLog

    s = FlightSummary(source=getattr(log, "filename", ""), format="ArduPilot",
                      firmware=log.firmware)
    # 时长：取最高频非头部消息的时间跨度（不同消息可能用不同时间基准，不能混用）
    from collections import Counter
    cnt = Counter(m.name for m in log.messages
                  if m.time is not None and not m.is_header)
    if cnt:
        top_name = cnt.most_common(1)[0][0]
        t2 = [m.time for m in log.messages
              if m.name == top_name and m.time is not None]
        if len(t2) >= 2:
            s.duration_s = (max(t2) - min(t2))
    s.sample_count = sum(1 for m in log.messages if not m.is_header)
    # 解锁周期近似：统计 ARM 相关消息 / armed 字段
    armed_cycles = 0
    for m in log.messages:
        if m.name == "MODE" and m.fields.get("Mode") in (0, 1, 2, 3, 4, 5, 6, 7):  # 粗略
            pass
    s.armed_cycles = max(1, sum(1 for m in log.messages if m.name in ("MODE", "STAT")))
    # 提取常用序列
    series: List[TimeSeries] = []

    # 电池：CURR / BAT（真实 CURR 的 Volt 单位 daV=0.01V、Curr=0.01A，需 /100）
    for mname in ("CURR", "BAT"):
        bt_times, bvals = _collect_ardupilot(log, mname, None)
        if not bt_times:
            continue
        volt_scale = 0.01 if mname == "CURR" else 1.0
        curr_scale = 0.01 if mname == "CURR" else 1.0
        for name, vals in bvals.items():
            if name in ("Volt", "Voltage", "V") and len(vals):
                scaled = [v * volt_scale for v in vals]
                ser = _series_from(bt_times, scaled, name, mname)
                if ser:
                    series.append(ser)
                    s.battery_min_v = float(ser.values.min())
                    s.battery_start_v = float(ser.values[0])
                    s.battery_end_v = float(ser.values[-1])
            elif name in ("Curr", "Current") and len(vals):
                scaled = [v * curr_scale for v in vals]
                s.max_current_a = float(max(scaled))
                ser = _series_from(bt_times, scaled, name, mname)
                if ser:
                    series.append(ser)

    # 高度与速度（GPS Alt/Spd、BARO Alt）
    for mname in ("GPS", "BARO"):
        gt, gvals = _collect_ardupilot(log, mname, None)
        if not gt:
            continue
        for name, vals in gvals.items():
            if len(vals) == 0:
                continue
            ser = _series_from(gt, vals, f"{mname}.{name}", mname)
            if not ser:
                continue
            series.append(ser)
            if name in ("Alt", "GAlt", "RelAlt"):
                mx = float(ser.values.max())
                if s.max_altitude_m is None or mx > s.max_altitude_m:
                    s.max_altitude_m = mx
            if name in ("Spd", "GSpd", "Speed"):
                mx = float(ser.values.max())
                if s.max_speed_m_s is None or mx > s.max_speed_m_s:
                    s.max_speed_m_s = mx

    # IMU 加速度与水平加速度幅值
    accel_ok = False
    for mname in ("IMU", "IMU2", "IMU3"):
        imu_times, imu = _collect_ardupilot(log, mname, ["AccX", "AccY", "AccZ"])
        if not imu_times:
            continue
        for name in ("AccX", "AccY", "AccZ"):
            if name in imu and len(imu[name]):
                ser = _series_from(imu_times, imu[name], f"{mname}.{name}", mname)
                if ser:
                    series.append(ser)
        if all(n in imu for n in ("AccX", "AccY")):
            ax = np.array(imu["AccX"]); ay = np.array(imu["AccY"])
            mag = np.hypot(ax, ay) / 9.80665
            if len(mag):
                s.max_horizontal_accel_g = float(max(mag.max(),
                                            s.max_horizontal_accel_g or 0))

    # ATT 姿态角(度)
    att_times, att = _collect_ardupilot(log, "ATT", None)
    if att_times:
        for name in ("Roll", "Pitch", "Yaw"):
            if name in att and len(att[name]):
                ser = _series_from(att_times, att[name], f"ATT.{name}", "ATT")
                if ser:
                    series.append(ser)

    # 记录各序列通道范围
    for ser in series:
        if len(ser.values):
            s.channel_report.setdefault(ser.name,
                                        (float(ser.values.min()), float(ser.values.max())))
    s.series = series  # 便于访问
    return s


def _collect_ardupilot(log, msg_name: str, keys: Optional[List[str]]) -> Tuple[List[float], Dict[str, List[Any]]]:
    """收集某一消息类型的 (相对时间[s], {field: values})。

    时间优先取 TimeUS(微秒)/TimeMS(毫秒)/time 字段。
    """
    times: List[float] = []
    fields: Dict[str, List[Any]] = {}
    time_keys = ("TimeUS", "TimeMS", "time", "Time")
    for m in log.messages:
        if m.name != msg_name or m.is_header:
            continue
        t = None
        for tk in time_keys:
            if tk in m.fields:
                t = m.fields[tk]
                break
        if t is None:
            continue
        # TimeUS 微秒 -> 秒；TimeMS 毫秒 -> 秒
        if t and m.fields.get("TimeUS") is not None or m.fields.get("TimeMS") is not None:
            pass
        t = float(t)
        if "TimeUS" in m.fields:
            t = t / 1e6
        elif "TimeMS" in m.fields:
            t = t / 1e3
        times.append(t)
        for k, v in m.fields.items():
            if keys and k not in keys:
                continue
            if isinstance(v, (int, float)) and k.lower() not in ("status",):
                fields.setdefault(k, []).append(float(v))
    return times, fields


def _series_from(rel_times: List[float], vals: List[Any], name: str, source: str) -> Optional[TimeSeries]:
    if not vals or len(vals) != len(rel_times):
        return None
    try:
        v = np.array([float(x) for x in vals], dtype=np.float64)
    except (ValueError, TypeError):
        return None
    t = np.array(rel_times, dtype=np.float64)
    if len(t):
        t = t - t[0]
    ser = TimeSeries(name=name, source=source, time_s=t, values=v)
    return ser


# ----------------------------------------------------------------
# 从 Betaflight 日志构建摘要与序列
# ----------------------------------------------------------------
def summarize_betaflight(log) -> FlightSummary:
    s = FlightSummary(source=getattr(log, "filename", ""),
                      format="Betaflight", firmware=log.firmware)
    sess = log.best_session()
    if not sess:
        return s
    s.armed_cycles = len(log.sessions)
    s.sample_count = sum(len(x.rows) for x in log.sessions)
    s.duration_s = sess.duration_s
    series: List[TimeSeries] = []

    # 主帧数值矩阵
    names, mat = sess.numeric_matrix()
    time_us = np.array([float(v) for v in sess.time_us], dtype=np.float64) if sess.time_us else np.zeros(len(mat))
    time_s = (time_us - time_us[0]) / 1e6 if len(time_us) else np.zeros(len(mat))

    for i, nm in enumerate(names):
        vals = mat[:, i]
        ser = TimeSeries(name=nm, source="I", time_s=time_s[:len(vals)], values=vals)
        series.append(ser)
        if len(vals):
            s.channel_report.setdefault(nm, (float(vals.min()), float(vals.max())))

    # 提取电池电压 (vbat), rssi, 油门等
    for nm in ("vbat", "batteryVoltage", "Vbat"):
        if nm in s.channel_report:
            # 找对应序列
            for ser in series:
                if ser.name == nm:
                    s.battery_min_v = float(ser.values.min())
                    s.battery_start_v = float(ser.values[0])
                    s.battery_end_v = float(ser.values[-1])
                    break
            break
    # 电流
    for nm in ("current", "amperage", "Current"):
        for ser in series:
            if ser.name == nm and len(ser.values):
                s.max_current_a = float(ser.values.max())
                break
    # 高度（若存在）
    for nm in ("altitude", "GPS_altitude"):
        for ser in series:
            if ser.name == nm and len(ser.values):
                s.max_altitude_m = float(ser.values.max())
                break
    # GPS 速度
    for nm in ("GPS_speed", "speed"):
        for ser in series:
            if ser.name == nm and len(ser.values):
                s.max_speed_m_s = float(ser.values.max())
                break

    # GPS/磁等附加帧（尽力）
    for ftype in ("GPS", "D"):
        fl = sess.frame_rows.get(ftype, [])
        if fl:
            times = []
            for r in fl:
                try:
                    times.append(float(r[0]))
                except (ValueError, TypeError):
                    times.append(float("nan"))
            ts = np.array(times)
            ts = (ts - ts[0]) / 1e6
            for c, name in enumerate(sess.frame_columns.get(ftype, [])):
                if c == 0:
                    continue
                vals = []
                for r in fl:
                    try:
                        vals.append(float(r[c]))
                    except (ValueError, IndexError, TypeError):
                        vals.append(float("nan"))
                if vals:
                    series.append(TimeSeries(name=name, source=ftype, time_s=ts[:len(vals)], values=np.array(vals)))
    s.series = series
    return s


def _summarize_binary_blackbox(log) -> FlightSummary:
    """二进制 Blackbox 结果（core._BinaryLog）转摘要。"""
    res = log.result
    s = FlightSummary(source=getattr(log, "filename", ""), format="Betaflight(binary)",
                      firmware=res.get("firmware"))
    cols = res.get("columns") or []
    rows = res.get("rows") or []
    s.sample_count = len(rows)
    s.armed_cycles = max(1, res.get("frame_counts", {}).get("S", 0) // 2 + 1)
    # 时间轴：优先 loopIteration 累计，否则用行索引
    series: List[TimeSeries] = []
    if not cols or not rows:
        return s
    n = len(rows)
    time_ser = None
    # 用 loopIteration 推导时间（列 0），不足则用行序
    loops = np.array([float(r[0]) if r and len(r) > 0 else 0.0 for r in rows])
    # 简单单调处理：取正增量累计
    d = np.diff(loops)
    d = np.where(d > 0, d, 1.0)
    t = np.concatenate([[0.0], np.cumsum(d)]) * (128 / 1e6) if res.get("sys", {}).get("frame_interval_i") else np.arange(n)
    s.duration_s = float(t[-1] - t[0])
    # 各列
    for c, name in enumerate(cols):
        if c >= 52:
            continue
        vals = []
        for r in rows:
            try:
                vals.append(float(r[c]) if c < len(r) else 0.0)
            except (ValueError, TypeError):
                vals.append(float("nan"))
        if len(vals) == n:
            v = np.array(vals)
            series.append(TimeSeries(name=name, source="I", time_s=t, values=v))
            if len(v):
                s.channel_report.setdefault(name, (float(v.min()), float(v.max())))
    # 电池
    for nm in ("vbatLatest", "batteryVoltage"):
        for ser in series:
            if ser.name == nm and len(ser.values):
                v = ser.values
                # vbat 单位 0.01V；用中位数附近有效值，避免异常帧污染
                valid = v[np.isfinite(v)]
                if len(valid) == 0:
                    break
                # 只保留 5%~95% 范围（过滤解码失步产生的离群值）
                lo, hi = np.percentile(valid, [2, 98])
                core = valid[(valid >= lo) & (valid <= hi)]
                if len(core):
                    core = core * 0.01
                    s.battery_min_v = float(core.min())
                    s.battery_start_v = float(valid[0]) * 0.01
                    s.battery_end_v = float(valid[-1]) * 0.01
                break
    # GPS（若有）—— Betaflight GPS_altitude 单位 cm(*0.01 m)，GPS_speed cm/s(*0.01 m/s)
    gcols = res.get("gps_columns") or []
    grows = res.get("gps_rows") or []
    if gcols and grows:
        try:
            gi = {name: i for i, name in enumerate(gcols)}
            alt_i = gi.get("GPS_altitude")
            spd_i = gi.get("GPS_speed")
            if alt_i is not None:
                alts = np.array([float(r[alt_i]) * 0.01 for r in grows if alt_i < len(r)])
                alts = alts[np.isfinite(alts)]
                if len(alts):
                    s.max_altitude_m = float(alts.max())
            if spd_i is not None:
                spds = np.array([float(r[spd_i]) * 0.01 for r in grows if spd_i < len(r)])
                spds = spds[np.isfinite(spds)]
                if len(spds):
                    # 过滤明显异常（>100 m/s）
                    spds = spds[spds <= 100]
                    if len(spds):
                        s.max_speed_m_s = float(spds.max())
            # GPS 序列
            gt = np.arange(len(grows))
            if alt_i is not None:
                series.append(TimeSeries(name="GPS_altitude", source="G",
                                         time_s=gt,
                                         values=np.array([float(r[alt_i]) * 0.01 if alt_i < len(r) else 0 for r in grows])))
            if spd_i is not None:
                series.append(TimeSeries(name="GPS_speed", source="G",
                                         time_s=gt,
                                         values=np.array([float(r[spd_i]) * 0.01 if spd_i < len(r) else 0 for r in grows])))
        except Exception:
            pass
    s.series = series
    return s


def summarize(log, format_hint: Optional[str] = None) -> FlightSummary:
    """根据对象类型分派到对应摘要函数。"""
    # 判断类型
    from .解析器.贝塔解析 import BfFlightLog
    from .解析器.阿德解析 import ArduFlightLog
    if isinstance(log, ArduFlightLog):
        return summarize_ardupilot(log)
    if isinstance(log, BfFlightLog):
        return summarize_betaflight(log)
    if type(log).__name__ == "_BinaryLog":
        return _summarize_binary_blackbox(log)
    raise TypeError(f"不支持的日志对象: {type(log)}")


# ================================================================
# 3D 飞行轨迹提取
# ================================================================
# WGS84 椭球常数
_WGS84_A = 6378137.0             # 长半轴 (m)
_WGS84_E2 = 0.0066943799901413165  # 第一偏心率平方

def _ellipsoid_arc_lat(lat_deg: float) -> float:
    """WGS84 在纬度 lat 处，1 度纬度的子午圈弧长（米）。"""
    import math
    r = math.radians(lat_deg)
    sinr = math.sin(r)
    denom = 1.0 - _WGS84_E2 * sinr * sinr
    M = _WGS84_A * (1 - _WGS84_E2) / (denom ** 1.5)
    return M * math.pi / 180.0

def _ellipsoid_arc_lng(lat_deg: float) -> float:
    """WGS84 在纬度 lat 处，1 度经度的卯酉圈弧长（米）。"""
    import math
    r = math.radians(lat_deg)
    sinr = math.sin(r)
    denom = math.sqrt(1.0 - _WGS84_E2 * sinr * sinr)
    N = _WGS84_A / denom
    return N * math.cos(r) * math.pi / 180.0


def 提取轨迹(log) -> Dict[str, Any]:
    """从日志中提取 3D 飞行轨迹点（高精度版）。

    返回:
        {
          "ok": bool,
          "reason": str|None,            # 失败原因
          "points": [[x,y,z], ...],      # 米制相对坐标: x=东, y=北, z=高度
          "times": [t秒, ...],
          "meta": {...,                   # 含精度说明
                   "xy_approx": "WGS84 椭球精确弧长（每点按所在纬度计算）",
                   "z_source": "BARO(气压计)/GPS/0",
                   "z_basis": 高度基准说明,
                   "z_offset_note": 若用 GPS 椭球高的提示}
        }
    经纬度 -> 相对起飞点的米制坐标，采用 WGS84 椭球逐点精确弧长，
    不再使用固定 111320 m/度 的球面近似。
    高度（Z）优先使用气压计(BARO)相对高度（垂直精度高、无椭球高偏移）；
    无气压计时回退 GPS Alt；两种情况都在 meta 中注明基准。
    """
    import math
    from .解析器.阿德解析 import ArduFlightLog
    from .解析器.贝塔解析 import BfFlightLog

    lat: List[float] = []
    lng: List[float] = []
    alt: List[float] = []
    alt_src: List[str] = []
    ts: List[float] = []
    src = "未知"

    # ---------- 收集 ArduPilot GPS 与 BARO ----------
    if isinstance(log, ArduFlightLog):
        # 先收 BARO 时间序列（相对起飞点高度，气压计）
        baro_t: List[float] = []
        baro_z: List[float] = []
        for m in log.messages:
            if m.is_header or m.name != "BARO":
                continue
            f = m.fields
            if "Alt" not in f:
                continue
            t0 = f.get("TimeUS") or f.get("TimeMS")
            if t0 is None:
                continue
            t = float(t0) / 1e6 if f.get("TimeUS") is not None else float(t0) / 1e3
            baro_t.append(t)
            baro_z.append(float(f["Alt"]))
        # baro_z 相对起飞点归零（取第一条为基准，ArduPilot BARO.Alt 通常已相对起飞点）
        if baro_z:
            base = baro_z[0]
            baro_z = [z - base for z in baro_z]
        else:
            base = 0.0

        # GPS 点
        for m in log.messages:
            if m.is_header or m.name != "GPS":
                continue
            f = m.fields
            if "Lat" in f and "Lng" in f and f["Lat"] != 0 and f["Lng"] != 0:
                lat.append(float(f["Lat"]))
                lng.append(float(f["Lng"]))
                if "TimeUS" in f:
                    t = float(f["TimeUS"]) / 1e6
                elif "TimeMS" in f:
                    t = float(f["TimeMS"]) / 1e3
                else:
                    t = float(len(ts))
                ts.append(t)
                # 高度：优先用与当前 GPS 时刻最接近的气压计高度
                if baro_t:
                    # 找最近时间的气压计样本
                    best = min(range(len(baro_t)), key=lambda i: abs(baro_t[i] - t))
                    alt.append(baro_z[best])
                    alt_src.append("BARO")
                elif "Alt" in f:
                    alt.append(float(f["Alt"]))
                    alt_src.append("GPS-Alt")
                elif "RelAlt" in f:
                    alt.append(float(f["RelAlt"]))
                    alt_src.append("GPS-RelAlt")
                else:
                    alt.append(0.0)
                    alt_src.append("0")
        src = "GPS+BARO"

    # ---------- Betaflight CSV ----------
    elif isinstance(log, BfFlightLog):
        for sess in log.sessions:
            cols = sess.column_names
            if "GPS_lat" in cols and "GPS_lon" in cols:
                ilat, ilng = cols.index("GPS_lat"), cols.index("GPS_lon")
                i_alt = cols.index("GPS_altitude") if "GPS_altitude" in cols else None
                for row in sess.rows:
                    try:
                        lt = float(row[ilat]); ln = float(row[ilng])
                    except (ValueError, IndexError):
                        continue
                    if lt == 0 and ln == 0:
                        continue
                    lat.append(lt); lng.append(ln)
                    if i_alt is not None:
                        try:
                            alt.append(float(row[i_alt]) * 0.01)  # cm -> m
                            alt_src.append("GPS-Alt")
                        except (ValueError, IndexError):
                            alt.append(0.0); alt_src.append("0")
                    else:
                        alt.append(0.0); alt_src.append("0")
                if sess.time_us:
                    ts = [t / 1e6 for t in sess.time_us]
                src = "BLACKBOX"

    # 若上面没取到，尝试从 series 中回退寻找 Lat/Lng 配对
    if not lat and hasattr(log, "series") and log.series:
        names = [s.name for s in log.series]
        pairs = [("GPS.Lat", "GPS.Lng"), ("Lat", "Lng"), ("GPS_coord[0]", "GPS_coord[1]")]
        for nlat, nlng in pairs:
            if nlat in names and nlng in names:
                slat = next(s for s in log.series if s.name == nlat)
                slng = next(s for s in log.series if s.name == nlng)
                n = min(len(slat.values), len(slng.values))
                for i in range(n):
                    vl = float(slat.values[i]); vn = float(slng.values[i])
                    if vl == 0 and vn == 0:
                        continue
                    lat.append(vl); lng.append(vn)
                    alt.append(0.0); alt_src.append("0")
                ts = [float(t) for t in slat.time_s]
                src = f"SERIES:{nlat}"
                break

    n = len(lat)
    if n < 2:
        return {"ok": False, "reason": "日志中没有有效的 GPS 坐标数据（需要 Lat/Lng 字段）",
                "points": [], "times": [], "meta": {"count": 0, "source": src}}

    # ---------- 经纬度 -> 米：WGS84 椭球逐点精确弧长 ----------
    lat0, lng0 = lat[0], lng[0]
    pts = []
    # 预计算每个点所在纬度的弧长（弧长随纬度缓慢变化，逐点算保证大跨度下也准）
    for i in range(n):
        mpd_lat = _ellipsoid_arc_lat(lat[i])
        mpd_lng = _ellipsoid_arc_lng(lat[i])
        x = (lng[i] - lng0) * mpd_lng   # 东
        y = (lat[i] - lat0) * mpd_lat   # 北
        z = float(alt[i]) if i < len(alt) else 0.0
        pts.append([round(x, 2), round(y, 2), round(z, 2)])
    if len(ts) != n:
        ts = [float(i) for i in range(n)]

    # ---------- 元信息与精度说明 ----------
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; zs = [p[2] for p in pts]
    z_src_ctr = {}
    for s0 in alt_src:
        z_src_ctr[s0] = z_src_ctr.get(s0, 0) + 1
    z_source = max(z_src_ctr, key=z_src_ctr.get) if z_src_ctr else "0"
    if z_source == "BARO":
        z_basis = "气压计(BARO)相对起飞点高度；垂直精度约 ±0.5~2 m，无椭球高偏移"
    elif z_source.startswith("GPS"):
        z_basis = "GPS 高度(椭球高/相对高)；垂直精度约 ±5~15 m，可能含椭球高系统偏移"
    else:
        z_basis = "无高度传感器数据；Z 轴恒为 0（仅平面轨迹）"

    meta = {
        "count": n,
        "span_xy_m": round(max(max(xs) - min(xs), max(ys) - min(ys)), 1),
        "x_min": round(min(xs), 1), "x_max": round(max(xs), 1),
        "y_min": round(min(ys), 1), "y_max": round(max(ys), 1),
        "z_min": round(min(zs), 1), "z_max": round(max(zs), 1),
        "source": src,
        "start": [pts[0][0], pts[0][1], pts[0][2]],
        "end": [pts[-1][0], pts[-1][1], pts[-1][2]],
        "xy_approx": "WGS84 椭球精确弧长（逐点按所在纬度计算）",
        "z_source": z_source,
        "z_src_distribution": z_src_ctr,
        "z_basis": z_basis,
    }
    return {"ok": True, "reason": None, "points": pts, "times": ts, "meta": meta}


def _cos_deg(d: float) -> float:
    import math
    return math.cos(math.radians(d))