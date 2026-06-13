"""研究 Skill 加载器"""
from pathlib import Path
import yaml
from dataclasses import dataclass

class InvalidResearchSkillName(ValueError):
    pass

@dataclass(frozen=True)
class LoadedResearchSkill:
    name: str
    version: str
    body: str
    allowed_tools: list[str]

class ResearchSkillLoader:
    def __init__(self, root: Path, catalog_names: set[str]):
        self._root = root
        self._names = catalog_names

    def load(self, name: str) -> LoadedResearchSkill:
        if name not in self._names:
            raise InvalidResearchSkillName(f"未知技能: {name}")
        if ".." in name or "/" in name:
            raise InvalidResearchSkillName(f"非法技能名称: {name}")
        for skill_dir in self._root.iterdir():
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            text = skill_file.read_text()
            if not text.startswith("---"):
                continue
            parts = text.split("---", 2)
            manifest = yaml.safe_load(parts[1])
            if manifest.get("name") == name:
                return LoadedResearchSkill(
                    name=name, version=manifest["version"],
                    body=parts[2].strip(),
                    allowed_tools=manifest.get("allowed_tools", []),
                )
        raise InvalidResearchSkillName(f"未找到技能: {name}")
