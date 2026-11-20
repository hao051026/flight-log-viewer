# 飞行日志查看器 (Flight Log Viewer)
# Copyright (C) 2026 hao051026 (小冉学长)
# 本项目以 GNU GPL-3.0 许可发布，详见 LICENSE 与 NOTICE 文件。
"""
中文映射：把日志格式名、通道名（英文字段）翻译成中文，用于 Web 界面与命令行展示。
"""

# 日志格式 -> 中文
FORMAT_CN = {
    "ArduPilot": "ArduPilot（自主飞行）",
    "Betaflight": "Betaflight（开源飞控）",
    "Betaflight/INAV": "Betaflight/INAV（开源飞控）",
    "Betaflight(binary)": "Betaflight（二进制黑盒）",
}

# 通道名（字段名） -> 中文
CHANNEL_CN = {
    # 时间 / 迭代
    "time": "时间(微秒)",
    "loopIteration": "循环周期",
    "TimeUS": "时间(微秒)",
    "TimeMS": "时间(毫秒)",
    # 电池 / 电流
    "vbatLatest": "电池电压",
    "vbat": "电池电压",
    "batteryVoltage": "电池电压",
    "Volt": "电池电压",
    "amperageLatest": "电流",
    "current": "电流",
    "amperage": "电流",
    "Curr": "电流",
    # 遥控 / 油门
    "throttle": "油门",
    "rcCommand[0]": "遥控输入-横滚",
    "rcCommand[1]": "遥控输入-俯仰",
    "rcCommand[2]": "遥控输入-偏航",
    "rcCommand[3]": "遥控输入-油门",
    "rssi": "信号强度",
    # 陀螺 / 加速度
    "gyroADC[0]": "陀螺仪-横滚",
    "gyroADC[1]": "陀螺仪-俯仰",
    "gyroADC[2]": "陀螺仪-偏航",
    "gyroUnfilt[0]": "陀螺(未滤波)-横滚",
    "gyroUnfilt[1]": "陀螺(未滤波)-俯仰",
    "gyroUnfilt[2]": "陀螺(未滤波)-偏航",
    "accSmooth[0]": "加速度-横滚",
    "accSmooth[1]": "加速度-俯仰",
    "accSmooth[2]": "加速度-垂直",
    # PID
    "axisP[0]": "PID-P-横滚",
    "axisP[1]": "PID-P-俯仰",
    "axisP[2]": "PID-P-偏航",
    "axisI[0]": "PID-I-横滚",
    "axisI[1]": "PID-I-俯仰",
    "axisI[2]": "PID-I-偏航",
    "axisD[0]": "PID-D-横滚",
    "axisD[1]": "PID-D-俯仰",
    "axisD[2]": "PID-D-偏航",
    "axisF[0]": "PID-FFF-横滚",
    "axisF[1]": "PID-F-俯仰",
    "axisF[2]": "PID-F-偏航",
    # 电机 / 转速
    "motor[0]": "电机1",
    "motor[1]": "电机2",
    "motor[2]": "电机3",
    "motor[3]": "电机4",
    "eRPM[0]": "电机1转速",
    "eRPM[1]": "电机2转速",
    "eRPM[2]": "电机3转速",
    "eRPM[3]": "电机4转速",
    # GPS
    "GPS_numSat": "GPS卫星数",
    "GPS_altitude": "GPS高度",
    "GPS_speed": "GPS速度",
    "GPS_ground_course": "GPS航向",
    "GPS_coord[0]": "GPS纬度",
    "GPS_coord[1]": "GPS经度",
    # 姿态
    "Roll": "横滚角",
    "Pitch": "俯仰角",
    "Yaw": "偏航角",
    "ATT.Roll": "姿态-横滚角",
    "ATT.Pitch": "姿态-俯仰角",
    "ATT.Yaw": "姿态-偏航角",
    # ArduPilot 专用
    "Alt": "高度",
    "Spd": "速度",
    "Lat": "纬度",
    "Lng": "经度",
    "GPS.Alt": "GPS高度",
    "GPS.Spd": "GPS速度",
    "GPS.Lat": "GPS纬度",
    "GPS.Lng": "GPS经度",
    "IMU.AccX": "加速度X",
    "IMU.AccY": "加速度Y",
    "IMU.AccZ": "加速度Z",
    "IMU2.AccX": "IMU2加速度X",
    "IMU2.AccY": "IMU2加速度Y",
    "IMU2.AccZ": "IMU2加速度Z",
    "IMU3.AccX": "IMU3加速度X",
    "IMU3.AccY": "IMU3加速度Y",
    "IMU3.AccZ": "IMU3加速度Z",
    "BARO.Alt": "气压计高度",
    "BARO.Press": "气压",
    "BARO.Temp": "气压计温度",
    "CURR.Curr": "电流",
    # 补充分离词
    "altitude": "高度",
    "GCrs": "航向",
    "VZ": "垂直速度",
    "Press": "气压",
    "Temp": "温度",
    "NSats": "卫星数",
    "HDop": "水平精度因子",
    "RelAlt": "相对高度",
    "GAlt": "GPS海拔",
    "Week": "GPS周",
    "Status": "状态",
    "CRt": "气压变化率",
    "TimeMS": "时间(毫秒)",
    "TimeUS": "时间(微秒)",
    # 序号帧来源
    "I": "主帧",
    "G": "GPS帧",
    "S": "慢帧",
    "P": "差分帧",
    "H": "GPS原点帧",
}


