"""
知识库向量嵌入
支持 DashScope API（Qwen3-Embedding）语义嵌入和本地哈希嵌入 fallback。

Workflow:
  API 可用 → 调用 DashScope text-embedding-v4 → 返回语义向量
  API 不可用或未配置 → fallback 到本地字符 n-gram 哈希向量
  余弦相似度统一用于两种模式的向量比较
"""
from hashlib import sha256
from math import sqrt

import httpx


class EmbeddingService:
    """嵌入服务，优先使用 DashScope API，失败时降级为本地哈希"""

    _DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

    def __init__(
        self,
        dimension: int = 1024,
        model_name: str = "text-embedding-v4",
        api_key: str = "",
    ):
        """初始化嵌入服务

        参数:
            dimension: 向量维度（API 模式 1024，本地模式 256）
            model_name: API 模型名；本地模式时显示"local-hashing-v1"
            api_key: DashScope API key；为空时不启用 API 模式

        返回:
            None
        """
        self.dimension = dimension
        self.api_key = api_key
        self._api_model = model_name if api_key else ""
        self._local_dimension = 256
        self.model_name = self._api_model if self._api_model else "local-hashing-v1"

    @property
    def _use_api(self) -> bool:
        """是否使用 API 模式"""
        return bool(self.api_key)

    async def embed(self, text: str) -> list[float]:
        """将文本转换为归一化向量

        参数:
            text: 需要嵌入的文本

        返回:
            list[float]: 归一化后的向量
        """
        if self._use_api:
            try:
                return await self._api_embed(text)
            except Exception:
                pass
        return self._local_embed(text)

    async def _api_embed(self, text: str) -> list[float]:
        """调用 DashScope API 生成语义向量

        参数:
            text: 需要嵌入的文本

        返回:
            list[float]: API 返回的向量
        """
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self._DASHSCOPE_BASE_URL}/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._api_model,
                    "input": text,
                    "dimensions": self.dimension,
                },
            )
            response.raise_for_status()
            data = response.json()
            return list(data["data"][0]["embedding"])

    def _local_embed(self, text: str) -> list[float]:
        """本地字符 n-gram 哈希向量（fallback）

        参数:
            text: 需要嵌入的文本

        返回:
            list[float]: 归一化后的哈希向量
        """
        vector = [0.0] * self._local_dimension
        for token in self._tokens(text):
            digest = sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._local_dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def similarity(self, left: list[float], right: list[float]) -> float:
        """计算两个向量的余弦相似度

        参数:
            left: 第一个归一化向量
            right: 第二个归一化向量

        返回:
            float: 0 到 1 附近的相似度分数，负数会被裁剪为 0
        """
        if not left or not right or len(left) != len(right):
            return 0.0
        return max(0.0, sum(a * b for a, b in zip(left, right, strict=True)))

    def _tokens(self, text: str) -> list[str]:
        """提取用于哈希嵌入的字符 n-gram

        参数:
            text: 原始文本

        返回:
            list[str]: 包含单字、双字和三字窗口的 token 列表
        """
        compact = "".join(
            char.lower()
            for char in text
            if char.isalnum() or "一" <= char <= "鿿"
        )
        if not compact:
            return []

        tokens = list(compact)
        for width in (2, 3):
            if len(compact) >= width:
                tokens.extend(
                    compact[index:index + width]
                    for index in range(len(compact) - width + 1)
                )
        return tokens
