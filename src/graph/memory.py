"""
图执行共享模块
提供 LangGraph 共享的 MemorySaver 检查点实例

在总流程中的位置:
  每个 agent 的 _build_graph() 调用 builder.compile(checkpointer=checkpointer)
  共享此实例以复用对话记忆，所有 agent 的图执行共享同一 MemorySaver
"""
from langgraph.checkpoint.memory import MemorySaver

checkpointer = MemorySaver()
"""全局共享的 MemorySaver 实例，所有 agent 图编译时共用"""
