from __future__ import annotations

import re
from difflib import SequenceMatcher
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List

from pptx import Presentation
from pptx.util import Inches, Pt

from app.database import DATA_DIR, from_json, get_conn, now_local, rows_to_dicts, to_json
from app.services.model_router import choose_model, deepseek_client
from app.services.notifications import notifications
from app.services.rag import rag_service


GENERATED_DIR = DATA_DIR / "generated"


AGENT_REGISTRY = [
    {
        "agent_id": "supervisor",
        "name": "主管 Agent",
        "description": "任务分发、上下文管理、模型路由和工具权限控制。",
        "enabled": True,
        "tools": ["model_router", "task_store", "notification_center", "rag"],
    },
    {
        "agent_id": "learning",
        "name": "学习规划 Agent",
        "description": "生成学习路线、每日计划、复盘问题，并根据进度调整计划。",
        "enabled": True,
        "tools": ["rag", "notification_center", "scheduler"],
    },
    {
        "agent_id": "ppt",
        "name": "PPT 制作 Agent",
        "description": "根据主题、风格和知识库素材生成 PPT 文件。",
        "enabled": True,
        "tools": ["rag", "pptx_generator", "file_store"],
    },
    {
        "agent_id": "frontier",
        "name": "前沿资讯 Agent",
        "description": "生成 AI 与金融量化领域的每日热点简报。",
        "enabled": True,
        "tools": ["web_search_adapter", "notification_center", "archive"],
    },
    {
        "agent_id": "paper",
        "name": "论文 Agent（预留）",
        "description": "后续实现论文逻辑、语言、图表和数据审查。",
        "enabled": False,
        "tools": ["rag", "document_parser"],
    },
    {
        "agent_id": "travel",
        "name": "旅游 Agent（预留）",
        "description": "后续实现旅游路线、实时天气、交通和机酒建议。",
        "enabled": False,
        "tools": ["web_search_adapter", "weather_adapter", "notification_center"],
    },
]


class SupervisorAgent:
    def route(self, message: str) -> Dict[str, Any]:
        lowered = message.lower()
        if "ppt" in lowered or "幻灯" in message:
            target = "ppt"
        elif "学习" in message or "计划" in message:
            target = "learning"
        elif "ai" in lowered or "量化" in message or "前沿" in message:
            target = "frontier"
        else:
            target = "learning"
        model = choose_model("supervisor", "cheap")
        return {"target_agent": target, "model": model.__dict__, "message": message}


