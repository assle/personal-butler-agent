"""
Butler Agent 包
导出小管家总控 agent，供应用 wiring 和测试通过统一包入口引用

Workflow:
  main.py 或测试导入 ButlerAgent → ButlerAgent 构建工具调用 StateGraph
  → handle() 返回 AgentResponse
"""
from src.agents.butler.graph import ButlerAgent

__all__ = ["ButlerAgent"]
