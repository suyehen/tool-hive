"""KEK 与信封加密（任务 B4，设计 §10.1）。

设计要解决的问题
----------------
平台代持上游系统的 Token。若 Token 明文入库，任何拿到**数据库备份、只读账号或慢查询日志**
的人就能一次性拿走**所有**上游凭据（设计 §2 的 C4/D2）。所以必须加密；
而**密钥不能和密文放在同一个地方**——放一起等于没加密。

于是用信封加密::

    上游 Token（明文）
      └─ 用 DEK 加密            → body 存入 credential.ciphertext
           └─ DEK 再用 KEK 加密  → wrapped_dek 一并存在同一个 blob 里
                └─ KEK 放在库外：环境变量，永不入库

密文格式（自带 ``kek_id``，这是轮换能成立的前提）
--------------------------------------------------
::

    "THC1"          4B   魔数 + 格式版本
    kek_id_len      1B
    kek_id          nB   utf-8；**记录"这条密文由哪把 KEK 包装"**
    dek_nonce      12B   AES-GCM nonce（包装 DEK 用）
    wrapped_dek    48B   32B DEK + 16B GCM tag
    body_nonce     12B   AES-GCM nonce（加密正文用）
    body           mB    正文密文 + 16B GCM tag

**为什么把 ``kek_id`` 写进密文**：解密时必须按**密文上记录的** id 去找 KEK，
而不是用当前的 ``ACTIVE_KEK_ID``。否则轮换期间（新 KEK 已启用、存量密文还没重包装完）
所有存量凭据都会解不开（设计 §10.1）。

密钥绝不外泄
------------
设计 §10.1 部署约束第 2 条要求"KEK 不进日志、不进崩溃转储、不进配置查询接口"。
本模块据此做了三件事：

1. 异常信息**只含 kek_id，绝不含密钥值**；
2. :meth:`EnvelopeCipher.__repr__` 被重写成脱敏形式——否则 ``repr()`` 一个
   持有 KEK 的对象就会把它打出来；
3. 配置侧对承载密钥的字段设了 ``repr=False``（见 :class:`toolhive.config.SecretSettings`）。
"""

from __future__ import annotations

import os
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from toolhive.config import SecretSettings

__all__ = [
    "CipherError",
    "DecryptionError",
    "EnvelopeCipher",
    "UnknownKekError",
    "parse_kek_id",
]

#: 魔数 + 格式版本。放在最前面，便于将来演进时能识别旧格式。
MAGIC: Final = b"THC1"

_DEK_BYTES: Final = 32  # AES-256
_NONCE_BYTES: Final = 12  # GCM 标准 nonce 长度
_WRAPPED_DEK_BYTES: Final = _DEK_BYTES + 16  # DEK + GCM tag

#: AAD 前缀。把两层加密分别绑定到不同的前缀上，
#: 防止把"包装后的 DEK"当成"正文密文"塞回去（两者格式相似，不加区分是可以互换的）。
_AAD_DEK: Final = b"THC1:dek:"
_AAD_BODY: Final = b"THC1:body:"


class CipherError(Exception):
    """加密相关错误基类。

    ⚠️ **所有子类的消息都不得包含密钥材料或明文**——设计 §10.1 部署约束第 2 条。
    """


class UnknownKekError(CipherError):
    """密文引用的 ``kek_id`` 不在 ``TOOLHIVE_KEKS`` 里。

    这通常意味着 KEK 轮换的最后一步（从环境变量移除旧 KEK）执行得太早，
    或者换了环境却没迁移密文。

    设计 §10.1 要求这种情况**fail-closed**：拒绝执行并返回 ``TH_UPSTREAM_ERROR``，
    同时**触发平台侧告警**——这是平台配置问题，不是调用方的错。
    把它和"上游抖动"混在一起会让运维查错方向。
    """


class DecryptionError(CipherError):
    """密文损坏、被篡改，或 AAD 不匹配。

    GCM 的 tag 校验失败会走到这里。**不要把底层异常原文透出去**——
    它可能包含密文片段，而密文对排查没有帮助、对攻击者却有用。
    """


def parse_kek_id(blob: bytes) -> str:
    """从密文头部读出 ``kek_id``，**不解密**。

    用途：轮换任务要按 ``kek_id`` 分组处理存量凭据，不该为此先解密一遍。
    """
    _, kek_id = _split_header(blob)
    return kek_id


