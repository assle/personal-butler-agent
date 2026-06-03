"""
联网搜索数据结构
定义搜索服务对外返回的统一结果对象

Workflow:
1. 搜索供应商返回原始 JSON 数据
2. service 模块解析并归一化字段
3. 调用方只依赖 SearchResult，不直接依赖供应商响应格式
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchResult:
    """统一搜索结果对象"""

    # 结果标题
    title: str
    # 结果链接
    url: str
    # 结果摘要文本
    snippet: str
    # 供应商返回的相关性分数；没有分数时为 None
    score: float | None = None
