"""研究计划 DAG 校验器"""
from src.research.budgets import BudgetLimits
from src.research.planning.schemas import PlanDraft


class PlanValidationError(ValueError):
    """研究计划校验失败"""


class PlanValidator:
    """按 DAG、工具和预算规则校验研究计划"""

    def __init__(self, allowed_tools: set[str]):
        """初始化校验器

        参数:
            allowed_tools: 允许调用的工具名集合
        """
        self._allowed_tools = allowed_tools

    @classmethod
    def from_registry(cls, registry) -> "PlanValidator":
        """从工具注册表创建校验器；参数为注册表；返回使用注册工具名的校验器。"""
        return cls(
            allowed_tools={
                definition.name
                for definition in registry.list_tools()
                if registry.has_provider(definition.name)
            }
        )

    def validate(self, draft: PlanDraft, *, limits: BudgetLimits) -> None:
        """校验计划草案；不合法时抛出 PlanValidationError

        参数:
            draft: 待校验的计划草案
            limits: 预算限制

        异常:
            PlanValidationError: 校验失败
        """
        self._validate_keys(draft)
        self._validate_dependencies(draft)
        self._validate_no_cycle(draft)
        self._validate_tools(draft)
        self._validate_budgets(draft, limits)

    def _validate_keys(self, draft: PlanDraft) -> None:
        """校验步骤 key 唯一"""
        keys = [s.key for s in draft.steps]
        if len(keys) != len(set(keys)):
            raise PlanValidationError("步骤 key 必须唯一")

    def _validate_dependencies(self, draft: PlanDraft) -> None:
        """校验依赖引用存在且无自依赖"""
        key_set = {s.key for s in draft.steps}
        for step in draft.steps:
            for dep in step.depends_on:
                if dep == step.key:
                    raise PlanValidationError(f"步骤 {step.key} 不能依赖自身")
                if dep not in key_set:
                    raise PlanValidationError(
                        f"步骤 {step.key} 依赖不存在的步骤 {dep}"
                    )

    def _validate_no_cycle(self, draft: PlanDraft) -> None:
        """校验 DAG 无环"""
        key_set = {s.key for s in draft.steps}
        deps = {s.key: set(s.depends_on) for s in draft.steps}

        # 拓扑排序检测环
        in_degree = {k: len(deps[k]) for k in key_set}
        queue = [k for k in key_set if in_degree[k] == 0]

        while queue:
            node = queue.pop(0)
            for other in key_set:
                if node in deps[other]:
                    in_degree[other] -= 1
                    if in_degree[other] == 0:
                        queue.append(other)

        if any(d > 0 for d in in_degree.values()):
            raise PlanValidationError("研究计划包含循环依赖")

    def _validate_tools(self, draft: PlanDraft) -> None:
        """校验所有工具名在允许列表中"""
        for step in draft.steps:
            if step.tool_name not in self._allowed_tools:
                raise PlanValidationError(
                    f"步骤 {step.key} 使用了未注册的工具: {step.tool_name}"
                )

    def _validate_budgets(
        self, draft: PlanDraft, limits: BudgetLimits
    ) -> None:
        """校验不超预算"""
        if len(draft.steps) > limits.max_steps:
            raise PlanValidationError(
                f"步骤数 {len(draft.steps)} 超过限制 {limits.max_steps}"
            )
        if draft.estimated_tokens > limits.max_tokens:
            raise PlanValidationError(
                f"预估 token {draft.estimated_tokens} 超过限制 {limits.max_tokens}"
            )
        if draft.estimated_cost_microunits > limits.max_cost_microunits:
            raise PlanValidationError(
                f"预估成本 {draft.estimated_cost_microunits} 超过限制 {limits.max_cost_microunits}"
            )

        # 检查依赖深度
        for step in draft.steps:
            depth = self._dependency_depth(step.key, draft)
            if depth > limits.max_dependency_depth:
                raise PlanValidationError(
                    f"步骤 {step.key} 依赖深度 {depth} 超过限制 {limits.max_dependency_depth}"
                )

    def _dependency_depth(self, key: str, draft: PlanDraft) -> int:
        """计算步骤的依赖深度"""
        deps = {s.key: s.depends_on for s in draft.steps}
        visited: set[str] = set()
        max_depth = 0

        def dfs(k: str, depth: int) -> None:
            nonlocal max_depth
            if k in visited:
                return
            visited.add(k)
            max_depth = max(max_depth, depth)
            for dep in deps.get(k, []):
                dfs(dep, depth + 1)

        dfs(key, 0)
        return max_depth