def fmt_name(fmt: str) -> str:
    """日志格式名转中文，未记录的保留原样。"""
    return FORMAT_CN.get(fmt, fmt)


def channel_name(name: str) -> str:
    """通道名转中文；去掉来源前缀后匹配，否则保留原名。"""
    if name in CHANNEL_CN:
        return CHANNEL_CN[name]
    # 尝试去掉「源.」前缀后匹配（如 GPS.TimeMS -> TimeMS）
    if "." in name:
        base = name.split(".", 1)[1]
        if base in CHANNEL_CN:
            return CHANNEL_CN[base]
    return name


def series_label(source: str, name: str) -> str:
    """生成中文的图表序列标签：如「主帧 · 电池电压」。"""
    src_cn = FRAME_SOURCE_CN.get(source, source)
    name_cn = channel_name(name)
    if source:
        return f"{src_cn} · {name_cn}"
    return name_cn


# ============================================================
# 统计参数注解：每个飞行摘要参数的含义说明（用于界面展示）
# ============================================================
PARAM_NOTES = {
    "source": "飞行日志的文件（名字）",
    "format": "日志来自哪一家飞控系统；不同系统记录的数据字段有所不同",
    "firmware": "飞控上运行的固件（程序）名称与版本号",
    "duration_s": "从解锁到停机的飞行总时长",
    "sample_count": "日志中记录了多少个数据点；越多说明记录越详细",
    "armed_cycles": "解锁（启动电机）的次数；每次解锁算一个飞行段",
    "max_altitude_m": "整个飞行中达到的最高高度（海拔/相对高度）",
    "max_speed_m_s": "飞行的最高速度，米每秒（换算成约 ×3.6 即公里每小时）",
    "max_current_a": "主电池输出的最大电流；越大表示耗电越猛",
    "max_horizontal_accel_g": "水平方向的最大加速度，以重力加速度 g 为单位（1g≈9.8米/秒²）",
    "battery_min_v": "飞行中电池电压掉到的最低值；过低说明电池快没电",
    "battery_start_v": "起飞时电池的电压",
    "battery_end_v": "降落后电池的电压",
    "armed_cycles_guess": "预估的解锁次数（依据日志中的模式切换记录）",
}


