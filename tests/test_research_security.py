"""安全边界测试"""
from src.research.supervisor.prompts import SUPERVISOR_SYSTEM_PROMPT
from src.research.synthesis.prompts import SYNTHESIS_SYSTEM_PROMPT
from src.research.review.prompts import CITATION_REVIEW_PROMPT

def test_all_prompts_contain_system_rules_section():
    for prompt in [SUPERVISOR_SYSTEM_PROMPT, SYNTHESIS_SYSTEM_PROMPT, CITATION_REVIEW_PROMPT]:
        assert "<system_rules>" in prompt, f"Missing system_rules in prompt"
        assert "</system_rules>" in prompt, f"Missing closing system_rules"

def test_synthesis_prompt_contains_untrusted_source_instruction():
    assert "<untrusted_source>" in SYNTHESIS_SYSTEM_PROMPT

def test_prompts_are_isolated_from_each_other():
    # Verify each prompt has distinct sections
    assert "<task>" in SUPERVISOR_SYSTEM_PROMPT
    assert "<evidence_records>" in SYNTHESIS_SYSTEM_PROMPT
    assert "<task>" in CITATION_REVIEW_PROMPT
