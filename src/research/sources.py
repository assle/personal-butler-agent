"""研究工作空间授权数据源网关"""
from pydantic import BaseModel


class ResearchAccessScope(BaseModel):
    """研究任务不可变数据范围"""
    workspace_id: str
    user_id: str
    include_public: bool = True
    group_ids: tuple[str, ...] = ()
    allow_web: bool = True


class ResearchSourceGateway:
    """按任务权限范围路由检索"""

    def __init__(self, *, knowledge=None, web=None):
        self._knowledge = knowledge
        self._web = web

    async def search_knowledge(
        self,
        scope: ResearchAccessScope,
        query: str,
        *,
        db,
        domains: list[str] | None = None,
        limit: int = 5,
        llm=None,
    ):
        """按研究权限范围检索知识库"""
        if self._knowledge is None:
            return []
        return await self._knowledge.search(
            query=query,
            user_id=scope.user_id,
            db=db,
            domains=domains or ["global", "qa"],
            limit=limit,
            llm=llm,
        )

    async def search_web(self, scope: ResearchAccessScope, query: str):
        """按权限执行联网搜索"""
        if not scope.allow_web or self._web is None:
            return []
        return await self._web.search(query)
