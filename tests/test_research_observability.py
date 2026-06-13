from src.research.observability import TraceContext

def test_trace_context_propagates_task_step_and_attempt():
    ctx = TraceContext(trace_id="t1", workspace_id="ws-a", task_id="R1", step_id="R1:1:web", attempt=2)
    fields = ctx.as_log_fields()
    assert fields["task_id"] == "R1"
    assert fields["attempt"] == 2
