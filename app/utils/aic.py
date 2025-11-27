from typing import Optional
import secrets
import hashlib

from .utils import get_beijing_time

PROTOCOL_VERSION = "1"
MANAGER_CODE = "0001"
PROVIDER_CODE = "00001"

# Base36 字母表（0-9, A-Z）
BASE36_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE36_INDEX = {ch: i for i, ch in enumerate(BASE36_ALPHABET)}


def _base36_encode(num: int, length: int) -> str:
    """将非负整数编码为固定长度的 Base36 字符串（大写，左侧以 0 补齐）。"""
    if num < 0:
        raise ValueError("num 必须是非负整数")
    if length <= 0:
        raise ValueError("length 必须为正数")
    if num == 0:
        return "0".rjust(length, "0")
    digits = []
    base = 36
    while num > 0:
        num, rem = divmod(num, base)
        digits.append(BASE36_ALPHABET[rem])
    encoded = "".join(reversed(digits))
    if len(encoded) > length:
        # 超长则截断右侧（低位），保持固定长度
        encoded = encoded[-length:]
    return encoded.rjust(length, "0")


def _base36_decode(s: str) -> int:
    """将 Base36 字符串解码为整数。允许小写输入与空格。"""
    if not s:
        return 0
    val = 0
    for ch in s.strip().upper():
        if ch == " ":
            continue
        if ch not in BASE36_INDEX:
            raise ValueError(f"非 Base36 字符: {ch}")
        val = val * 36 + BASE36_INDEX[ch]
    return val


def _get_ms_of_year(now_beijing: Optional[float] = None) -> int:
    """获取北京时间当年内的毫秒数（去掉年份影响）。

    为避免闰年边界误差，这里精确计算：从当年 01-01 00:00:00.000 到当前时间的毫秒差。
    """
    # 当前北京时间
    dt = get_beijing_time()
    # 当年起点（北京时间）
    year_start = dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    # 差值（毫秒）
    delta_ms = int((dt - year_start).total_seconds() * 1000)
    return max(delta_ms, 0)


def _encode_year_b36(year: int) -> str:
    """将十进制年份编码为 3 位 Base36（直接以年份值编码，比如 2025 -> '1K9'）。"""
    return _base36_encode(year, 3)


def _serial_from_ms_with_salt(
    ms_in_year: int, salt: bytes, kind: bytes, length: int
) -> str:
    """基于年内毫秒数 + 随机盐，生成指定长度的 Base36 序列。

    为了避免 Base36 非 2 的幂导致的位操作复杂性，采用 BLAKE2b 哈希将
    (kind || ms_in_year || salt) 映射为高熵字节，再转换为大整数后以 Base36 编码，
    取所需长度，不足左侧以 '0' 补齐。不同 kind（b'OBJ'/b'INS'）保证两段序列不同。
    """
    # 组装消息：kind + ms(8B big-endian) + salt(>=8B)
    ms_bytes = ms_in_year.to_bytes(8, byteorder="big", signed=False)
    h = hashlib.blake2b(digest_size=16)
    h.update(kind)
    h.update(ms_bytes)
    h.update(salt)
    digest = h.digest()  # 128-bit
    val = int.from_bytes(digest, "big")
    s36 = _base36_encode(val, length)
    # 使用末尾 length 位，确保不同长度时后缀分布稳定
    if len(s36) > length:
        s36 = s36[-length:]
    return s36


def generate_aic(
    protocol_version: str = PROTOCOL_VERSION,
    manager_code: str = MANAGER_CODE,
    provider_code: str = PROVIDER_CODE,
) -> str:
    """
    生成符合 AIC（Agent Identity Code）规范的 32 位身份码（Base36 本体码 + 2 位十进制校验）。

    AIC 字段（共 32 位）：
    - [1]    协议版本号（1 位，Base36，通常为 '1'）
    - [2-5]  管理机构代码（4 位，示例："0001"）
    - [6-10] 智能体提供商机构代码（5 位，示例："00001"）
    - [11-13] 注册年份（3 位，十进制年份按 Base36 编码，如 2025 -> '1K9'）
    - [14-22] 本体序列号（9 位，基于年内毫秒数 + 随机盐，经哈希映射生成，Base36）
    - [23-30] 实例序列号（8 位，基于年内毫秒数 + 随机盐，经哈希映射生成，Base36）
    - [31-32] 校验码（2 位十进制数字），按 GSMA 风格：
        将前 30 位 Base36 本体码换算为十进制大整数，乘以 100 后对 97 取余；
        用 98 减去余数，结果左侧补零到 2 位。

    返回:
        32 位 AIC 字符串
    """
    # 基础字段
    dt = get_beijing_time()
    year_b36 = _encode_year_b36(dt.year)

    # 年内毫秒数 + 随机盐 -> 两段不同的序列号
    ms_in_year = _get_ms_of_year()
    # 8 字节随机盐，提升并发唯一性
    salt = secrets.token_bytes(8)
    object_serial = _serial_from_ms_with_salt(ms_in_year, salt, b"OBJ", 9)
    instance_serial = _serial_from_ms_with_salt(ms_in_year, salt, b"INS", 8)

    # 组装 30 位本体码（Base32）
    body30 = f"{protocol_version}{manager_code}{provider_code}{year_b36}{object_serial}{instance_serial}"

    # 计算 2 位十进制校验码
    check_digits = calculate_check_digits(body30)
    return body30 + check_digits


def calculate_check_digits(aic_body_base36: str) -> str:
    """
    计算新版 AIC 的 2 位十进制校验码（Base36 本体码 -> 十进制 -> GSMA-97）。

    步骤：
    1) 将 30 位 Base36 本体码解码为一个十进制大整数 N；
    2) 计算 remainder = (N * 100) % 97；
    3) check = 98 - remainder；
    4) 返回 2 位十进制字符串（若 <10 则左补 0）。
    """
    if len(aic_body_base36) != 30:
        raise ValueError("校验码计算需要 30 位 Base36 本体码")
    n = _base36_decode(aic_body_base36)
    remainder = (n * 100) % 97
    check = 98 - remainder
    return f"{check:02d}"


def validate_aic(aic: str) -> bool:
    """
    验证新版 AIC 的有效性。

    验证规则：
    - 长度必须为 32；
    - 前 30 位为 Base36（0-9, A-Z），后 2 位为十进制数字；
    - 将前 30 位按 Base36 解码为十进制大整数 N，检查 (N * 100 + 校验码) % 97 == 1。
    """
    if not aic:
        return False
    aic = aic.strip().upper().replace(" ", "")
    if len(aic) != 32:
        return False

    body, chk = aic[:30], aic[30:]
    # 校验后两位必须为十进制
    if not chk.isdigit():
        return False

    # 校验前 30 位字符集
    try:
        n = _base36_decode(body)
    except ValueError:
        return False

    # 按规范验证： (N * 100 + chk) % 97 == 1
    chk_val = int(chk)
    return ((n * 100) + chk_val) % 97 == 1
