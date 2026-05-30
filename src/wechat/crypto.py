"""
企业微信消息加解密和签名验证
基于企业微信官方加密协议：AES-256-CBC + PKCS#7 + SHA1 签名

Workflow:
1. verify_signature: 对 token,timestamp,nonce,msg_encrypt 排序后 SHA1 比对
2. encrypt: 随机16字节 + 消息长度(4字节大端) + 消息 + CorpID → PKCS#7填充 → AES加密 → Base64
3. decrypt: Base64解码 → AES解密 → 去PKCS#7填充 → 解析消息 → 校验 CorpID
"""
import base64
import hashlib
import os
import struct

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class SignatureError(Exception):
    """签名验证失败"""
    pass


class DecryptError(Exception):
    """解密失败（密钥错误或格式异常）"""
    pass


class CorpIDMismatch(Exception):
    """解密后的 CorpID 与预期不匹配"""
    pass


def verify_signature(
    token: str, timestamp: str, nonce: str, msg_encrypt: str, msg_signature: str
) -> bool:
    """验证企业微信回调签名

    参数:
        token: 企业微信后台配置的 Token
        timestamp: 请求携带的时间戳
        nonce: 请求携带的随机数
        msg_encrypt: 加密的消息体
        msg_signature: 请求携带的签名

    返回:
        bool: 签名匹配返回 True，否则返回 False
    """
    parts = sorted([token, timestamp, nonce, msg_encrypt])
    raw = "".join(parts).encode("utf-8")
    computed = hashlib.sha1(raw).hexdigest()
    return computed == msg_signature


def _decode_aes_key(encoding_aes_key: str) -> bytes:
    """将 43 位 Base64 编码的 EncodingAESKey 解码为 32 字节 AES 密钥

    参数:
        encoding_aes_key: 43 位 Base64 字符串

    返回:
        bytes: 32 字节 AES 密钥
    """
    return base64.b64decode(encoding_aes_key + "=")


def encrypt(encoding_aes_key: str, msg: str, corp_id: str) -> str:
    """加密消息为 Base64 密文

    加密格式: random(16) + msg_len(4, big-endian) + msg_utf8 + corp_id_utf8
    加密方式: AES-256-CBC，IV 为密钥前 16 字节，PKCS#7 填充

    参数:
        encoding_aes_key: 43 位 Base64 EncodingAESKey
        msg: 明文消息字符串
        corp_id: 企业 CorpID，解密时会校验

    返回:
        str: Base64 编码的密文
    """
    aes_key = _decode_aes_key(encoding_aes_key)
    iv = aes_key[:16]

    msg_bytes = msg.encode("utf-8")
    corp_id_bytes = corp_id.encode("utf-8")

    # 构造明文: random(16) + msg_len(4, big-endian) + msg + corp_id
    raw = (
        os.urandom(16)
        + struct.pack("!I", len(msg_bytes))
        + msg_bytes
        + corp_id_bytes
    )

    # PKCS#7 填充到 32 字节块（256 位）
    padder = padding.PKCS7(256).padder()
    padded = padder.update(raw) + padder.finalize()

    # AES-256-CBC 加密
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()

    return base64.b64encode(encrypted).decode()


def decrypt(encoding_aes_key: str, msg_encrypt: str, corp_id: str) -> str:
    """解密企业微信回调密文

    解密步骤:
    1. Base64 解码密文
    2. AES-256-CBC 解密（IV 为密钥前 16 字节）
    3. PKCS#7 去填充
    4. 读取前 16 字节随机串，再读 4 字节长度，再读消息内容
    5. 校验末尾 CorpID 与预期一致

    参数:
        encoding_aes_key: 43 位 Base64 EncodingAESKey
        msg_encrypt: Base64 编码的密文字符串
        corp_id: 企业 CorpID，用于校验解密后的数据完整性

    返回:
        str: 解密后的明文消息

    异常:
        DecryptError: Base64 解码、AES 解密或消息格式异常
        CorpIDMismatch: CorpID 校验不通过
    """
    aes_key = _decode_aes_key(encoding_aes_key)
    iv = aes_key[:16]

    try:
        encrypted = base64.b64decode(msg_encrypt)
    except Exception:
        raise DecryptError("Base64 解码失败")

    try:
        cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(encrypted) + decryptor.finalize()

        unpadder = padding.PKCS7(256).unpadder()
        raw = unpadder.update(padded) + unpadder.finalize()
    except Exception:
        raise DecryptError("AES 解密或 PKCS#7 去填充失败")

    try:
        # 格式: random(16) + msg_len(4, big-endian) + msg + corp_id
        msg_len = struct.unpack("!I", raw[16:20])[0]
        msg_bytes = raw[20:20 + msg_len]
        corp_id_from_msg = raw[20 + msg_len:].decode("utf-8")
    except (struct.error, IndexError, UnicodeDecodeError):
        raise DecryptError("消息格式异常")

    if corp_id_from_msg != corp_id:
        raise CorpIDMismatch(
            f"CorpID 不匹配: 期望 {corp_id}, 实际 {corp_id_from_msg}"
        )

    return msg_bytes.decode("utf-8")