def _split_header(blob: bytes) -> tuple[int, str]:
    """校验魔数并切出 ``(正文起始偏移, kek_id)``。"""
    if len(blob) < len(MAGIC) + 2:
        raise DecryptionError("密文太短，不像是本格式")
    if blob[: len(MAGIC)] != MAGIC:
        raise DecryptionError("密文魔数不匹配（可能不是本平台产生的密文）")

    kek_id_len = blob[len(MAGIC)]
    start = len(MAGIC) + 1
    end = start + kek_id_len
    if len(blob) < end:
        raise DecryptionError("密文头部被截断")
    try:
        kek_id = blob[start:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DecryptionError("密文头部的 kek_id 不是合法 UTF-8") from exc
    return end, kek_id


class EnvelopeCipher:
    """信封加密器。持有 KEK，负责加密、解密与**重包装**。

    **不需要**可变状态：每次加密都新生成一个随机 DEK（设计 §10.1
    "每条凭据使用独立随机 DEK"），所以同一个实例可以并发使用。
    """

    def __init__(self, secret: SecretSettings) -> None:
        self._secret = secret

    def __repr__(self) -> str:
        # 默认的 object repr 只显示地址，但一旦有人给它加了 __dict__ 打印就会泄密。
        # 显式写死脱敏形式，只暴露"有几把 KEK、当前用哪把"。
        return (
            f"EnvelopeCipher(kek_ids={sorted(self._secret.kek_ids())!r}, "
            f"active_kek_id={self._secret.active_kek_id!r})"
        )

    @property
    def kek_ids(self) -> set[str]:
        """已知的 KEK 标识（**不含密钥值**）。"""
        return self._secret.kek_ids()

    def encrypt(
        self,
        plaintext: bytes,
        *,
        kek_id: str | None = None,
        aad: bytes | None = None,
    ) -> bytes:
        """加密。每次调用生成新的随机 DEK。

        ``kek_id`` 为 ``None`` 时用 ``ACTIVE_KEK_ID``（新写入的正常路径）；
        显式指定只在轮换/测试时使用。

        ``aad``（附加认证数据）不会被加密，但**参与完整性校验**。
        建议传入凭据自身的标识（如名称），这样即使有人把 A 的密文复制到 B 上，
        解密也会失败——这是"密文不可搬运"的保证。
        """
        target_kek_id = kek_id or self._secret.active_kek_id
        try:
            kek = self._secret.kek_bytes(target_kek_id)
        except KeyError as exc:
            raise UnknownKekError(
                f"加密指定的 kek_id={target_kek_id!r} 不在 TOOLHIVE_KEKS 中"
            ) from exc

        dek = AESGCM.generate_key(bit_length=256)
        dek_nonce = os.urandom(_NONCE_BYTES)
        wrapped_dek = AESGCM(kek).encrypt(dek_nonce, dek, _AAD_DEK + (aad or b""))

        body_nonce = os.urandom(_NONCE_BYTES)
        body = AESGCM(dek).encrypt(body_nonce, plaintext, _AAD_BODY + (aad or b""))

        kek_id_bytes = target_kek_id.encode("utf-8")
        if len(kek_id_bytes) > 255:
            raise CipherError("kek_id 超过 255 字节，无法写入密文头部")

        return b"".join(
            (
                MAGIC,
                bytes([len(kek_id_bytes)]),
                kek_id_bytes,
                dek_nonce,
                wrapped_dek,
                body_nonce,
                body,
            )
        )

    def decrypt(self, blob: bytes, *, aad: bytes | None = None) -> bytes:
        """解密。

        **按密文头部记录的 ``kek_id`` 找 KEK**，不依赖 ``ACTIVE_KEK_ID``——
        这是 KEK 轮换期间存量密文仍能解开的前提（设计 §10.1）。
        """
        offset, kek_id = _split_header(blob)

        try:
            kek = self._secret.kek_bytes(kek_id)
        except KeyError as exc:
            raise UnknownKekError(
                f"密文引用的 kek_id={kek_id!r} 不在 TOOLHIVE_KEKS 中"
                f"（现有：{sorted(self._secret.kek_ids())}）。"
                "按设计 §10.1 必须 fail-closed 并告警——这是平台配置问题，"
                "不是调用方的错；不要降级为匿名调用，也不要返回空值。"
            ) from exc

        need = offset + _NONCE_BYTES + _WRAPPED_DEK_BYTES + _NONCE_BYTES
        if len(blob) < need:
            raise DecryptionError("密文被截断")

        dek_nonce = blob[offset : offset + _NONCE_BYTES]
        wrapped_start = offset + _NONCE_BYTES
        wrapped_dek = blob[wrapped_start : wrapped_start + _WRAPPED_DEK_BYTES]
        body_nonce_start = wrapped_start + _WRAPPED_DEK_BYTES
        body_nonce = blob[body_nonce_start : body_nonce_start + _NONCE_BYTES]
        body = blob[body_nonce_start + _NONCE_BYTES :]

        context = aad or b""
        try:
            dek = AESGCM(kek).decrypt(dek_nonce, wrapped_dek, _AAD_DEK + context)
        except InvalidTag as exc:
            raise DecryptionError(
                "解开 DEK 失败：KEK 不对、AAD 不匹配，或密文被篡改"
                f"（kek_id={kek_id!r}）"
            ) from exc

        try:
            return AESGCM(dek).decrypt(body_nonce, body, _AAD_BODY + context)
        except InvalidTag as exc:
            raise DecryptionError(
                "解开正文失败：密文被篡改，或 AAD 与加密时不一致"
            ) from exc

    def rewrap(
        self, blob: bytes, *, kek_id: str | None = None, aad: bytes | None = None
    ) -> bytes:
        """把 DEK 换成用新 KEK 包装，**正文密文原样不动**。

        这是信封加密的核心收益：KEK 轮换（设计 §10.1 的第 3 步）只需要重写 48 字节，
        不必把每个凭据的正文解密再加密一遍——凭据明文**在整个过程中都不出现在内存之外**，
        连解密正文这一步都省了。

        ``kek_id`` 为 ``None`` 时用当前的 ``ACTIVE_KEK_ID``。
        已经是目标 KEK 的密文原样返回（重复执行是安全的）。
        ``aad`` 必须与加密时相同，通常为不可变的凭据 ID。
        """
        offset, current_kek_id = _split_header(blob)
        target = kek_id or self._secret.active_kek_id

        old_kek = self._kek_or_raise(current_kek_id)
        new_kek = self._kek_or_raise(target)

        need = offset + _NONCE_BYTES + _WRAPPED_DEK_BYTES + _NONCE_BYTES + 16
        if len(blob) < need:
            raise DecryptionError("密文被截断")

        dek_nonce = blob[offset : offset + _NONCE_BYTES]
        wrapped_start = offset + _NONCE_BYTES
        wrapped_dek = blob[wrapped_start : wrapped_start + _WRAPPED_DEK_BYTES]
        tail = blob[wrapped_start + _WRAPPED_DEK_BYTES :]

        context = aad or b""
        try:
            dek = AESGCM(old_kek).decrypt(dek_nonce, wrapped_dek, _AAD_DEK + context)
        except InvalidTag as exc:
            raise DecryptionError(
                f"重包装时无法解开 DEK（kek_id={current_kek_id!r}）。"
                "请检查 KEK、AAD 和密文完整性"
            ) from exc

        if current_kek_id == target:
            return blob
        new_nonce = os.urandom(_NONCE_BYTES)
        new_wrapped = AESGCM(new_kek).encrypt(new_nonce, dek, _AAD_DEK + context)

        target_bytes = target.encode("utf-8")
        if len(target_bytes) > 255:
            raise CipherError("kek_id 超过 255 字节，无法写入密文头部")
        return b"".join(
            (MAGIC, bytes([len(target_bytes)]), target_bytes, new_nonce, new_wrapped, tail)
        )

    def _kek_or_raise(self, kek_id: str) -> bytes:
        try:
            return self._secret.kek_bytes(kek_id)
        except KeyError as exc:
            raise UnknownKekError(
                f"kek_id={kek_id!r} 不在 TOOLHIVE_KEKS 中"
                f"（现有：{sorted(self._secret.kek_ids())}）"
            ) from exc
