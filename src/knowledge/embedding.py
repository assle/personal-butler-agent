"""
知识库本地向量嵌入
用稳定的字符 n-gram 哈希向量为 RAG 提供轻量语义召回，不依赖外部服务

Workflow:
  文本 → 规范化 → 字符 n-gram → 哈希投影到固定维度 → L2 归一化向量
  查询向量与 chunk 向量通过余弦相似度参与混合排序
"""
from hashlib import sha256
from math import sqrt


class EmbeddingService:
    """本地嵌入服务，生成可重复的轻量文本向量"""

    def __init__(self, dimension: int = 256, model_name: str = "local-hashing-v1"):
        """初始化嵌入服务

        参数:
            dimension: 向量维度，维度越高哈希冲突越少
            model_name: 嵌入模型标识，用于索引重建和兼容判断

        返回:
            None
        """
        self.dimension = dimension
        self.model_name = model_name

    def embed(self, text: str) -> list[float]:
        """将文本转换为归一化向量

        参数:
            text: 需要嵌入的文档片段或用户查询

        返回:
            list[float]: 固定维度、L2 归一化后的向量
        """
        vector = [0.0] * self.dimension
        for token in self._tokens(text):
            digest = sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
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
            if char.isalnum() or "\u4e00" <= char <= "\u9fff"
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
