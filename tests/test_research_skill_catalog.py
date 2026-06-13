"""研究 Skill 测试"""
import yaml
from pathlib import Path

def _parse_skill_md(path):
    """简单的 frontmatter 解析"""
    text = path.read_text()
    if not text.startswith("---"):
        raise ValueError("missing frontmatter")
    parts = text.split("---", 2)
    return yaml.safe_load(parts[1]), parts[2].strip()

def test_general_skill_manifest_is_valid():
    manifest, body = _parse_skill_md(Path("research_skills/general/SKILL.md"))
    assert manifest["name"] == "general-research"
    assert manifest["version"] == "1.0.0"
    assert manifest["allowed_tools"] == ["knowledge.search", "web.search", "web.fetch"]
    assert len(body) > 100