# ============================================================
# 通道注解：每个数据通道（参数）的含义说明，供悬浮提示展示
# ============================================================
CHANNEL_NOTES = {
    # 时间 / 迭代
    "time": "时间轴：从日志开始算起的时间",
    "loopIteration": "飞控主循环的迭代次数（每次循环约 125~250 微秒）",
    "TimeUS": "时间戳（微秒）",
    "TimeMS": "时间戳（毫秒）",
    # 电池 / 电流
    "vbatLatest": "电池电压（最新采样值）",
    "vbat": "电池电压",
    "batteryVoltage": "电池电压",
    "Volt": "电池电压",
    "amperageLatest": "电池输出电流（最新采样值）",
    "current": "电池输出电流",
    "amperage": "电池输出电流",
    "Curr": "电池输出电流",
    # 遥控 / 油门
    "throttle": "油门杆位置（遥控器输入，1000~2000 为有效范围）",
    "rcCommand[0]": "遥控输入：横滚通道（左右倾斜）",
    "rcCommand[1]": "遥控输入：俯仰通道（前后俯仰）",
    "rcCommand[2]": "遥控输入：偏航通道（机头转动）",
    "rcCommand[3]": "遥控输入：油门通道（动力）",
    "rssi": "接收机信号强度（越大信号越好）",
    # 陀螺 / 加速度
    "gyroADC[0]": "陀螺仪原始数据：横滚角速度（机身左右倾斜的快慢）",
    "gyroADC[1]": "陀螺仪原始数据：俯仰角速度（机身前后俯仰的快慢）",
    "gyroADC[2]": "陀螺仪原始数据：偏航角速度（机头转动的快慢）",
    "gyroUnfilt[0]": "陀螺仪未滤波数据：横滚方向（原始噪声更大）",
    "gyroUnfilt[1]": "陀螺仪未滤波数据：俯仰方向",
    "gyroUnfilt[2]": "陀螺仪未滤波数据：偏航方向",
    "accSmooth[0]": "加速度计滤波后：横滚方向加速度",
    "accSmooth[1]": "加速度计滤波后：俯仰方向加速度",
    "accSmooth[2]": "加速度计滤波后：垂直方向加速度（静止时约 9.8）",
    # PID
    "axisP[0]": "PID 比例项（横滚）：对姿态误差的反应强度；越大越灵敏、越猛",
    "axisP[1]": "PID 比例项（俯仰）：对姿态误差的反应强度",
    "axisP[2]": "PID 比例项（偏航）：对姿态误差的反应强度",
    "axisI[0]": "PID 积分项（横滚）：消除长期误差；越小越稳但不消除漂移",
    "axisI[1]": "PID 积分项（俯仰）",
    "axisI[2]": "PID 积分项（偏航）",
    "axisD[0]": "PID 微分项（横滚）：抑制过快变化、防振荡",
    "axisD[1]": "PID 微分项（俯仰）",
    "axisD[2]": "PID 微分项（偏航）",
    "axisF[0]": "PID 前馈项（横滚）：对杆量变化的提前响应",
    "axisF[1]": "PID 前馈项（俯仰）",
    "axisF[2]": "PID 前馈项（偏航）",
    # 电机 / 转速
    "motor[0]": "电机 1 输出（油门百分比）",
    "motor[1]": "电机 2 输出（油门百分比）",
    "motor[2]": "电机 3 输出（油门百分比）",
    "motor[3]": "电机 4 输出（油门百分比）",
    "eRPM[0]": "电机 1 电子转速（转/分钟）",
    "eRPM[1]": "电机 2 电子转速（转/分钟）",
    "eRPM[2]": "电机 3 电子转速（转/分钟）",
    "eRPM[3]": "电机 4 电子转速（转/分钟）",
    # GPS
    "GPS_numSat": "GPS 锁定卫星数量（≥10 精度较好）",
    "GPS_altitude": "GPS 测出的高度（米）",
    "GPS_speed": "GPS 测出的对地速度（米/秒）",
    "GPS_ground_course": "GPS 航向角（0~360 度）",
    "GPS_coord[0]": "GPS 纬度坐标",
    "GPS_coord[1]": "GPS 经度坐标",
    # 姿态
    "Roll": "横滚角（机身左右倾斜角度，度）",
    "Pitch": "俯仰角（机身前后俯仰角度，度）",
    "Yaw": "偏航角（机头朝向，0~360 度）",
    "ATT.Roll": "姿态：横滚角（机身左右倾斜，度）",
    "ATT.Pitch": "姿态：俯仰角（机身前后俯仰，度）",
    "ATT.Yaw": "姿态：偏航角（机头朝向，度）",
    # ArduPilot 专用
    "Alt": "高度（米）",
    "Spd": "速度（米/秒）",
    "Lat": "纬度坐标",
    "Lng": "经度坐标",
    "GPS.Alt": "GPS 高度（米）",
    "GPS.Spd": "GPS 速度（米/秒）",
    "GPS.Lat": "GPS 纬度",
    "GPS.Lng": "GPS 经度",
    "GPS.NSats": "GPS 卫星数",
    "GPS.HDop": "GPS 水平精度因子（越小越准）",
    "GPS.TimeMS": "GPS 时间戳（毫秒）",
    "GPS.GCrs": "GPS 航向角（度）",
    "GPS.VZ": "GPS 垂直速度（米/秒）",
    "GPS.Week": "GPS 周数（卫星时间）",
    "IMU.AccX": "加速度计 X 轴（前向加速度）",
    "IMU.AccY": "加速度计 Y 轴（侧向加速度）",
    "IMU.AccZ": "加速度计 Z 轴（垂直方向；静止时约等于重力 9.8）",
    "IMU2.AccX": "备用 IMU2 加速度 X",
    "IMU2.AccY": "备用 IMU2 加速度 Y",
    "IMU2.AccZ": "备用 IMU2 加速度 Z",
    "IMU3.AccX": "备用 IMU3 加速度 X",
    "IMU3.AccY": "备用 IMU3 加速度 Y",
    "IMU3.AccZ": "备用 IMU3 加速度 Z",
    "BARO.Alt": "气压计高度（米，随气压变化）",
    "BARO.Press": "大气压强（帕）",
    "BARO.Temp": "气压计温度（摄氏度）",
    "BARO.TimeMS": "气压计时间戳（毫秒）",
    "BARO.CRt": "气压高度变化率",
    "CURR.Curr": "电池电流",
    "CURR.Volt": "电池电压",
    # 补充分离词
    "altitude": "高度（米）",
    "GCrs": "航向角（度）",
    "VZ": "垂直速度（米/秒，负为下降）",
    "Press": "大气压强",
    "Temp": "温度（摄氏度）",
    "NSats": "卫星数量",
    "HDop": "水平精度因子（越小越准）",
    "RelAlt": "相对起飞点的高度（米）",
    "GAlt": "GPS 海拔（米）",
    "Week": "GPS 周数",
    "Status": "传感器/GPS 状态码",
    "CRt": "气压变化率",
    "setpoint[0]": "期望横滚角（飞控想要的角度）",
    "setpoint[1]": "期望俯仰角（飞控想要的角度）",
    "setpoint[2]": "期望偏航角（飞控想要的角度）",
    "setpoint[3]": "期望油门/高度",
    "magADC[0]": "磁力计 X（地磁方向探测）",
    "magADC[1]": "磁力计 Y",
    "magADC[2]": "磁力计 Z",
    "imuQuaternion[0]": "IMU 姿态四元数 w（描述机身空间朝向）",
    "imuQuaternion[1]": "IMU 姿态四元数 x",
    "imuQuaternion[2]": "IMU 姿态四元数 y",
}


def channel_note(name: str) -> str:
    """返回通道的中文注解说明；匹配不到时返回空字符串。"""
    if name in CHANNEL_NOTES:
        return CHANNEL_NOTES[name]
    if "." in name:
        base = name.split(".", 1)[1]
        if base in CHANNEL_NOTES:
            return CHANNEL_NOTES[base]
    return ""


def param_note(key: str) -> str:
    """返回统计参数的中文注解说明；匹配不到时返回空字符串。"""
    return PARAM_NOTES.get(key, "")


FRAME_SOURCE_CN = {
    "I": "主帧",
    "G": "GPS帧",
    "S": "慢帧",
    "P": "差分帧",
    "H": "GPS原点",
    "ATT": "姿态",
    "GPS": "GPS",
    "IMU": "惯性测量",
    "IMU2": "惯性测量2",
    "IMU3": "惯性测量3",
    "BARO": "气压计",
    "CURR": "电池",
    "BAT": "电池",
}