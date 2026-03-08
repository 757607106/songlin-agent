from __future__ import annotations

from pathlib import Path

from src.services import skill_catalog_service


def test_list_skill_catalog_discovers_skill_files(tmp_path, monkeypatch):
    skill_catalog_service.clear_skill_catalog_cache()
    root = tmp_path / "skills"
    skill_dir = root / "team" / "research"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Research Skill\n\nDescription line", encoding="utf-8")

    monkeypatch.setattr(skill_catalog_service, "_skill_roots", lambda: [root])

    items = skill_catalog_service.list_skill_catalog()
    assert len(items) == 1
    assert items[0]["id"] == "team/research"
    assert items[0]["name"] == "team/research"
    assert items[0]["path"] == str(skill_file.resolve())
    assert items[0]["description"] == "Research Skill"


def test_resolve_skill_sources_supports_id_and_path(tmp_path, monkeypatch):
    skill_catalog_service.clear_skill_catalog_cache()
    root = tmp_path / "skills"
    skill_dir = root / "ops" / "writer"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Writer Skill", encoding="utf-8")

    monkeypatch.setattr(skill_catalog_service, "_skill_roots", lambda: [root])

    by_id = skill_catalog_service.resolve_skill_sources(["ops/writer"])
    by_file = skill_catalog_service.resolve_skill_sources([str(skill_file)])
    by_dir = skill_catalog_service.resolve_skill_sources([str(skill_dir)])

    assert by_id == [str(skill_file.resolve())]
    assert by_file == [str(skill_file.resolve())]
    assert by_dir == [str(skill_file.resolve())]


def test_list_skill_catalog_uses_cache_until_forced_refresh(tmp_path, monkeypatch):
    skill_catalog_service.clear_skill_catalog_cache()
    root = tmp_path / "skills"
    first_dir = root / "a"
    second_dir = root / "b"
    first_dir.mkdir(parents=True)
    (first_dir / "SKILL.md").write_text("# A Skill", encoding="utf-8")
    monkeypatch.setattr(skill_catalog_service, "_skill_roots", lambda: [root])

    first = skill_catalog_service.list_skill_catalog()
    assert [item["id"] for item in first] == ["a"]

    second_dir.mkdir(parents=True)
    (second_dir / "SKILL.md").write_text("# B Skill", encoding="utf-8")

    # Cached call should still return previous snapshot.
    cached = skill_catalog_service.list_skill_catalog()
    assert [item["id"] for item in cached] == ["a"]

    refreshed = skill_catalog_service.list_skill_catalog(force_refresh=True)
    assert [item["id"] for item in refreshed] == ["a", "b"]
