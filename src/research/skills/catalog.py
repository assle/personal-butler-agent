"""研究 Skill 目录"""
from pathlib import Path
import yaml
from dataclasses import dataclass

@dataclass(frozen=True)
class ResearchSkillSummary:
    name: str
    version: str
    description: str
    applies_to: list[str]
    allowed_tools: list[str]

class ResearchSkillCatalog:
    def __init__(self, root: Path):
        self._root = root
        self._entries: list[ResearchSkillSummary] = []
        self._scan()

    def _scan(self):
        for skill_dir in self._root.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            text = skill_file.read_text()
            if not text.startswith("---"):
                continue
            parts = text.split("---", 2)
            manifest = yaml.safe_load(parts[1])
            self._entries.append(ResearchSkillSummary(
                name=manifest["name"], version=manifest["version"],
                description=manifest["description"],
                applies_to=manifest.get("applies_to", []),
                allowed_tools=manifest.get("allowed_tools", []),
            ))

    def list(self) -> list[ResearchSkillSummary]:
        return list(self._entries)
