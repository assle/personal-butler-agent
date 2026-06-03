"""
联网搜索包入口
对外导出搜索结果数据结构和搜索服务

Workflow:
1. schemas 定义统一返回对象
2. service 封装供应商调用与结果归一化
3. 其他模块从 src.search 导入公开接口
"""
from src.search.schemas import SearchResult
from src.search.service import WebSearchService

__all__ = ["SearchResult", "WebSearchService"]
