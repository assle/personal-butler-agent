"""Skill 加载器测试"""
from pathlib import Path
import pytest
from src.research.skills.catalog import ResearchSkillCatalog
from src.research.skills.loader import ResearchSkillLoader, InvalidResearchSkillName

def test_catalog_exposes_metadata_without_full_body():
    catalog = ResearchSkillCatalog(Path("research_skills"))
    entries = catalog.list()
    assert len(entries) >= 1
    assert entries[0].name == "general-research"
    assert "source hierarchy" not in entries[0].description.lower()

def test_loader_loads_skill_by_name():
    catalog = ResearchSkillCatalog(Path("research_skills"))
    names = {s.name for s in catalog.list()}
    loader = ResearchSkillLoader(Path("research_skills"), names)
    skill = loader.load("general-research")
    assert skill.name == "general-research"
    assert len(skill.body) > 100

def test_loader_rejects_unknown_name():
    loader = ResearchSkillLoader(Path("research_skills"), {"general-research"})
    with pytest.raises(InvalidResearchSkillName):
        loader.load("nonexistent")

def test_loader_rejects_path_traversal():
    loader = ResearchSkillLoader(Path("research_skills"), {"general-research"})
    with pytest.raises(InvalidResearchSkillName):
        loader.load("../secret")
