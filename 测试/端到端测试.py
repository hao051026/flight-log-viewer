# 飞行日志查看器 (Flight Log Viewer)
# Copyright (C) 2026 hao051026 (小冉学长)
# 本项目以 GNU GPL-3.0 许可发布，详见 LICENSE 与 NOTICE 文件。
#!/usr/bin/env python3
"""
端到端验证脚本：解析样例日志、校验数据、验证 CSV 导出与 Web API。
运行：
    python tests/test_e2e.py
"""

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "样例")


def test_ardupilot(data):
    from 飞行日志.解析器.阿德解析 import parse_ardupilot_log, export_ardupilot_csv
    log = parse_ardupilot_log(data, filename="样例阿德日志.bin")
    assert len(log.messages) > 0, "应该解析出消息"
    assert "GPS" in log.message_names() and "IMU" in log.message_names(), "应含 GPS/IMU 消息"
    imu = [m for m in log.messages if m.name == "IMU"][5]
    assert abs(imu.fields["AccZ"] - 9.8) < 1, f"AccZ 应接近重力 {imu.fields['AccZ']}"
    # 导出
    out = os.path.join(SAMPLES, "_test_ardu_gps.csv")
    export_ardupilot_csv(log, out, "GPS")
    assert os.path.exists(out)
    print("[PASS]  ArduPilot 解析与导出通过  (消息", len(log.messages), "条)")


def test_betaflight(data):
    from 飞行日志.解析器.贝塔解析 import parse_betaflight_log, export_betaflight_csv
    log = parse_betaflight_log(data.decode("utf-8"), filename="样例贝塔日志.csv")
    assert len(log.sessions) >= 1, "应至少 1 个会话"
    sess = log.best_session()
    assert len(sess.rows) > 0, "应有数据行"
    assert "vbat" in sess.column_names, "应识别 vbat 列"
    out = os.path.join(SAMPLES, "_test_bf.csv")
    export_betaflight_csv(log, out)
    assert os.path.exists(out)
    print("[PASS]  Betaflight 解析与导出通过  (行", len(sess.rows), ", 会话", len(log.sessions), ")")


def test_analysis_load():
    from 飞行日志.核心 import load_any, summarize_any
    for fname in ("样例阿德日志.bin", "样例贝塔日志.csv"):
        log = load_any(os.path.join(SAMPLES, fname))
        s = summarize_any(log)
        d = s.as_dict()
        assert len(s.series) > 0, f"{fname} 应有序列"
        assert d["sample_count"] > 0, f"{fname} 应有采样"
        print(f"[PASS]  摘要 {fname}: {d['format']}, 时长 {d['duration_s']}s, "
              f"序列 {len(s.series)} 条, "
              f"BattMin {d['battery_min_v']}V")


def test_web_api():
    from 飞行日志.网页.应用 import create_app
    app = create_app()
    c = app.test_client()
    assert c.get("/").status_code == 200, "主页应 200"
    for fname in ("样例阿德日志.bin", "样例贝塔日志.csv"):
        with open(os.path.join(SAMPLES, fname), "rb") as f:
            r = c.post("/api/analyze",
                       data={"file": (io.BytesIO(f.read()), fname)},
                       content_type="multipart/form-data")
        d = r.get_json()
        assert r.status_code == 200 and d.get("ok"), f"{fname} API 应成功: {d.get('error')}"
        assert len(d["series"]) > 0, f"{fname} 应返回序列"
        print(f"[PASS]  Web API {fname}: {d['format']}, {len(d['series'])} 序列")


def main():
    # 样例需先生成
    import subprocess
    gen = os.path.join(SAMPLES, "生成样例.py")
    subprocess.run([sys.executable, gen], check=True, capture_output=True)

    with open(os.path.join(SAMPLES, "样例阿德日志.bin"), "rb") as f:
        test_ardupilot(f.read())
    with open(os.path.join(SAMPLES, "样例贝塔日志.csv"), "rb") as f:
        test_betaflight(f.read())
    test_analysis_load()
    test_web_api()
    test_real_logs()
    print("\n[ALL PASS]  全部端到端验证通过")


def test_real_logs():
    """验证 real_logs/ 下的真实日志（若存在）。"""
    realdir = os.path.join(ROOT, "真实日志")
    if not os.path.isdir(realdir):
        print("(无 real_logs 目录，跳过真实日志测试)")
        return
    from 飞行日志.核心 import load_any, summarize_any
    ran = False
    for fname in ("阿德飞行日志.bin", "真实贝塔黑盒.BBL"):
        p = os.path.join(realdir, fname)
        if not os.path.exists(p):
            continue
        ran = True
        log = load_any(p)
        s = summarize_any(log)
        d = s.as_dict()
        assert len(s.series) > 0, f"{fname} 应有序列"
        assert d["sample_count"] > 0, f"{fname} 应有采样"
        print(f"[PASS] 真实日志 {fname}: {d['format']}, "
              f"{d['sample_count']} 采样, {len(s.series)} 序列, "
              f"电池 {d['battery_start_v']}->{d['battery_end_v']}V, "
              f"最高海拔 {d['max_altitude_m']}m")
    if not ran:
        print("(real_logs 目录为空，跳过)")


if __name__ == "__main__":
    main()