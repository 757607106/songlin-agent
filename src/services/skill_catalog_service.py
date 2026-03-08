from __future__ import annotations

from pathlib import Path
from time import monotonic

from src import config as sys_config

_SKILL_CATALOG_CACHE_TTL_SECONDS = 10.0
_skill_catalog_cache: list[dict[str, str]] | None = None
_skill_catalog_cache_at: float = 0.0


def _skill_roots() -> list[Path]:
    roots: list[Path] = []
    save_root = Path(sys_config.save_dir) / "skills"
    roots.append(save_root)
    roots.append(Path("skills"))

    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return deduped


def _read_description(skill_file: Path) -> str:
    try:
        lines = skill_file.read_text(encoding="utf-8").splitlines()
    except Exception:
        return "No description"

    for line in lines[:30]:
        text = line.strip()
        if not text:
            continue
        if text.startswith("# "):
            return text[2:].strip()
        if text.lower().startswith("description:"):
            return text.split(":", 1)[1].strip() or "No description"
    return "No description"


def _skill_id_from_path(skill_file: Path, root: Path) -> str:
    try:
        relative = skill_file.parent.relative_to(root)
        if relative.parts:
            return "/".join(relative.parts)
    except Exception:
        pass
    return skill_file.parent.name


def clear_skill_catalog_cache() -> None:
    global _skill_catalog_cache, _skill_catalog_cache_at
    _skill_catalog_cache = None
    _skill_catalog_cache_at = 0.0


def _build_skill_catalog() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for root in _skill_roots():
        if not root.exists():
            continue
        for skill_file in root.rglob("SKILL.md"):
            if not skill_file.is_file():
                continue
            skill_id = _skill_id_from_path(skill_file, root)
            if skill_id in seen_ids:
                continue
            seen_ids.add(skill_id)
            items.append(
                {
                    "id": skill_id,
                    "name": skill_id,
                    "description": _read_description(skill_file),
                    "path": str(skill_file.resolve()),
                }
            )

    items.sort(key=lambda item: item["id"])
    return items


def list_skill_catalog(*, force_refresh: bool = False) -> list[dict[str, str]]:
    global _skill_catalog_cache, _skill_catalog_cache_at

    now = monotonic()
    if (
        not force_refresh
        and _skill_catalog_cache is not None
        and (now - _skill_catalog_cache_at) < _SKILL_CATALOG_CACHE_TTL_SECONDS
    ):
        return [dict(item) for item in _skill_catalog_cache]

    items = _build_skill_catalog()
    _skill_catalog_cache = items
    _skill_catalog_cache_at = now
    return [dict(item) for item in items]


def get_skill_names() -> list[str]:
    return [item["id"] for item in list_skill_catalog()]


def resolve_skill_sources(skill_refs: list[str] | None) -> list[str]:
    if not skill_refs:
        return []

    catalog = list_skill_catalog()
    id_to_path = {item["id"]: item["path"] for item in catalog}

    resolved: list[str] = []
    seen: set[str] = set()
    for ref in skill_refs:
        if not isinstance(ref, str):
            continue
        value = ref.strip()
        if not value:
            continue

        candidate: Path | None = None
        if value in id_to_path:
            candidate = Path(id_to_path[value])
        else:
            raw_path = Path(value).expanduser()
            probes: list[Path] = []
            if raw_path.is_absolute():
                probes.append(raw_path)
            else:
                probes.extend(
                    [
                        Path.cwd() / raw_path,
                        Path(sys_config.save_dir) / "skills" / raw_path,
                    ]
                )

            if not raw_path.name.endswith(".md"):
                probes.extend([probe / "SKILL.md" for probe in list(probes)])

            for probe in probes:
                path = probe
                if path.is_dir():
                    path = path / "SKILL.md"
                if path.is_file() and path.name == "SKILL.md":
                    candidate = path
                    break

        if candidate is None:
            continue

        abs_path = str(candidate.resolve())
        if abs_path in seen:
            continue
        seen.add(abs_path)
        resolved.append(abs_path)

    return resolved
