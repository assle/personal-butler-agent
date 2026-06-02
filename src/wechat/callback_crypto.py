"""
企业微信智能机器人 URL 回调加解密工具
负责 Token 签名校验、EncodingAESKey 解码、AES-256-CBC 解密和 URL 验证回显加密

Workflow:
1. URL 验证或消息回调携带 encrypt/msg_signature/timestamp/nonce
2. decrypt_if_signature_valid() 先计算 SHA1 签名并常量时间比较
3. 签名通过后解密企业微信密文，可选校验尾部 receive_id，返回 JSON 或 echostr 明文
4. encrypt() 仅用于测试和需要主动生成加密回包的场景
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


_PKCS7_BLOCK_SIZE = 32
_AES_KEY_BYTES = 32


@dataclass(frozen=True)
class EncryptedPayload:
    """加密后的回调载荷"""

    encrypt: str
    """Base64 编码密文"""

    signature: str
    """使用 Token/timestamp/nonce/encrypt 计算出的 SHA1 签名"""


class WeComCallbackCrypto:
    """企业微信回调加解密器"""

    def __init__(self, token: str, encoding_aes_key: str, receive_id: str = ""):
        """初始化回调加解密器

        参数:
            token: 企业微信后台配置的回调 Token
            encoding_aes_key: 企业微信后台配置的 43 位 EncodingAESKey
            receive_id: 可选接收方 ID；为空时不校验密文尾部 ID
        """
        if not token:
            raise ValueError("token is required")
        self._token = token
        self._receive_id = receive_id
        self._aes_key = self._decode_encoding_aes_key(encoding_aes_key)
        self._iv = self._aes_key[:16]

    def compute_signature(self, timestamp: str, nonce: str, encrypt_text: str) -> str:
        """计算企业微信回调 SHA1 签名

        参数:
            timestamp: 回调 query 中的 timestamp
            nonce: 回调 query 中的 nonce
            encrypt_text: 回调密文

        返回:
            str: 40 位十六进制 SHA1 签名
        """
        pieces = sorted([self._token, timestamp or "", nonce or "", encrypt_text or ""])
        return hashlib.sha1("".join(pieces).encode("utf-8")).hexdigest()

    def decrypt_if_signature_valid(
        self,
        signature: str,
        timestamp: str,
        nonce: str,
        encrypt_text: str,
    ) -> str:
        """校验签名并解密回调密文

        参数:
            signature: 回调 query 中的 msg_signature
            timestamp: 回调 query 中的 timestamp
            nonce: 回调 query 中的 nonce
            encrypt_text: 回调密文

        返回:
            str: 解密后的明文
        """
        expected = self.compute_signature(timestamp, nonce, encrypt_text)
        if not hmac.compare_digest(expected, signature or ""):
            raise ValueError("invalid callback signature")
        return self.decrypt(encrypt_text)

    def decrypt(self, encrypt_text: str) -> str:
        """解密企业微信 AES-CBC 密文

        参数:
            encrypt_text: Base64 编码密文

        返回:
            str: 解密后的明文 JSON 或 echostr
        """
        cipher = Cipher(algorithms.AES(self._aes_key), modes.CBC(self._iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(base64.b64decode(encrypt_text)) + decryptor.finalize()
        plain = _pkcs7_unpad(padded)
        if len(plain) < 20:
            raise ValueError("invalid callback payload length")
        msg_len = int.from_bytes(plain[16:20], "big")
        msg_start = 20
        msg_end = msg_start + msg_len
        if msg_end > len(plain):
            raise ValueError("invalid callback message length")
        message = plain[msg_start:msg_end].decode("utf-8")
        receive_id = plain[msg_end:].decode("utf-8")
        if self._receive_id and receive_id != self._receive_id:
            raise ValueError("callback receive_id mismatch")
        return message

    def encrypt(self, plain_text: str, timestamp: str, nonce: str) -> EncryptedPayload:
        """加密明文并生成签名

        参数:
            plain_text: 待加密明文
            timestamp: 签名使用的 timestamp
            nonce: 签名使用的 nonce

        返回:
            EncryptedPayload: 密文和对应签名
        """
        msg = plain_text.encode("utf-8")
        payload = b"".join([
            os.urandom(16),
            len(msg).to_bytes(4, "big"),
            msg,
            self._receive_id.encode("utf-8"),
        ])
        padded = _pkcs7_pad(payload)
        cipher = Cipher(algorithms.AES(self._aes_key), modes.CBC(self._iv))
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(padded) + encryptor.finalize()
        encrypt_text = base64.b64encode(encrypted).decode("utf-8")
        signature = self.compute_signature(timestamp, nonce, encrypt_text)
        return EncryptedPayload(encrypt=encrypt_text, signature=signature)

    @staticmethod
    def _decode_encoding_aes_key(encoding_aes_key: str) -> bytes:
        """解码企业微信 EncodingAESKey

        参数:
            encoding_aes_key: 43 位 Base64 字符串，可带或不带末尾等号

        返回:
            bytes: 32 字节 AES key
        """
        key = base64.b64decode((encoding_aes_key or "").strip() + "=")
        if len(key) != _AES_KEY_BYTES:
            raise ValueError(f"invalid EncodingAESKey length: {len(key)}")
        return key


def _pkcs7_pad(data: bytes) -> bytes:
    """按企业微信 32 字节块大小填充数据

    参数:
        data: 原始字节

    返回:
        bytes: 填充后的字节
    """
    pad = _PKCS7_BLOCK_SIZE - (len(data) % _PKCS7_BLOCK_SIZE)
    if pad == 0:
        pad = _PKCS7_BLOCK_SIZE
    return data + bytes([pad]) * pad


def _pkcs7_unpad(data: bytes) -> bytes:
    """移除企业微信 PKCS#7 填充

    参数:
        data: 填充后的字节

    返回:
        bytes: 原始字节
    """
    if not data:
        raise ValueError("empty padded payload")
    pad = data[-1]
    if pad < 1 or pad > _PKCS7_BLOCK_SIZE or pad > len(data):
        raise ValueError("invalid pkcs7 padding")
    if data[-pad:] != bytes([pad]) * pad:
        raise ValueError("invalid pkcs7 padding bytes")
    return data[:-pad]