class LearningAgent:
    TOPIC_ALIASES = [
        (r"深度学习|deeplearning|deep learning", "deeplearning"),
        (r"机器学习|machinelearning|machine learning", "machinelearning"),
        (r"强化学习|reinforcementlearning|reinforcement learning", "reinforcementlearning"),
        (r"迁移学习|transferlearning|transfer learning", "transferlearning"),
        (r"监督学习|supervisedlearning|supervised learning", "supervisedlearning"),
        (r"无监督学习|unsupervisedlearning|unsupervised learning", "unsupervisedlearning"),
        (r"自然语言处理|nlp|naturallanguageprocessing|natural language processing", "nlp"),
        (r"计算机视觉|cv|computervision|computer vision", "computervision"),
        (r"大语言模型|大模型|llm|largelanguagemodel|large language model", "llm"),
        (r"人工智能|ai|artificialintelligence|artificial intelligence", "ai"),
        (r"量化交易|量化金融|quant|quantitative", "quant"),
        (r"英语|english", "english"),
        (r"雅思|ielts", "ielts"),
        (r"托福|toefl", "toefl"),
        (r"python|py", "python"),
    ]
    TOPIC_GENERIC_WORDS = [
        "我想", "想要", "想", "帮我", "请帮我", "如何", "怎么", "怎样",
        "学习一下", "学习", "了解", "掌握", "熟悉", "入门", "进阶",
        "基础", "相关方面", "相关内容", "相关知识", "知识点", "知识",
        "方面", "相关", "课程", "教程", "计划", "内容", "体系",
        "系统", "系统性", "全面", "训练", "提升", "能力", "的", "之",
    ]

    def normalize_topic(self, topic: str) -> str:
        normalized = topic.strip().lower()
        normalized = re.sub(r"[\s\-_—–·.,，。:：;；!！?？()（）【】\[\]{}<>《》\"'“”‘’/\\|]+", "", normalized)
        normalized = normalized.replace("的", "").replace("之", "")
        for pattern, replacement in self.TOPIC_ALIASES:
            normalized = re.sub(pattern.replace(" ", ""), replacement, normalized, flags=re.IGNORECASE)
        for word in sorted(self.TOPIC_GENERIC_WORDS, key=len, reverse=True):
            normalized = normalized.replace(word, "")
        normalized = re.sub(r"(相关|课程|计划|学习|内容|知识|方面)+$", "", normalized)
        return normalized

    def topic_terms(self, topic: str) -> set[str]:
        normalized = self.normalize_topic(topic)
        terms = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", normalized))
        if not terms and normalized:
            terms.add(normalized)
        if len(normalized) >= 4:
            terms.update(normalized[index : index + 2] for index in range(len(normalized) - 1))
        return terms

    def is_same_topic(self, left: str, right: str) -> bool:
        left_norm = self.normalize_topic(left)
        right_norm = self.normalize_topic(right)
        if not left_norm or not right_norm:
            return False
        if left_norm == right_norm:
            return True
        if min(len(left_norm), len(right_norm)) >= 4:
            shorter, longer = sorted([left_norm, right_norm], key=len)
            if shorter in longer and len(shorter) / len(longer) >= 0.72:
                return True
        left_terms = self.topic_terms(left)
        right_terms = self.topic_terms(right)
        if left_terms and right_terms:
            overlap = len(left_terms & right_terms) / len(left_terms | right_terms)
            if overlap >= 0.72:
                return True
        return SequenceMatcher(None, left_norm, right_norm).ratio() >= 0.86

    def find_duplicate_plan_by_topic(self, topic: str) -> Dict[str, Any] | None:
        self.dedupe_active_plans()
        with get_conn() as conn:
            rows = rows_to_dicts(
                conn.execute(
                    """
                    SELECT * FROM learning_plans
                    WHERE status = 'active'
                    ORDER BY created_at DESC
                    """
                ).fetchall()
            )
        for row in rows:
            if self.is_same_topic(row["topic"], topic):
                row["plan"] = from_json(row["plan"], {})
                return row
        return None

    def dedupe_active_plans(self) -> List[int]:
        with get_conn() as conn:
            rows = rows_to_dicts(
                conn.execute(
                    """
                    SELECT * FROM learning_plans
                    WHERE status = 'active'
                    ORDER BY created_at ASC, id ASC
                    """
                ).fetchall()
            )
            keepers: List[Dict[str, Any]] = []
            duplicate_ids: List[int] = []
            for row in rows:
                duplicate_of_existing = any(self.is_same_topic(existing["topic"], row["topic"]) for existing in keepers)
                if duplicate_of_existing:
                    duplicate_ids.append(row["id"])
                else:
                    keepers.append(row)
            if duplicate_ids:
                placeholders = ",".join("?" for _ in duplicate_ids)
                conn.execute(
                    f"UPDATE learning_plans SET status = 'deleted', updated_at = ? WHERE id IN ({placeholders})",
                    (now_local(), *duplicate_ids),
                )
        return duplicate_ids

    def create_plan(
        self,
        topic: str,
        duration_days: int,
        daily_minutes: int,
        target_level: str,
        use_knowledge: bool = True,
    ) -> Dict[str, Any]:
        topic = topic.strip()
        target_level = target_level.strip()
        duplicate = self.find_duplicate_plan_by_topic(topic)
        if duplicate:
            notifications.create(
                "该计划已添加",
                f"{duplicate['topic'].strip()} 已存在学习计划，不会重复创建。",
                "info",
                "learning",
                {"plan_id": duplicate["id"], "duplicate": True},
            )
            return {
                "id": duplicate["id"],
                "duplicate": True,
                "message": "该计划已添加",
                **duplicate["plan"],
            }

        model = choose_model("learning", "default", uses_rag=use_knowledge)
        rag_context = rag_service.query(topic, limit=3) if use_knowledge else {"sources": []}
        plan = self._build_plan(topic, duration_days, daily_minutes, target_level, rag_context.get("sources", []), model.__dict__)
        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO learning_plans(topic, duration_days, daily_minutes, target_level, plan, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (topic, duration_days, daily_minutes, target_level, to_json(plan), now_local(), now_local()),
            )
            plan_id = cur.lastrowid
            conn.execute(
                """
                INSERT INTO tasks(agent_id, title, status, input, output, model_used, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("learning", f"学习计划：{topic}", "completed", to_json({"topic": topic}), to_json(plan), model.model, now_local(), now_local()),
            )
        notifications.create(
            "新的学习计划已生成",
            f"{topic} 的 {duration_days} 天计划已经准备好，今日任务会显示在首页。",
            "success",
            "learning",
            {"plan_id": plan_id},
        )
        return {"id": plan_id, **plan}

    def _build_plan(self, topic: str, duration_days: int, daily_minutes: int, target_level: str, rag_sources: List[Dict[str, Any]] | None = None, model: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if model and model.get("provider") == "deepseek" and deepseek_client.available:
            try:
                return self._build_plan_with_deepseek(topic, duration_days, daily_minutes, target_level, rag_sources or [], model)
            except Exception as exc:
                notifications.create(
                    "DeepSeek 计划生成已降级",
                    f"真实模型调用失败，已使用本地模板生成。原因：{exc}",
                    "warning",
                    "learning",
                    {"topic": topic},
                )
        phases = self._build_phases(topic, duration_days, target_level)
        days = []
        for day in range(1, duration_days + 1):
            phase = phases[min(len(phases) - 1, int((day - 1) / max(1, duration_days / len(phases))))]
            days.append(
                {
                    "day": day,
                    "title": f"{topic} Day {day}: {phase['name']}",
                    "goal": phase["goal"],
                    "minutes": daily_minutes,
                    "tasks": [
                        f"用 {max(15, daily_minutes // 3)} 分钟复习上一日关键点",
                        f"学习“{phase['name']}”核心概念并做结构化笔记",
                        "完成 3 个自测问题，记录不确定内容",
                    ],
                    "check": "用自己的话解释今日概念，并标记 0-100 的掌握度。",
                }
            )
        return {
            "topic": topic,
            "target_level": target_level,
            "duration_days": duration_days,
            "daily_minutes": daily_minutes,
            "phases": phases,
            "days": days,
            "rag_sources": rag_sources or [],
            "model": model or {},
        }

    def _build_plan_with_deepseek(
        self,
        topic: str,
        duration_days: int,
        daily_minutes: int,
        target_level: str,
        rag_sources: List[Dict[str, Any]],
        model: Dict[str, Any],
    ) -> Dict[str, Any]:
        source_summary = "\n".join(
            f"- {source.get('filename', '资料')}：{source.get('content', '')[:260]}" for source in rag_sources[:3]
        ) or "暂无知识库资料。"
        system = (
            "你是严谨的个人学习规划 Agent。请只输出合法 JSON，不要 Markdown。"
            "JSON 字段必须包含 phases 和 days。"
            "phases 是数组，每项包含 name, goal。"
            "days 是数组，长度必须等于 duration_days，每项包含 day, title, goal, minutes, tasks, check。"
            "tasks 是 3 到 5 个具体可执行任务。"
        )
        user = (
            f"学习主题：{topic}\n"
            f"学习期限：{duration_days} 天\n"
            f"每日学习时间：{daily_minutes} 分钟\n"
            f"目标程度：{target_level}\n"
            f"可参考资料：\n{source_summary}\n"
            "请生成循序渐进、每天任务不重复、适合个人执行的学习计划。"
        )
        generated = deepseek_client.chat_json(system, user, temperature=0.25, max_tokens=3000)
        phases = generated.get("phases") or self._build_phases(topic, duration_days, target_level)
        days = generated.get("days") or []
        if len(days) != duration_days:
            raise ValueError("DeepSeek 返回的 days 长度与学习期限不一致。")
        normalized_days = []
        for index, day in enumerate(days, start=1):
            normalized_days.append(
                {
                    "day": index,
                    "title": str(day.get("title") or f"{topic} Day {index}"),
                    "goal": str(day.get("goal") or f"完成 {topic} 第 {index} 天学习。"),
                    "minutes": int(day.get("minutes") or daily_minutes),
                    "tasks": [str(task) for task in (day.get("tasks") or [])][:5] or ["完成今日学习任务并记录问题。"],
                    "check": str(day.get("check") or "用自己的话复述今日重点，并记录掌握度。"),
                }
            )
        return {
            "topic": topic,
            "target_level": target_level,
            "duration_days": duration_days,
            "daily_minutes": daily_minutes,
            "phases": phases,
            "days": normalized_days,
            "rag_sources": rag_sources,
            "model": model,
        }

    def update_plan_settings(self, plan_id: int, duration_days: int, daily_minutes: int) -> Dict[str, Any]:
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM learning_plans WHERE id = ? AND status = 'active'", (plan_id,)).fetchone()
            if not row:
                return {"ok": False, "message": "学习计划不存在。"}
            old_plan = from_json(row["plan"], {})
            plan = self._build_plan(
                row["topic"],
                duration_days,
                daily_minutes,
                row["target_level"],
                old_plan.get("rag_sources", []),
                old_plan.get("model", {}),
            )
            conn.execute(
                """
                UPDATE learning_plans
                SET duration_days = ?, daily_minutes = ?, plan = ?, updated_at = ?
                WHERE id = ?
                """,
                (duration_days, daily_minutes, to_json(plan), now_local(), plan_id),
            )
            conn.execute("DELETE FROM learning_progress WHERE plan_id = ? AND day_index > ?", (plan_id, duration_days))
        notifications.create(
            "学习计划已更新",
            f"{row['topic']} 已调整为 {duration_days} 天、每日 {daily_minutes} 分钟。",
            "info",
            "learning",
            {"plan_id": plan_id},
        )
        return {"ok": True, "id": plan_id, **plan}

    def delete_plan(self, plan_id: int) -> Dict[str, Any]:
        with get_conn() as conn:
            row = conn.execute("SELECT topic FROM learning_plans WHERE id = ?", (plan_id,)).fetchone()
            if not row:
                return {"ok": False, "message": "学习计划不存在。"}
            conn.execute("UPDATE learning_plans SET status = 'deleted', updated_at = ? WHERE id = ?", (now_local(), plan_id))
        notifications.create(
            "学习计划已删除",
            f"{row['topic']} 已从计划列表移除。",
            "info",
            "learning",
            {"plan_id": plan_id},
        )
        return {"ok": True, "deleted_plan_id": plan_id}

    def record_progress(self, plan_id: int, day_index: int, completion: int, mastery: int, notes: str = "") -> Dict[str, Any]:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO learning_progress(plan_id, day_index, completion, mastery, notes, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (plan_id, day_index, completion, mastery, notes, now_local()),
            )
            row = conn.execute("SELECT * FROM learning_plans WHERE id = ?", (plan_id,)).fetchone()
            plan = from_json(row["plan"], {}) if row else {}
        adjustment = "按原计划继续。"
        if completion < 70 or mastery < 70:
            adjustment = "建议明天减少新内容，增加复习、错题整理和概念复述。"
        notifications.create("学习进度已记录", adjustment, "info", "learning", {"plan_id": plan_id, "day": day_index})
        return {"plan_id": plan_id, "day_index": day_index, "adjustment": adjustment, "plan": plan}

    def get_plan_detail(self, plan_id: int) -> Dict[str, Any]:
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM learning_plans WHERE id = ?", (plan_id,)).fetchone()
            if not row:
                return {"found": False, "message": "学习计划不存在。"}
            progress_rows = rows_to_dicts(
                conn.execute(
                    """
                    SELECT * FROM learning_progress
                    WHERE plan_id = ?
                    ORDER BY day_index ASC, created_at DESC, id DESC
                    """,
                    (plan_id,),
                ).fetchall()
            )

        detail = dict(row)
        detail["plan"] = from_json(detail["plan"], {})
        latest_by_day: Dict[int, Dict[str, Any]] = {}
        for item in progress_rows:
            latest_by_day.setdefault(item["day_index"], item)

        duration = max(1, detail["duration_days"])
        completion_sum = sum(item["completion"] for item in latest_by_day.values())
        mastery_values = [item["mastery"] for item in latest_by_day.values()]
        detail["progress"] = {
            "percent": round(min(100, completion_sum / duration), 1),
            "completed_days": len([item for item in latest_by_day.values() if item["completion"] >= 100]),
            "recorded_days": len(latest_by_day),
            "current_day": min(duration, len(latest_by_day) + 1),
            "average_mastery": round(sum(mastery_values) / len(mastery_values), 1) if mastery_values else 0,
            "latest_by_day": latest_by_day,
        }
        detail["found"] = True
        return detail

    def chat(self, plan_id: int, message: str, selected_day: int | None = None) -> Dict[str, Any]:
        detail = self.get_plan_detail(plan_id)
        if not detail.get("found"):
            return {"answer": "没有找到对应的学习计划。", "sources": []}

        plan = detail["plan"]
        day_index = selected_day or detail["progress"]["current_day"]
        days = plan.get("days", [])
        day = days[day_index - 1] if 0 < day_index <= len(days) else {}
        rag_context = rag_service.query(f"{detail['topic']} {message}", limit=3)
        model = choose_model("learning", "cheap", uses_rag=bool(rag_context.get("sources")))
        if model.provider == "deepseek" and deepseek_client.available:
            source_summary = "\n".join(
                f"- {source.get('filename', '资料')}：{source.get('content', '')[:260]}" for source in rag_context.get("sources", [])[:3]
            ) or "暂无知识库资料。"
            try:
                answer = deepseek_client.chat(
                    "你是个人学习规划 Agent，回答要具体、简洁、可执行。不要编造资料来源。",
                    (
                        f"学习计划：{detail['topic']}\n"
                        f"当前第 {day_index} 天目标：{day.get('goal', '当前阶段目标')}\n"
                        f"当天任务：{day.get('tasks', [])}\n"
                        f"知识库片段：\n{source_summary}\n"
                        f"用户问题：{message}"
                    ),
                    temperature=0.25,
                    max_tokens=900,
                )
            except Exception as exc:
                answer = f"DeepSeek 暂时不可用，先按本地策略回答：围绕第 {day_index} 天目标，先复述概念，再做一个小例子，最后记录不确定点。错误：{exc}"
        else:
            source_hint = ""
            if rag_context.get("sources"):
                source_hint = f"\n可参考知识库资料：{rag_context['sources'][0]['filename']}"
            answer = (
                f"围绕《{detail['topic']}》第 {day_index} 天的学习安排，建议你先聚焦："
                f"{day.get('goal', '当前阶段目标')}。\n"
                f"针对你的问题“{message}”，可以按三步处理：先复述概念，再做一个小例子，最后记录仍不确定的点。"
                f"{source_hint}"
            )
        return {"answer": answer, "sources": rag_context.get("sources", []), "day": day_index, "model": model.__dict__}

    def list_plans(self) -> List[Dict[str, Any]]:
        self.dedupe_active_plans()
        with get_conn() as conn:
            rows = rows_to_dicts(conn.execute("SELECT * FROM learning_plans WHERE status = 'active' ORDER BY created_at DESC").fetchall())
        for row in rows:
            row["plan"] = from_json(row["plan"], {})
        return rows

    def _build_phases(self, topic: str, duration_days: int, target_level: str) -> List[Dict[str, str]]:
        return [
            {"name": "建立知识地图", "goal": f"理解 {topic} 的核心概念、边界和常见应用。"},
            {"name": "系统学习与练习", "goal": f"围绕 {target_level} 目标完成主题学习、练习和案例分析。"},
            {"name": "项目化输出", "goal": f"用作品、总结或讲解验证自己是否达到 {target_level}。"},
        ]


class PPTAgent:
    def generate(self, topic: str, audience: str, style: str, slides: int, use_knowledge: bool = True) -> Dict[str, Any]:
        model = choose_model("ppt", "strong", needs_file=True, uses_rag=use_knowledge)
        rag_context = rag_service.query(topic, limit=5) if use_knowledge else {"sources": []}
        outline = self._outline(topic, audience, slides, rag_context.get("sources", []))
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"ppt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pptx"
        path = GENERATED_DIR / filename
        self._write_pptx(path, topic, audience, style, outline)
        output = {
            "topic": topic,
            "audience": audience,
            "style": style,
            "slides": outline,
            "file": f"/generated/{filename}",
            "model": model.__dict__,
            "sources": rag_context.get("sources", []),
        }
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO tasks(agent_id, title, status, input, output, model_used, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("ppt", f"PPT：{topic}", "completed", to_json({"topic": topic, "audience": audience}), to_json(output), model.model, now_local(), now_local()),
            )
        notifications.create("PPT 已生成", f"{topic} 的 PPT 已完成，可在 PPT 页面下载。", "success", "ppt", output)
        return output

    def list_jobs(self) -> List[Dict[str, Any]]:
        with get_conn() as conn:
            rows = rows_to_dicts(conn.execute("SELECT * FROM tasks WHERE agent_id = 'ppt' ORDER BY created_at DESC").fetchall())
        for row in rows:
            row["input"] = from_json(row["input"], {})
            row["output"] = from_json(row["output"], {})
        return rows

    def _outline(self, topic: str, audience: str, slides: int, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        base = [
            ("主题与目标", f"面向 {audience} 说明 {topic} 的背景、价值和本次汇报目标。"),
            ("核心框架", f"用 3-5 个模块建立 {topic} 的整体结构。"),
            ("关键内容", "结合知识库资料提炼概念、方法、案例或数据。"),
            ("实践路径", "给出可执行步骤、资源需求和风险点。"),
            ("总结与下一步", "凝练结论，并明确后续行动。"),
        ]
        outline = []
        for index in range(slides):
            title, body = base[index] if index < len(base) else (f"补充分析 {index + 1}", f"继续展开 {topic} 的细节。")
            citation = sources[index % len(sources)]["filename"] if sources else "暂无知识库引用"
            outline.append({"slide": index + 1, "title": title, "body": body, "citation": citation})
        return outline

    def _write_pptx(self, path: Path, topic: str, audience: str, style: str, outline: List[Dict[str, Any]]) -> None:
        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)
        title_slide = prs.slides.add_slide(prs.slide_layouts[0])
        title_slide.shapes.title.text = topic
        title_slide.placeholders[1].text = f"{audience} | {style}"
        for item in outline:
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = item["title"]
            body = slide.placeholders[1].text_frame
            body.clear()
            p = body.paragraphs[0]
            p.text = item["body"]
            p.font.size = Pt(22)
            cite = body.add_paragraph()
            cite.text = f"引用来源：{item['citation']}"
            cite.font.size = Pt(12)
        prs.save(path)


class FrontierAgent:
    def run_daily(self) -> Dict[str, Any]:
        model = choose_model("frontier", "default")
        today = date.today().isoformat()
        report = {
            "date": today,
            "sections": [
                {
                    "name": "AI 模型与产品",
                    "items": [
                        "关注主流模型更新、开源模型发布、Agent 工具链变化。",
                        "建议后续接入新闻搜索 API 后替换为实时来源。",
                    ],
                },
                {
                    "name": "金融与量化",
                    "items": [
                        "关注宏观数据、市场波动、量化平台工具和监管动态。",
                        "本地原型阶段生成结构化待查清单，避免伪造实时新闻。",
                    ],
                },
                {
                    "name": "行动建议",
                    "items": ["将高价值来源沉淀到知识库，周末做趋势复盘。"],
                },
            ],
            "model": model.__dict__,
            "sources": ["web_search_adapter:reserved"],
        }
        with get_conn() as conn:
            existing = conn.execute("SELECT id FROM frontier_reports WHERE report_date = ?", (today,)).fetchone()
            if existing:
                conn.execute("UPDATE frontier_reports SET content = ? WHERE id = ?", (to_json(report), existing["id"]))
                report_id = existing["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO frontier_reports(report_date, title, content, created_at) VALUES(?, ?, ?, ?)",
                    (today, f"{today} 前沿日报", to_json(report), now_local()),
                )
                report_id = cur.lastrowid
        notifications.create("今日前沿日报已生成", "AI 与金融量化日报已更新到前沿页面。", "info", "frontier", {"report_id": report_id})
        return {"id": report_id, **report}

    def list_reports(self) -> List[Dict[str, Any]]:
        with get_conn() as conn:
            rows = rows_to_dicts(conn.execute("SELECT * FROM frontier_reports ORDER BY report_date DESC LIMIT 30").fetchall())
        for row in rows:
            row["content"] = from_json(row["content"], {})
        return rows


supervisor_agent = SupervisorAgent()
learning_agent = LearningAgent()
ppt_agent = PPTAgent()
frontier_agent = FrontierAgent()
