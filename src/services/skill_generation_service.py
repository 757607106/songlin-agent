from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from src import config as sys_config
from src.agents.common import load_chat_model
from src.services.text2sql_service import text2sql_service
from src.utils import logger


def _slugify(text: str) -> str:
    raw = (text or "").strip().lower()
    raw = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", raw)
    return raw.strip("-") or "skill"


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-z0-9\u4e00-\u9fff_]+", text or "") if len(t) > 1}


class SkillGenerationService:
    def __init__(self):
        self._root = Path(sys_config.save_dir) / "skills" / "reporter"

    def _published_root(self, department_id: int, connection_id: int) -> Path:
        return self._root / str(department_id) / str(connection_id) / "published"

    def _draft_root(self, department_id: int, connection_id: int) -> Path:
        return self._root / str(department_id) / str(connection_id) / "drafts"

    def _meta_path(self, skill_dir: Path) -> Path:
        return skill_dir / "skill.meta.json"

    def _skill_file_path(self, skill_dir: Path) -> Path:
        return skill_dir / "SKILL.md"

    def _build_question(self, business_scenario: str, target_metrics: list[str], constraints: list[str]) -> str:
        metric_text = "、".join(target_metrics) if target_metrics else "核心指标"
        constraint_text = "；".join(constraints) if constraints else "无额外约束"
        return f"业务场景：{business_scenario}。关注指标：{metric_text}。约束：{constraint_text}。"

    def _rank_tables(self, schema_tables: list[dict], business_question: str) -> list[dict]:
        question_tokens = _tokenize(business_question)
        scored = []
        for table in schema_tables:
            table_name = str(table.get("table_name", ""))
            table_comment = str(table.get("table_comment", ""))
            columns = table.get("columns", []) or []
            table_tokens = _tokenize(f"{table_name} {table_comment}")
            score = len(question_tokens & table_tokens) * 2
            matched_columns = []
            for col in columns:
                col_name = str(col.get("column_name", ""))
                col_comment = str(col.get("column_comment", ""))
                col_tokens = _tokenize(f"{col_name} {col_comment}")
                col_score = len(question_tokens & col_tokens)
                if col_score > 0:
                    score += col_score
                    matched_columns.append(col_name)
            scored.append(
                {
                    "table_name": table_name,
                    "table_comment": table_comment,
                    "columns": columns,
                    "score": score,
                    "matched_columns": sorted(set(matched_columns)),
                }
            )
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    async def _build_skill_content(
        self,
        *,
        skill_name: str,
        business_scenario: str,
        target_metrics: list[str],
        constraints: list[str],
        selected_tables: list[dict],
        analysis: dict[str, Any],
    ) -> str:
        metrics_text = "、".join(target_metrics) if target_metrics else "业务核心指标"
        selected_table_brief = []
        for table in selected_tables[:8]:
            cols = [
                str(col.get("column_name", "")) for col in (table.get("columns") or [])[:10] if col.get("column_name")
            ]
            selected_table_brief.append(
                {
                    "table_name": table.get("table_name"),
                    "table_comment": table.get("table_comment"),
                    "columns": cols,
                    "matched_columns": table.get("matched_columns", []),
                }
            )
        draft_payload = {
            "business_scenario": business_scenario,
            "target_metrics": target_metrics,
            "constraints": constraints,
            "analysis": analysis,
            "tables": selected_table_brief,
        }
        prompt = (
            "你是资深数据分析架构师。请根据输入生成 DeepAgents 可用的 SKILL.md 文件内容。\n"
            "必须满足：\n"
            "1) 输出完整 Markdown，包含 frontmatter（name, description）\n"
            "2) description 必须说明技能做什么 + 何时触发\n"
            "3) 正文结构包含：Overview、Instructions、Clarification Rules、Metric Rules、Output Contract\n"
            "4) 澄清问题必须是业务语言，不能出现技术词（如字段名/索引/join）\n"
            "5) SQL 规则中只能引用输入中存在的表与字段\n"
            "6) 语言使用中文\n"
            "7) 不要输出多余解释，只输出 SKILL.md 内容\n\n"
            f"技能名建议：{skill_name}\n"
            f"业务场景：{business_scenario}\n"
            f"核心指标：{metrics_text}\n"
            f"输入数据：{json.dumps(draft_payload, ensure_ascii=False)}"
        )
        try:
            model = load_chat_model(sys_config.default_model)
            resp = await model.ainvoke([HumanMessage(content=prompt)])
            content = (resp.content or "").strip()
            if content.startswith("```markdown"):
                content = content[11:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            if content and content.startswith("---") and "description:" in content:
                return content
        except Exception as exc:
            logger.warning(f"SkillGenerationService: llm skill draft failed, fallback template used: {exc}")

        table_lines = []
        for item in selected_table_brief[:5]:
            matched = ", ".join(item.get("matched_columns")[:8]) or "需进一步确认"
            table_lines.append(f"- {item.get('table_name')}: {matched}")
        clarification = "\n".join(
            [
                "- 当前指标按哪个业务口径统计（例如订单口径、支付口径、签约口径）？",
                "- 时间范围与统计粒度是什么（天/周/月/季度）？",
                "- 是否需要按区域、渠道、门店、客户类型等维度拆分？",
            ]
        )
        return (
            f"---\n"
            f'name: "{skill_name}"\n'
            f'description: "根据{business_scenario}自动分析指标与数据口径。'
            f'Invoke when 用户咨询该业务场景或相关指标分析。"\n'
            f"---\n\n"
            f"# {business_scenario} 技能\n\n"
            f"## Overview\n"
            f"该技能用于围绕「{business_scenario}」完成指标分析、口径澄清与 SQL 约束生成。\n\n"
            f"## Instructions\n"
            f"1. 先识别用户请求是否属于该业务场景。\n"
            f"2. 根据 Metric Rules 对指标进行拆解并生成查询约束。\n"
            f"3. 若口径不完整，按 Clarification Rules 进行业务澄清。\n"
            f"4. 返回结构化分析结论与下一步建议。\n\n"
            f"## Clarification Rules\n"
            f"{clarification}\n\n"
            f"## Metric Rules\n"
            f"- 核心指标：{metrics_text}\n"
            f"- 优先关联表：\n"
            f"{chr(10).join(table_lines) if table_lines else '- 暂无高置信关联表，需先进行 schema 澄清'}\n\n"
            f"## Output Contract\n"
            f"- 输出必须包含：分析目标、指标定义、口径说明、风险提示、建议动作。\n"
            f"- 对每个指标给出可执行的计算说明。\n"
        )

    async def generate_reporter_skill(
        self,
        *,
        department_id: int,
        connection_id: int,
        business_scenario: str,
        target_metrics: list[str] | None = None,
        constraints: list[str] | None = None,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        target_metrics = [m.strip() for m in (target_metrics or []) if m and str(m).strip()]
        constraints = [c.strip() for c in (constraints or []) if c and str(c).strip()]
        if not business_scenario.strip():
            raise ValueError("business_scenario 不能为空")

        question = self._build_question(business_scenario, target_metrics, constraints)
        schema = await text2sql_service.get_schema(connection_id)
        analysis_payload = await text2sql_service.analyze_query(question)
        analysis = analysis_payload.get("analysis", {}) if isinstance(analysis_payload, dict) else {}
        tables = schema.get("tables", []) if isinstance(schema, dict) else []
        ranked = self._rank_tables(tables, question)
        selected_tables = [item for item in ranked if item["score"] > 0][:8]
        if not selected_tables:
            selected_tables = ranked[:5]

        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        skill_slug = _slugify(business_scenario)[:40]
        skill_id = f"{skill_slug}-{timestamp}"
        skill_name = f"reporter-{skill_slug}"

        skill_content = await self._build_skill_content(
            skill_name=skill_name,
            business_scenario=business_scenario,
            target_metrics=target_metrics,
            constraints=constraints,
            selected_tables=selected_tables,
            analysis=analysis if isinstance(analysis, dict) else {},
        )

        draft_root = self._draft_root(department_id, connection_id)
        skill_dir = draft_root / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file = self._skill_file_path(skill_dir)
        meta_file = self._meta_path(skill_dir)
        now_iso = datetime.now(UTC).isoformat()
        meta = {
            "id": skill_id,
            "name": skill_name,
            "status": "draft",
            "department_id": department_id,
            "connection_id": connection_id,
            "business_scenario": business_scenario,
            "target_metrics": target_metrics,
            "constraints": constraints,
            "selected_tables": [t.get("table_name") for t in selected_tables],
            "created_by": created_by,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        skill_file.write_text(skill_content, encoding="utf-8")
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"meta": meta, "skill_file": str(skill_file)}

    def _read_meta(self, skill_dir: Path, status: str) -> dict[str, Any] | None:
        meta_file = self._meta_path(skill_dir)
        if not meta_file.exists():
            return None
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            meta["status"] = status
            meta["skill_file"] = str(self._skill_file_path(skill_dir))
            return meta
        except Exception:
            return None

    async def list_reporter_skills(self, *, department_id: int, connection_id: int) -> list[dict[str, Any]]:
        drafts = self._draft_root(department_id, connection_id)
        published = self._published_root(department_id, connection_id)
        items: list[dict[str, Any]] = []
        for root, status in ((drafts, "draft"), (published, "published")):
            if not root.exists():
                continue
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                meta = self._read_meta(child, status)
                if meta:
                    items.append(meta)
        items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return items

    async def publish_reporter_skill(
        self, *, department_id: int, connection_id: int, skill_id: str, updated_by: str | None = None
    ) -> dict[str, Any]:
        draft_dir = self._draft_root(department_id, connection_id) / skill_id
        if not draft_dir.exists():
            raise FileNotFoundError("技能草稿不存在")
        published_dir = self._published_root(department_id, connection_id) / skill_id
        if published_dir.exists():
            shutil.rmtree(published_dir)
        published_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(draft_dir, published_dir)

        meta_file = self._meta_path(published_dir)
        meta = {}
        if meta_file.exists():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        meta["status"] = "published"
        meta["updated_by"] = updated_by
        meta["updated_at"] = datetime.now(UTC).isoformat()
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"meta": meta, "skill_file": str(self._skill_file_path(published_dir))}

    async def resolve_reporter_skill_sources(
        self, *, department_id: int | None, connection_id: int, skill_ids: list[str] | None = None
    ) -> list[str]:
        if department_id is None:
            return []
        published_root = self._published_root(department_id, connection_id)
        if not published_root.exists():
            return []
        allowed = set(skill_ids or [])
        sources = []
        for child in sorted(published_root.iterdir()):
            if not child.is_dir():
                continue
            if allowed and child.name not in allowed:
                continue
            skill_file = self._skill_file_path(child)
            if skill_file.exists():
                sources.append(str(child))
        return sources


skill_generation_service = SkillGenerationService()
