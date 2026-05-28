from __future__ import annotations

from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler

from app.database import get_conn, get_setting, set_setting
from app.services.agents import frontier_agent, learning_agent
from app.services.notifications import notifications


class LocalScheduler:
    def __init__(self) -> None:
        self.scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self.started = False

    def start(self) -> None:
        if self.started:
            return
        self.scheduler.add_job(self.create_learning_reminder, "cron", hour=8, minute=30, id="learning_reminder", replace_existing=True)
        self.scheduler.add_job(self.create_frontier_report, "cron", hour=9, minute=0, id="frontier_report", replace_existing=True)
        self.scheduler.start()
        self.started = True

    def shutdown(self) -> None:
        if self.started:
            self.scheduler.shutdown(wait=False)
            self.started = False

    def catch_up(self) -> None:
        today = date.today().isoformat()
        last_dashboard = get_setting("last_dashboard_opened")
        if last_dashboard != today:
            self.create_learning_reminder()
            self.create_frontier_report()
            set_setting("last_dashboard_opened", today)

    def create_learning_reminder(self) -> None:
        plans = learning_agent.list_plans()
        if not plans:
            return
        plan = plans[0]
        day_index = self._next_day_index(plan["id"], plan["duration_days"])
        day = plan["plan"].get("days", [{}])[max(0, day_index - 1)]
        notifications.create(
            "今日学习提醒",
            f"{plan['topic']} 第 {day_index} 天：{day.get('goal', '按计划完成今日任务。')}",
            "learning",
            "learning",
            {"plan_id": plan["id"], "day": day_index},
        )

    def create_frontier_report(self) -> None:
        today = date.today().isoformat()
        with get_conn() as conn:
            row = conn.execute("SELECT id FROM frontier_reports WHERE report_date = ?", (today,)).fetchone()
        if not row:
            frontier_agent.run_daily()

    def _next_day_index(self, plan_id: int, duration_days: int) -> int:
        with get_conn() as conn:
            row = conn.execute("SELECT MAX(day_index) AS max_day FROM learning_progress WHERE plan_id = ?", (plan_id,)).fetchone()
        completed = row["max_day"] or 0
        return min(duration_days, completed + 1)


local_scheduler = LocalScheduler()
