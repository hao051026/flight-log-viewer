# 飞行日志查看器 (Flight Log Viewer)
# Copyright (C) 2026 hao051026 (小冉学长)
# 本项目以 GNU GPL-3.0 许可发布，详见 LICENSE 与 NOTICE 文件。
"""
Betaflight / Cleanflight / INAV Blackbox **二进制帧解码器**
============================================================

实现黑盒二进制日志的帧级解码，算法忠实移植自
betaflight/blackbox-tools 的 parser.c / decoders.c / stream.c。

参考:
  - stream.c: 变长整型(UnsignedVB/SignedVB+ZigZag)、按位读取、ByteAlign
  - decoders.c: TAG8_4S16 / TAG2_3S32 / TAG8_8SVB / EliasDelta/Gamma
  - parser.c: applyPrediction 与 parseFrame

每条二进制记录以一个帧类型字符开始（I/G/H/S/E/P...），随后是各字段的编码数据。
字段的 predictor / encoding / signed 由日志头 `H Field <X> name:...`、
`H Field <X> signed:...`、`H Field <X> predictor:...`、`H Field <X> encoding:...`
提供。主帧 I 还要配合慢帧 S(P帧间隔) 维持 previous/previous2 历史。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------
# 编码类型枚举
# ---------------------------------------------------------------
ENC_SIGNED_VB = 0
ENC_UNSIGNED_VB = 1
ENC_NEG_14BIT = 3
ENC_ELIAS_DELTA_U32 = 4
ENC_ELIAS_DELTA_S32 = 5
ENC_TAG8_8SVB = 6
ENC_TAG2_3S32 = 7
ENC_TAG8_4S16 = 8
ENC_NULL = 9
ENC_ELIAS_GAMMA_U32 = 10
ENC_ELIAS_GAMMA_S32 = 11

# 预测器
PRED_0 = 0
PRED_PREVIOUS = 1
PRED_STRAIGHT_LINE = 2
PRED_AVERAGE_2 = 3
PRED_MINTHROTTLE = 4
PRED_MOTOR_0 = 5
PRED_INC = 6
PRED_HOME_COORD = 7
PRED_1500 = 8
PRED_VBATREF = 9
PRED_LAST_MAIN_FRAME_TIME = 10
PRED_MINMOTOR = 11
PRED_HOME_COORD_1 = 256


class BitStream:
    """按字节 + 可选按位读取的流。"""

    __slots__ = ("data", "pos", "bit_pos", "eof")

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.bit_pos = 7  # CHAR_BIT-1，0 表示位对齐已完成后的回绕
        self.eof = False

    def _byte_aligned(self):
        return self.bit_pos == 7

    def read_byte(self) -> Optional[int]:
        if self.pos >= len(self.data):
            self.eof = True
            return None
        b = self.data[self.pos]
        self.pos += 1
        return b

    def byte_align(self):
        if self.bit_pos != 7:
            self.bit_pos = 7
            self.pos += 1

    def read_unsigned_vb(self) -> int:
        result = 0
        shift = 0
        for _ in range(5):
            c = self.read_byte()
            if c is None:
                return 0
            result |= (c & ~0x80) << shift
            if c < 128:
                return result
            shift += 7
        return 0

    def read_signed_vb(self) -> int:
        return _zigzag(self.read_unsigned_vb())

    def read_bits(self, num_bits: int) -> int:
        result = 0
        for _ in range(num_bits):
            if self.pos >= len(self.data):
                self.eof = True
                return 0
            # 从当前字节 bit_pos 位读 1 bit
            b = self.data[self.pos]
            result = (result << 1) | ((b >> self.bit_pos) & 0x01)
            if self.bit_pos == 0:
                self.pos += 1
                self.bit_pos = 7
            else:
                self.bit_pos -= 1
        return result

    def read_bit(self) -> int:
        return self.read_bits(1)


def _zigzag(u: int) -> int:
    """ZigZag 解码（带符号的 varint 反转）。"""
    return (u >> 1) ^ -(u & 1)


def _sign_extend(value: int, bits: int) -> int:
    """把低 bits 位当作有符号数做符号扩展。"""
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


# ---------------------------------------------------------------
# 分组编码解码（decoders.c）
# ---------------------------------------------------------------
def _read_tag2_3s32(stream: BitStream) -> List[int]:
    lead = stream.read_byte()
    if lead is None:
        return [0, 0, 0]
    vals = [0, 0, 0]
    selector = lead >> 6
    if selector == 0:  # 2-bit fields
        for i in range(3):
            vals[i] = _sign_extend((lead >> (4 - 2 * i)) & 0x03, 2)
    elif selector == 1:  # 4-bit fields
        vals[0] = _sign_extend(lead & 0x0F, 4)
        b1 = stream.read_byte() or 0
        vals[1] = _sign_extend(b1 >> 4, 4)
        vals[2] = _sign_extend(b1 & 0x0F, 4)
    elif selector == 2:  # 6-bit fields (每字节一个)
        vals[0] = _sign_extend(lead & 0x3F, 6)
        for i in (1, 2):
            b = stream.read_byte() or 0
            vals[i] = _sign_extend(b & 0x3F, 6)
    else:  # selector 3: 每字段 8/16/24/32 位，由 lead 低6位两个一组决定
        sel = lead & 0x3F
        for i in range(3):
            sz = sel & 0x03
            if sz == 0:
                vals[i] = _sign_extend(stream.read_byte() or 0, 8)
            elif sz == 1:
                b1 = stream.read_byte() or 0
                b2 = stream.read_byte() or 0
                vals[i] = _sign_extend(b1 | (b2 << 8), 16)
            elif sz == 2:
                b1 = stream.read_byte() or 0
                b2 = stream.read_byte() or 0
                b3 = stream.read_byte() or 0
                vals[i] = _sign_extend(b1 | (b2 << 8) | (b3 << 16), 24)
            else:
                vals[i] = (stream.read_byte() or 0) | ((stream.read_byte() or 0) << 8) | \
                          ((stream.read_byte() or 0) << 16) | ((stream.read_byte() or 0) << 24)
            sel >>= 2
    return vals


def _read_tag8_4s16_v2(stream: BitStream) -> List[int]:
    """Betaflight 现代容器 (data version 2)。"""
    selector = stream.read_byte()
    values = [0, 0, 0, 0]
    buffer = 0
    nibble_index = 0
    for i in range(4):
        sel = selector & 0x03
        if sel == 0:  # ZERO
            values[i] = 0
        elif sel == 1:  # 4-bit
            if nibble_index == 0:
                b = stream.read_byte()
                buffer = b or 0
                values[i] = _sign_extend(buffer >> 4, 4)
                nibble_index = 1
            else:
                values[i] = _sign_extend(buffer & 0x0F, 4)
                nibble_index = 0
        elif sel == 2:  # 8-bit
            if nibble_index == 0:
                values[i] = _sign_extend(stream.read_byte() or 0, 8)
            else:
                char1 = buffer << 4
                buf2 = stream.read_byte() or 0
                char1 |= buf2 >> 4
                values[i] = _sign_extend(char1, 8)
                buffer = buf2
                nibble_index = 0
        else:  # 16-bit
            if nibble_index == 0:
                b1 = stream.read_byte() or 0
                b2 = stream.read_byte() or 0
                vals = b1 | (b2 << 8)
                buffer = b2
                values[i] = ((vals & 0xFF) ^ 8) - 8 if False else _sign_extend(vals & 0xFFFF, 16)
            else:
                char1 = stream.read_byte() or 0
                char2 = stream.read_byte() or 0
                vals = (buffer << 12) | (char1 << 4) | (char2 >> 4)
                values[i] = _sign_extend(vals & 0xFFFF, 16)
                buffer = char2
                nibble_index = 0
        selector >>= 2
    return values


def _read_tag8_4s16_v1(stream: BitStream) -> List[int]:
    selector = stream.read_byte()
    values = [0, 0, 0, 0]
    i = 0
    while i < 4:
        sel = selector & 0x03
        if sel == 0:
            values[i] = 0
            i += 1
        elif sel == 1:  # 两个 4-bit 字段
            combined = stream.read_byte() or 0
            values[i] = _sign_extend(combined & 0x0F, 4)
            if i + 1 < 4:
                values[i + 1] = _sign_extend(combined >> 4, 4)
            i += 2
            selector >>= 2
            continue
        elif sel == 2:
            values[i] = _sign_extend(stream.read_byte() or 0, 8)
            i += 1
        else:
            b1 = stream.read_byte() or 0
            b2 = stream.read_byte() or 0
            values[i] = _sign_extend(b1 | (b2 << 8), 16)
            i += 1
        selector >>= 2
    return values


def _read_tag8_8svb(stream: BitStream, group_count: int) -> List[int]:
    values = [0] * group_count
    if group_count == 1:
        values[0] = stream.read_signed_vb()
        return values
    header = stream.read_byte() or 0
    for i in range(min(8, group_count)):
        if header & 0x01:
            values[i] = stream.read_signed_vb()
        else:
            values[i] = 0
        header >>= 1
    return values


def _read_elias_gamma_u32(stream: BitStream) -> int:
    val_bits = 0
    while val_bits <= 32 and stream.read_bit() == 0:
        val_bits += 1
    if stream.eof or val_bits > 32:
        return 0
    if val_bits > 0:
        low = stream.read_bits(val_bits - 1)
    else:
        low = 0
    result = (1 << (val_bits - 1)) | low if val_bits > 0 else 0
    if val_bits == 0 and result == 0:
        return 0
    if result == 0xFFFFFFFF:
        esc = stream.read_bit()
        return 0xFFFFFFFF - 1 if esc == 0 else 0xFFFFFFFF
    return result - 1


def _read_elias_delta_u32(stream: BitStream) -> int:
    length_val_bits = 0
    while length_val_bits <= 32 and stream.read_bit() == 0:
        length_val_bits += 1
    if stream.eof or length_val_bits > 32:
        return 0
    length_low = stream.read_bits(length_val_bits)
    length = ((1 << length_val_bits) | length_low) - 1
    if length > 32:
        return 0
    result_low = stream.read_bits(length)
    result = (1 << length) | result_low if length > 0 else 0
    if result == 0xFFFFFFFF:
        esc = stream.read_bit()
        return 0xFFFFFFFF - 1 if esc == 0 else 0xFFFFFFFF
    return result - 1


# ---------------------------------------------------------------
# 帧缓冲区：按二进制帧类型维护帧定义
# ---------------------------------------------------------------
class FrameDef:
    __slots__ = ("frame_type", "names", "signed_", "widths", "predictor",
                 "encoding", "field_count")

    def __init__(self, frame_type: str, names: List[str], signed_: List[int],
                 widths: List[int], predictor: List[int], encoding: List[int]):
        self.frame_type = frame_type
        self.names = names
        self.signed_ = signed_
        self.widths = widths
        self.predictor = predictor
        self.encoding = encoding
        self.field_count = len(names)


class DecoderState:
    """跨帧维护历史状态。"""

    __slots__ = ("frame_defs", "history", "gps_home", "prev_frame",
                 "prev2_frame", "last_gps", "last_slow", "main_history_valid",
                 "last_main_frame_time", "last_main_iteration", "sys_cfg",
                 "main_frame_index", "frame_p_num", "frame_p_denom",
                 "frame_interval_i", "last_skipped", "main_history")

    def __init__(self):
        self.frame_defs: Dict[str, FrameDef] = {}
        self.history = [None, None, None]  # current, previous, previous2 (主帧)
        self.gps_home = None
        self.prev_frame = None
        self.prev2_frame = None
        self.last_gps = None
        self.last_slow = None
        self.main_history_valid = False
        self.last_main_frame_time = None
        self.last_main_iteration = 0
        self.sys_cfg: Dict = {}
        self.main_frame_index = 0
        self.frame_p_num = 1
        self.frame_p_denom = 1
        self.frame_interval_i = 1
        self.last_skipped = 0


def _apply_prediction(enc_value: int, predictor: int, field_index: int,
                      current: List[int], previous: Optional[List[int]],
                      previous2: Optional[List[int]], state: DecoderState) -> int:
    """mirror applyPrediction."""
    value = enc_value
    if predictor == PRED_0:
        pass
    elif predictor == PRED_MINTHROTTLE:
        value += state.sys_cfg.get("minthrottle", 0)
    elif predictor == PRED_1500:
        value += 1500
    elif predictor == PRED_MOTOR_0:
        # 找到 motor[0] 索引
        idx = _find_field_index(state, "I", "motor[0]")
        if idx is not None and idx < len(current):
            value += current[idx]
    elif predictor == PRED_VBATREF:
        value += state.sys_cfg.get("vbatref", 0)
    elif predictor == PRED_PREVIOUS:
        if previous is not None and field_index < len(previous):
            value += previous[field_index]
    elif predictor == PRED_STRAIGHT_LINE:
        if previous is not None and previous2 is not None and field_index < len(previous):
            value += 2 * previous[field_index] - (previous2[field_index] if field_index < len(previous2) else 0)
    elif predictor == PRED_AVERAGE_2:
        if previous is not None and previous2 is not None and field_index < len(previous):
            value += (previous[field_index] + previous2[field_index]) // 2
    elif predictor == PRED_HOME_COORD:
        if state.gps_home:
            idx = _find_field_index(state, "H", "GPS_home[0]")
            if idx is not None and idx < len(state.gps_home):
                value += state.gps_home[idx]
    elif predictor == PRED_HOME_COORD_1:
        if state.gps_home:
            idx = _find_field_index(state, "H", "GPS_home[1]")
            if idx is not None and idx < len(state.gps_home):
                value += state.gps_home[idx]
    elif predictor == PRED_LAST_MAIN_FRAME_TIME:
        if state.last_main_frame_time is not None:
            value += state.last_main_frame_time
    elif predictor == PRED_MINMOTOR:
        value += state.sys_cfg.get("motorOutputLow", 1000)
    else:
        # 已知但不需要特判的预测器（如不可能出现在含该字段的主流中）——忽略
        pass
    return value


def _find_field_index(state: DecoderState, frame_type: str, name: str) -> Optional[int]:
    fd = state.frame_defs.get(frame_type)
    if not fd:
        return None
    for i, nm in enumerate(fd.names):
        if nm == name:
            return i
    return None


def decode_frame(stream: BitStream, frame_type: str, state: DecoderState,
                 previous: Optional[List[int]], previous2: Optional[List[int]],
                 skipped_frames: int = 0) -> Optional[List[int]]:
    """解码一个二进制帧。返回字段值列表（原始 int），失败返回 None。"""
    fd = state.frame_defs.get(frame_type)
    if not fd:
        return None
    frame = [0] * fd.field_count
    predictor = fd.predictor
    encoding = fd.encoding
    signed = fd.signed_
    widths = fd.widths

    i = 0
    try:
        while i < fd.field_count:
            if predictor[i] == PRED_INC:
                frame[i] = skipped_frames + 1
                if previous is not None:
                    frame[i] += previous[i]
                i += 1
                continue

            values = [0] * 8
            enc = encoding[i]
            if enc == ENC_SIGNED_VB:
                stream.byte_align()
                value = stream.read_signed_vb()
            elif enc == ENC_UNSIGNED_VB:
                stream.byte_align()
                value = stream.read_unsigned_vb()
            elif enc == ENC_NEG_14BIT:
                stream.byte_align()
                value = -_sign_extend(stream.read_unsigned_vb(), 14)
            elif enc == ENC_TAG8_4S16:
                stream.byte_align()
                values = _read_tag8_4s16_v2(stream) if state.sys_cfg.get("dataVersion", 2) >= 2 \
                    else _read_tag8_4s16_v1(stream)
                for j in range(4):
                    if i >= fd.field_count:
                        break
                    pred = predictor[i] if i < len(predictor) else PRED_0
                    frame[i] = _apply_prediction(values[j], pred, i, frame, previous, previous2, state)
                    i += 1
                continue
            elif enc == ENC_TAG2_3S32:
                stream.byte_align()
                values = _read_tag2_3s32(stream)
                for j in range(3):
                    if i >= fd.field_count:
                        break
                    frame[i] = _apply_prediction(values[j], predictor[i], i, frame, previous, previous2, state)
                    i += 1
                continue
            elif enc == ENC_TAG8_8SVB:
                stream.byte_align()
                group_count = 1
                for j in range(i + 1, min(i + 8, fd.field_count)):
                    if encoding[j] != ENC_TAG8_8SVB:
                        break
                    group_count += 1
                values = _read_tag8_8svb(stream, group_count)
                for j in range(group_count):
                    if i >= fd.field_count:
                        break
                    frame[i] = _apply_prediction(values[j], predictor[i], i, frame, previous, previous2, state)
                    i += 1
                continue
            elif enc == ENC_ELIAS_DELTA_U32:
                value = _read_elias_delta_u32(stream)
                stream.byte_align()
            elif enc == ENC_ELIAS_DELTA_S32:
                value = _zigzag(_read_elias_delta_u32(stream))
                stream.byte_align()
            elif enc == ENC_ELIAS_GAMMA_U32:
                value = _read_elias_gamma_u32(stream)
                stream.byte_align()
            elif enc == ENC_ELIAS_GAMMA_S32:
                value = _zigzag(_read_elias_gamma_u32(stream))
                stream.byte_align()
            elif enc == ENC_NULL:
                value = 0
            else:
                raise ValueError(f"未支持的编码 {enc}")

            value = _apply_prediction(value, predictor[i], i, frame, previous, previous2, state)
            # 按字段宽度截断 (fieldWidth != 8 -> 32bit sign extend 逻辑)
            if widths and i < len(widths) and widths[i] != 8:
                if signed[i]:
                    value = _sign_extend(value & 0xFFFFFFFF, 32)
                else:
                    value = value & 0xFFFFFFFF
            frame[i] = value
            i += 1
    except Exception:
        # 解码中途异常/越界 -> 帧损坏
        return frame  # 返回已解部分（或部分）
    return frame


def make_bit_stream(data: bytes) -> BitStream:
    return BitStream(data)


# ---------------------------------------------------------------
# 高层：解析一个二进制 Blackbox 日志（单会话）成时间序列
# ---------------------------------------------------------------
FRAME_TYPES = "IPGHS"  # I=主帧 P=差分帧 G=GPS H=GPS home S=慢帧  (E 事件单独)

# 已知帧字母字节值，用于帧边界发现
def _is_frame_marker(b: int) -> bool:
    return b in (ord('I'), ord('P'), ord('G'), ord('H'), ord('S'), ord('E'))


def _parse_field_defs(header_lines: List[str], states: List) -> List[FrameDef]:
    """从 'Field X name/signed/predictor/encoding' header 行构建各帧定义。

    返回按帧字母序的 FrameDef 列表；同时把 I 的结构复制给 P。
    """
    # 收集每个帧字母的 4 类数组
    parts: Dict[str, Dict[str, List]] = {}
    for ln in header_lines:
        if not ln.startswith("Field "):
            continue
        # 格式: H Field I name:loopIteration,...
        body = ln[len("Field "):]
        ft = body[0]
        rest = body[2:]  # "name:..." 
        if ":" not in rest:
            continue
        kind, val = rest.split(":", 1)
        parts.setdefault(ft, {})[kind] = [x.strip() for x in val.split(",") if x.strip()]
    # 若已复制到 P 的不必重复，构建
    defs: Dict[str, FrameDef] = {}
    for ft in FRAME_TYPES:
        p = parts.get(ft)
        if not p:
            continue
        names = p.get("name") or []
        if not names:
            continue
        n = len(names)
        signed = [int(x) for x in (p.get("signed") or ["0"] * n)[:n]]
        widths = [32] * n  # Blackbox 字段默认 32 位（scaling 靠 signed / predictor）
        pred = [int(x) for x in (p.get("predictor") or ["0"] * n)[:n]]
        enc = [int(x) for x in (p.get("encoding") or ["0"] * n)[:n]]
        d = FrameDef(ft, names, signed, widths, pred, enc)
        defs[ft] = d
    # 若 P 未定义而 I 有，复制 I 结构给 P（Betaflight 中 P 复用 I 字段）
    if "P" not in defs and "I" in defs:
        di = defs["I"]
        defs["P"] = FrameDef("P", list(di.names), list(di.signed_), list(di.widths),
                             list(di.predictor), list(di.encoding))
    # 修正 G 帧的 HOME_COORD 第二个字段
    if "G" in defs:
        gd = defs["G"]
        for i in range(1, gd.field_count):
            if gd.predictor[i - 1] == PRED_HOME_COORD and gd.predictor[i] == PRED_HOME_COORD:
                gd.predictor[i] = PRED_HOME_COORD_1
    return defs


def parse_binary_blackbox(data: bytes):
    """解析一个完整的二进制 Blackbox 日志数据。

    返回 dict:
      - firmware, craft, frame_interval, p_ratio, frame_counts
      - series: {channel_name: [values]} / samples: 统一时间轴 list
      - data_rows: 主帧每行的命名数值
      - session_count
    """
    # 定位 header（首个 "H Product"）位置
    # header 是纯文本，数据段是二进制。用 'H\r\n'/'H\n' 行分隔。
    raw = data
    # 找 header 结束位置：首个非 "H " 开头的行（即第一帧数据字头）
    # 用逐行（按 \n）解析 header
    idx = 0
    header_lines: List[str] = []
    # 以换行分割
    lines_raw = []
    start = 0
    newline = b"\n"
    while True:
        nl = raw.find(newline, start)
        if nl < 0:
            break
        line = raw[start:nl]
        lines_raw.append(line)
        start = nl + 1
        if not line.startswith(b"H "):   # 数据行
            # 数据线可能在 header 中穿插（如空行后）？ 记录数据起始
            break
    header_lines_text = []
    for ln in lines_raw:
        if ln.startswith(b"H "):
            header_lines_text.append(ln[1:].decode("latin-1", "replace"))  # 去掉 'H'
        else:
            break
    # 数据从这里开始
    data_start = start

    # 解析 header 元数据
    sys_cfg: Dict = {}
    firmware = None
    craft = None
    for ln in header_lines_text:
        body = ln[1:] if ln.startswith(" ") else ln
        body = body.strip()
        if not body:
            continue
        if ":" in body:
            k, v = body.split(":", 1)
            k = k.strip(); v = v.strip()
        else:
            k, v = body, ""
        kl = k.lower()
        if kl == "firmware type":
            firmware = v
        elif kl == "craft name":
            craft = v
        elif kl == "data version":
            sys_cfg["dataVersion"] = int(v or 2)
        elif kl == "i interval":
            sys_cfg["frame_interval_i"] = int(v) if v else 32
        elif kl == "p interval":
            sys_cfg["frame_p_num"] = int(v) if v else 1
        elif kl == "p ratio":
            sys_cfg["frame_p_denom"] = int(v) if v else 1
        elif kl == "minthrottle":
            sys_cfg["minthrottle"] = int(v)
        elif kl == "motor_pwm_rate":
            pass
        elif kl in ("vbatref",):
            sys_cfg["vbatref"] = int(v)
        elif kl == "motoroutput" and "low" in v.lower():
            try:
                sys_cfg["motorOutputLow"] = int(v.split(".")[0])
            except (ValueError, IndexError):
                pass
    sys_cfg.setdefault("dataVersion", 2)
    sys_cfg.setdefault("frame_interval_i", 32)
    sys_cfg.setdefault("frame_p_num", 1)
    sys_cfg.setdefault("frame_p_denom", 1)

    # 构建帧定义（header_lines_text 里含 "Field X ..." 行，注意它们带 'H ' 前缀被去掉）
    field_lines = []
    for ln in header_lines_text:
        s = ln.strip()
        if s.startswith("Field "):
            field_lines.append(s)
    defs = _parse_field_defs(field_lines, None)
    state = DecoderState()
    state.frame_defs = defs
    state.sys_cfg = sys_cfg
    state.frame_interval_i = sys_cfg.get("frame_interval_i", 32)
    state.frame_p_num = sys_cfg.get("frame_p_num", 1)
    state.frame_p_denom = sys_cfg.get("frame_p_denom", 1)

    # 主历史环
    history = [[0] * 128 for _ in range(3)]
    state.main_history = history
    state.main_history_valid = False
    has_main = "I" in defs

    # 主帧缓冲区
    data_rows: List[List[int]] = []
    columns: List[str] = []
    gps_rows: List[List[int]] = []
    gps_columns: List[str] = []
    slow_rows: List[List[int]] = []
    slow_columns: List[str] = []
    frame_counts: Dict[str, int] = {}
    other_events = []

    # 建立解码函数入口：基于 BitStream 与字节对齐推进
    stream = BitStream(raw[data_start:])
    # 主循环：逐字节扫描帧字母，遇到已知帧字母则尝试解码
    i = data_start
    n = len(raw)

    def frame_name_columns(ft):
        fd = defs.get(ft)
        return fd.names if fd else []

    while i < n:
        b = raw[i]
        m = chr(b)
        if m not in defs and m != 'E':
            i += 1
            continue
        # 尝试解码该帧
        ft = m
        fd = defs.get(ft)
        try:
            if ft == 'E':
                # 事件帧：读 type, 然后跳过其数据（至少1字节对齐后）
                sub = BitStream(raw[i + 1:])
                et = sub.read_byte()
                other_events.append(("E", et if et is not None else -1))
                # 事件帧读取到流对齐
                i = i + 1 + (sub.pos)
                continue
        except Exception:
            i += 1
            continue

        # 解码
        try:
            stream = BitStream(raw[i + 1:])
            if ft == 'I':
                # 解码到新 buffer，prev=history[1]
                prev = history[1] if state.main_history_valid else None
                fresh = [0] * 128
                frame = decode_frame(stream, 'I', state, prev, None, 0)
                for k, v in enumerate(frame):
                    fresh[k] = v
                # 翻转：I 帧后 prev/prev2 均指向本帧
                history[2] = fresh
                history[1] = fresh
                history[0] = fresh
                state.main_history_valid = True
                if frame and len(frame) > 0:
                    state.last_main_iteration = frame[0]
                if frame and len(frame) > 1:
                    state.last_main_frame_time = frame[1]
                consumed = stream.pos
                data_rows.append(list(frame))
                if not columns:
                    columns = list(fd.names)
                frame_counts['I'] = frame_counts.get('I', 0) + 1
            elif ft == 'P':
                prev = history[1] if state.main_history_valid else None
                prev2 = history[2] if state.main_history_valid else None
                fresh = [0] * 128
                frame = decode_frame(stream, 'P', state, prev, prev2, 0)
                for k, v in enumerate(frame):
                    fresh[k] = v
                # 翻转：history 环左移
                history[2] = history[1]
                history[1] = fresh
                history[0] = fresh
                state.main_history_valid = True
                if frame and len(frame) > 1:
                    state.last_main_frame_time = frame[1]
                consumed = stream.pos
                data_rows.append(list(frame))
                if not columns:
                    columns = list(fd.names if fd else [])
                frame_counts['P'] = frame_counts.get('P', 0) + 1
            elif ft == 'G':
                frame = decode_frame(stream, 'G', state, None, None, 0)
                consumed = stream.pos
                if frame:
                    gps_rows.append(list(frame))
                    if not gps_columns:
                        gps_columns = list(fd.names)
                frame_counts['G'] = frame_counts.get('G', 0) + 1
            elif ft == 'H':
                frame = decode_frame(stream, 'H', state, None, None, 0)
                consumed = stream.pos
                if frame:
                    state.gps_home = list(frame)
                frame_counts['H'] = frame_counts.get('H', 0) + 1
            elif ft == 'S':
                frame = decode_frame(stream, 'S', state, None, None, 0)
                consumed = stream.pos
                if frame:
                    slow_rows.append(list(frame))
                    if not slow_columns:
                        slow_columns = list(fd.names)
                frame_counts['S'] = frame_counts.get('S', 0) + 1
            # 前进到本帧实际消费的字节后，继续找下一帧字母
            advanced = 1 + stream.pos
            i = i + advanced
            # 若 stream 越界则停止
            if stream.eof or i >= n:
                break
        except Exception:
            # 解码失败，尝试往前进一字节（失步恢复）
            i += 1
            continue

    # 组装结果
    master_frame = defs.get('I') or defs.get('P')
    return {
        "firmware": firmware,
        "craft": craft,
        "sys": sys_cfg,
        "frame_counts": frame_counts,
        "columns": columns,
        "rows": data_rows,
        "gps_columns": gps_columns,
        "gps_rows": gps_rows,
        "slow_columns": slow_columns,
        "slow_rows": slow_rows,
        "events": other_events,
        "frame_defs": {ft: fd.names for ft, fd in defs.items()},
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        with open(sys.argv[1], "rb") as f:
            res = parse_binary_blackbox(f.read())
        print("firmware:", res["firmware"])
        print("craft:", res["craft"])
        print("frame_counts:", res["frame_counts"])
        print("columns:", res["columns"][:12])
        print("rows:", len(res["rows"]))
        print("first row:", res["rows"][0][:12] if res["rows"] else [])
        print("last row:", res["rows"][-1][:12] if res["rows"] else [])
        print("gps_columns:", res["gps_columns"])
        print("gps_rows:", len(res["gps_rows"]))
    else:
        pass