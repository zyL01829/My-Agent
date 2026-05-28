from __future__ import annotations

from typing import Any, Dict, List

from app.database import from_json, get_conn, now_local, rows_to_dicts, to_json


class InAppNotificationProvider:
    name = "in_app"

    def create(
        self,
        title: str,
        body: str,
        kind: str = "info",
        source_agent: str = "system",
        payload: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        with get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO notifications(title, body, kind, source_agent, payload, created_at)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (title, body, kind, source_agent, to_json(payload or {}), now_local()),
            )
            row = conn.execute("SELECT * FROM notifications WHERE id = ?", (cur.lastrowid,)).fetchone()
        item = dict(row)
        item["payload"] = from_json(item["payload"], {})
        return item

    def list(self, limit: int = 50, unread_only: bool = False) -> List[Dict[str, Any]]:
        query = "SELECT * FROM notifications"
        params: list[Any] = []
        if unread_only:
            query += " WHERE is_read = 0"
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with get_conn() as conn:
            rows = rows_to_dicts(conn.execute(query, params).fetchall())
        for row in rows:
            row["payload"] = from_json(row["payload"], {})
        return rows

    def mark_read(self, notification_id: int) -> None:
        with get_conn() as conn:
            conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))


class NotificationRegistry:
    def __init__(self) -> None:
        self.providers = {"in_app": InAppNotificationProvider()}

    def create(self, *args, provider: str = "in_app", **kwargs):
        return self.providers[provider].create(*args, **kwargs)


notifications = NotificationRegistry()
