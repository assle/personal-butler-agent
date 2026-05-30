"""
测试企业微信消息加解密和签名验证

Workflow:
1. 验证签名计算（排序 token/timestamp/nonce/msg → SHA1）
2. 加解密往返测试（encrypt → decrypt 应与原文一致）
3. 错误 CorpID 应触发 CorpIDMismatch
4. 错误密钥解密应触发 DecryptError
"""
import base64
import hashlib
import os

import pytest

from src.wechat.crypto import (
    CorpIDMismatch,
    DecryptError,
    decrypt,
    encrypt,
    verify_signature,
)


def test_verify_signature_success():
    """测试签名验证通过：SHA1(sort([token, timestamp, nonce, msg_encrypt])) == msg_signature

    输入: token, timestamp, nonce, msg_encrypt 及正确签名
    输出: True
    """
    token = "test_token"
    timestamp = "1234567890"
    nonce = "test_nonce"
    msg_encrypt = "encrypted_message"

    expected_sig = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, msg_encrypt])).encode()
    ).hexdigest()

    assert verify_signature(token, timestamp, nonce, msg_encrypt, expected_sig) is True


def test_verify_signature_failure():
    """测试签名验证失败：错误签名应返回 False

    输入: 正确的 token/timestamp/nonce/msg_encrypt + 错误签名
    输出: False
    """
    token = "test_token"
    timestamp = "1234567890"
    nonce = "test_nonce"
    msg_encrypt = "encrypted_message"

    assert verify_signature(token, timestamp, nonce, msg_encrypt, "wrong_sig") is False


def test_encrypt_decrypt_roundtrip():
    """测试加解密往返：encrypt 后 decrypt 应与原文一致

    输入: 随机 AES 密钥 + 中文测试消息 + CorpID
    输出: decrypt 结果等于原始消息
    """
    aes_key_raw = os.urandom(32)
    encoding_aes_key = base64.b64encode(aes_key_raw).decode()
    corp_id = "test_corp_id"
    original_msg = "你好，这是一条测试消息"

    encrypted = encrypt(encoding_aes_key, original_msg, corp_id)
    decrypted = decrypt(encoding_aes_key, encrypted, corp_id)
    assert decrypted == original_msg


def test_decrypt_wrong_corp_id():
    """测试 CorpID 不匹配时应抛出 CorpIDMismatch

    输入: 用 correct_corp_id 加密的消息 + 错误的 wrong_corp_id 去解密
    输出: 抛出 CorpIDMismatch 异常
    """
    aes_key_raw = os.urandom(32)
    encoding_aes_key = base64.b64encode(aes_key_raw).decode()

    encrypted = encrypt(encoding_aes_key, "test message", "correct_corp_id")

    with pytest.raises(CorpIDMismatch):
        decrypt(encoding_aes_key, encrypted, "wrong_corp_id")


def test_decrypt_wrong_key():
    """测试使用错误密钥解密时应抛出 DecryptError

    输入: 密钥1加密的消息 + 密钥2尝试解密
    输出: 抛出 DecryptError 异常
    """
    aes_key_1 = base64.b64encode(os.urandom(32)).decode()
    aes_key_2 = base64.b64encode(os.urandom(32)).decode()

    encrypted = encrypt(aes_key_1, "test message", "corp_id")

    with pytest.raises(DecryptError):
        decrypt(aes_key_2, encrypted, "corp_id")
