# 飞行日志查看器 (Flight Log Viewer)
# Copyright (C) 2026 hao051026 (小冉学长)
# 本项目以 GNU GPL-3.0 许可发布，详见 LICENSE 与 NOTICE 文件。
"""
Flask Web 界面：加载、解析并可视化飞行日志
==========================================
"""

from __future__ import annotations

import io
import json
import os
import traceback

from flask import Flask, Response, jsonify, render_template, request

from ..分析 import summarize, _series_from
from ..解析器.贝塔解析 import BfFlightLog, load_betaflight_file, BfSession
from ..解析器.阿德解析 import ArduFlightLog, load_ardupilot_file

import numpy as np


def create_app() -> Flask:
    import os as _os
    _here = _os.path.dirname(_os.path.abspath(__file__))
    app = Flask(__name__,
                template_folder=_os.path.join(_here, "模板"),
                static_folder=_os.path.join(_here, "静态文件"))
    app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024  # 256 MB 上限

    # ------------------------------------------------------------
    # 主页
    # ------------------------------------------------------------
    @app.route("/")
    def index():
        return render_template("index.html")

    # ------------------------------------------------------------
    # 上传 + 解析
    # ------------------------------------------------------------
    @app.route("/api/analyze", methods=["POST"])
    def analyze():
        if "file" not in request.files:
            return jsonify({"error": "未收到文件"}), 400
        f = request.files["file"]
        filename = f.filename or "log"
        raw = f.read()
        if len(raw) == 0:
            return jsonify({"error": "空文件"}), 400

        # 探测格式：扩展名 + 内容
        ext = os.path.splitext(filename)[1].lower()
        note = {}
        try:
            if ext in (".bin", ".log"):
                log, fmt, note["kind"] = parse_ardupilot_bytes(raw, filename), "ArduPilot", "ardupilot"
            elif ext in (".bbl", ".bfl"):
                log, fmt, note["kind"] = _parse_blackbox_bytes(raw, filename)
            else:
                # 内容探测
                head = raw[:400]
                if b"\xa3\x95" in head:
                    log, fmt, note["kind"] = parse_ardupilot_bytes(raw, filename), "ArduPilot", "ardupilot"
                elif head.startswith(b"H Product:Blackbox"):
                    log, fmt, note["kind"] = _parse_blackbox_bytes(raw, filename)
                else:
                    return jsonify({"error": "无法识别日志格式"}), 400

            sumry = summarize(log)

            # 中文化格式名与通道名，并携带注解
            from ..中文映射 import fmt_name, channel_name, param_note
            fmt_cn = fmt_name(fmt)
            sum_dict = sumry.as_dict()
            sum_dict["format"] = fmt_cn
            ch = sum_dict.get("channel_report") or {}
            sum_dict["channel_report"] = {channel_name(k): v for k, v in ch.items()}
            # 统计参数中文注解（key -> 说明）
            sum_dict["param_notes"] = {k: param_note(k) for k in sum_dict.keys()}

            # 3D 飞行轨迹（经纬度+高度 -> 相对米制坐标）
            from ..分析 import 提取轨迹
            try:
                track = 提取轨迹(log)
            except Exception:
                track = {"ok": False, "reason": "轨迹提取失败", "points": [], "times": [], "meta": {"count": 0}}

            resp = {
                "ok": True,
                "format": fmt_cn,
                "summary": sum_dict,
                "series": _serialize_series(getattr(sumry, "series", [])),
                "track": track,
                "meta": note,
                "message_names": _message_names(log),
                "sessions": _session_overview(log),
            }
            return jsonify(resp)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": f"解析失败: {e}", "trace": traceback.format_exc()}), 500

    # ------------------------------------------------------------
    # 辅助：会话概览（Blackbox） / 消息类型（ArduPilot）
    # ------------------------------------------------------------
    def _message_names(log) -> list:
        if isinstance(log, ArduFlightLog):
            return log.message_names()
        if isinstance(log, BfFlightLog):
            return [f"frame:{k}" for k in (log.sessions[0].frame_columns.keys() if log.sessions else [])]
        return []

    def _session_overview(log) -> list:
        out = []
        if isinstance(log, BfFlightLog):
            for i, sess in enumerate(log.sessions):
                out.append({
                    "index": i + 1,
                    "rows": len(sess.rows),
                    "duration_s": round(sess.duration_s, 3),
                    "frames": {k: len(v) for k, v in sess.frame_rows.items()},
                    "columns": sess.column_names[:8],
                })
        return out

    return app


def parse_ardupilot_bytes(raw: bytes, filename: str) -> ArduFlightLog:
    from ..解析器.阿德解析 import parse_ardupilot_log as pa
    return pa(raw, filename=filename)


def parse_betaflight_bytes(raw: bytes, filename: str) -> BfFlightLog:
    text = raw.decode("utf-8", errors="replace")
    from ..解析器.贝塔解析 import parse_betaflight_log as pb
    return pb(text, filename=filename)


def _parse_blackbox_bytes(raw: bytes, filename: str):
    """解析 Blackbox 日志：优先二进制，文本字段名(fieldnames) 走文本。"""
    from ..核心 import _BinaryLog
    from ..解析器.二进制黑盒解析 import parse_binary_blackbox
    # 判断是否二进制：header 含 'H Field <X> name' 且无 'fieldnames' -> 二进制
    head = raw[:2000]
    is_text_csv = b"fieldnames" in head
    if is_text_csv:
        return parse_betaflight_bytes(raw, filename), "Betaflight/INAV", "betaflight"
    # 尝试二进制解析
    try:
        result = parse_binary_blackbox(raw)
        if result.get("columns") or result.get("frame_counts"):
            return _BinaryLog(result, filename), "Betaflight(binary)", "blackbox_binary"
    except Exception:
        pass
    # 回退文本
    return parse_betaflight_bytes(raw, filename), "Betaflight/INAV", "betaflight"


def _serialize_series(series) -> list:
    """把 TimeSeries 列表转成 JSON（限制点数避免过大）。"""
    from ..中文映射 import channel_name, series_label, channel_note
    out = []
    for ser in series:
        t = ser.time_s
        v = ser.values
        if len(t) == 0:
            continue
        # 降采样到最多 2000 点
        step = max(1, int(np.floor(len(t) / 2000)))
        ts = t[::step].tolist()
        vs = v[::step]
        # nan 转 null
        vs = [None if (isinstance(x, float) and np.isnan(x)) else x for x in vs]
        out.append({
            "name": ser.name,
            "source": ser.source,
            "cn_name": channel_name(ser.name),
            "label": series_label(ser.source, ser.name),
            "note": channel_note(ser.name),   # 通道中文注解
            "time": ts,
            "values": vs,
        })
    return out


APP = create_app()

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="FlightLogViewer Web 界面")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    print(f"FlightLogViewer 启动于 http://{args.host}:{args.port}")
    APP.run(host=args.host, port=args.port, debug=False)