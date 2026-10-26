"""滴答清单 Open API 客户端。

只读：任务、清单、完成记录、专注记录、习惯与打卡。所有 HTTP/JSON 都收在
`DidaClient._request` 一个方法里，测试直接替换它，不碰真实网络。

时间约定：API 返回的 `completedTime` / `dueDate` 等是 UTC（`+0000`），
用户看到的是 +0800。`parse_dt` 统一转成 +0800 再返回，保证 `.date()`
落在用户的那一天。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

from .models import FocusRecord, FocusTask, Habit, Project, Task

TZ8 = timezone(timedelta(hours=8))

DEFAULT_BASE_URL = "https://api.dida365.com/open/v1"
# 收集箱 ID 形如 `inbox<账号号>`，带账号信息：放 config（`inbox_id`），不写死在代码里
DEFAULT_INBOX_ID = ""
INBOX_PROJECT_NAME = "收集箱"

# focus 接口单次查询上限 30 天，跨月要分段
FOCUS_MAX_DAYS = 30

_OFFSET_RE = re.compile(r"([+-])(\d{2})(\d{2})$")
_ZERO_FRACTION_RE = re.compile(r"\.0+(?=[+-]\d{2}:\d{2}$)")
_ESTIMATED_POMO_RE = re.compile(r"预计\s*(\d+)\s*🍅")


class DidaError(RuntimeError):
    """滴答 API 调用失败；`status` 是 HTTP 状态码（网络错误时为 None）。"""

    def __init__(self, status: int | None, message: str) -> None:
        super().__init__(message)
        self.status = status


def parse_dt(value: str | None) -> datetime | None:
    """把滴答的时间串解析成 +0800 的 aware datetime；空值返回 None。

    兼容 `2026-10-25T03:18:40.000+0000`、`...Z`、无时区等写法。
    无时区的值按 +0800（用户时区）解释。
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    text = _OFFSET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}:{m.group(3)}", text)
    text = _ZERO_FRACTION_RE.sub("", text)
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ8)
    return parsed.astimezone(TZ8)


def load_dida_token(path: Path) -> str:
    """从 dida-cli 的配置文件里取 `access_token`；`~` 会按当前用户展开。"""
    p = Path(path).expanduser()
    raw = json.loads(p.read_text(encoding="utf-8"))
    token = raw.get("access_token") if isinstance(raw, dict) else None
    if not token:
        raise ValueError(f"access_token missing in {p}")
    return str(token)


def _parse_stamp(value: Any) -> date | None:
    """打卡的 `stamp` 是 YYYYMMDD（也可能带时分秒），取前 8 位。"""
    text = str(value or "").strip()
    if len(text) < 8 or not text[:8].isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def _estimated_pomo(content: str | None) -> int | None:
    """预估番茄写在 content 里（如 `预计 3🍅`）。"""
    match = _ESTIMATED_POMO_RE.search(content or "")
    return int(match.group(1)) if match else None


def _iter_ranges(
    start: date, end: date, max_days: int = FOCUS_MAX_DAYS
) -> Iterator[tuple[date, date]]:
    """把 [start, end] 切成每段不超过 max_days 天的闭区间。"""
    current = start
    while current <= end:
        stop = min(end, current + timedelta(days=max_days - 1))
        yield current, stop
        current = stop + timedelta(days=1)


def _day_bound(day: date, *, end_of_day: bool) -> str:
    """focus / completed 接口的时间串格式：`YYYY-MM-DDTHH:mm:ss+0800`。"""
    clock = "23:59:59" if end_of_day else "00:00:00"
    return f"{day.isoformat()}T{clock}+0800"


class DidaClient:
    """滴答 Open API 的只读客户端。"""

    def __init__(
        self,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        inbox_id: str = DEFAULT_INBOX_ID,
    ) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.inbox_id = inbox_id

    # ---------- HTTP 缝合层 ----------

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        query: dict | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if query:
            clean = {k: v for k, v in query.items() if v is not None}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean)}"
        data = (
            None
            if body is None
            else json.dumps(body, ensure_ascii=False).encode("utf-8")
        )
        request = urllib.request.Request(
            url,
            data=data,
            method=method.upper(),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:300]
            except Exception:  # pragma: no cover - 读错误体失败不影响主错误
                detail = ""
            message = f"{method.upper()} {path} failed: HTTP {exc.code} {detail}".strip()
            raise DidaError(exc.code, message) from exc
        except urllib.error.URLError as exc:
            raise DidaError(
                None, f"{method.upper()} {path} failed: {exc.reason}"
            ) from exc
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))

    # ---------- 解析 ----------

    def _parse_task(self, raw: dict, project_id: str, project_name: str) -> Task:
        child_ids = raw.get("childIds") or ()
        if isinstance(child_ids, str):
            child_ids = (child_ids,)
        tags = raw.get("tags") or ()
        if isinstance(tags, str):
            tags = (tags,)
        content = raw.get("content")
        return Task(
            id=str(raw.get("id") or ""),
            project_id=str(raw.get("projectId") or project_id or ""),
            project_name=project_name,
            title=raw.get("title") or "",
            priority=int(raw.get("priority") or 0),
            due_date=parse_dt(raw.get("dueDate")),
            start_date=parse_dt(raw.get("startDate")),
            completed_time=parse_dt(raw.get("completedTime")),
            repeat_flag=raw.get("repeatFlag"),
            parent_id=raw.get("parentId"),
            child_ids=tuple(str(item) for item in child_ids),
            tags=tuple(str(item) for item in tags),
            estimated_pomo=_estimated_pomo(content),
            content=content,
        )

    def _parse_focus(self, raw: dict) -> FocusRecord | None:
        start = parse_dt(raw.get("startTime"))
        end = parse_dt(raw.get("endTime"))
        if start is None or end is None:
            return None
        tasks = []
        for item in raw.get("tasks") or ():
            if not isinstance(item, dict):
                continue
            task_id = item.get("taskId")
            task_start = parse_dt(item.get("startTime"))
            task_end = parse_dt(item.get("endTime"))
            if not task_id or task_start is None or task_end is None:
                # 没挂任务的自由专注不计入任务时长
                continue
            tasks.append(
                FocusTask(task_id=str(task_id), start=task_start, end=task_end)
            )
        return FocusRecord(
            id=str(raw.get("id") or ""),
            type=int(raw.get("type") or 0),
            start=start,
            end=end,
            tasks=tuple(tasks),
        )

    # ---------- 读接口 ----------

    def projects(self) -> list[Project]:
        data = self._request("GET", "/project") or []
        projects = []
        for raw in data:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            projects.append(Project(id=str(raw["id"]), name=raw.get("name") or ""))
        return projects

    def project_tasks(self, project_id: str, project_name: str) -> list[Task]:
        data = self._request("GET", f"/project/{project_id}/data") or {}
        if not isinstance(data, dict):
            return []
        # inbox 的响应里没有 `project` 键，名字只能用调用方传入的
        meta = data.get("project")
        fallback = meta.get("name") if isinstance(meta, dict) else None
        name = project_name or fallback or ""
        tasks = []
        for raw in data.get("tasks") or ():
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            tasks.append(self._parse_task(raw, project_id, name))
        return tasks

    def all_open_tasks(self) -> list[Task]:
        """所有清单 + 收集箱的未完成任务，按 task id 去重。"""
        collected: dict[str, Task] = {}
        seen_projects: set[str] = set()
        for project in self.projects():
            if project.id in seen_projects or project.id == self.inbox_id:
                continue
            seen_projects.add(project.id)
            for task in self.project_tasks(project.id, project.name):
                collected.setdefault(task.id, task)
        if self.inbox_id and self.inbox_id not in seen_projects:
            for task in self.project_tasks(self.inbox_id, INBOX_PROJECT_NAME):
                collected.setdefault(task.id, task)
        return list(collected.values())

    def completed_tasks(self, start: date, end: date) -> list[Task]:
        """完成记录。只传日期区间：带 `projectIds` 会返回 0 条。"""
        body = {
            "startDate": _day_bound(start, end_of_day=False),
            "endDate": _day_bound(end, end_of_day=True),
        }
        data = self._request("POST", "/task/completed", body=body)
        if isinstance(data, dict):
            rows = data.get("tasks") or ()
        else:
            rows = data or ()
        tasks = []
        for raw in rows:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            # 这个接口不返回清单名，`project_name` 留空，由上层按需补
            tasks.append(self._parse_task(raw, str(raw.get("projectId") or ""), ""))
        return tasks

    def focus(self, start: date, end: date, focus_type: int) -> list[FocusRecord]:
        """专注记录；单次查询 ≤30 天，超了自动分段。"""
        records: list[FocusRecord] = []
        for chunk_start, chunk_end in _iter_ranges(start, end):
            data = (
                self._request(
                    "GET",
                    "/focus",
                    query={
                        "from": _day_bound(chunk_start, end_of_day=False),
                        "to": _day_bound(chunk_end, end_of_day=True),
                        "type": focus_type,
                    },
                )
                or []
            )
            for raw in data:
                if not isinstance(raw, dict):
                    continue
                record = self._parse_focus(raw)
                if record is not None:
                    records.append(record)
        return records

    def habits(self) -> list[Habit]:
        data = self._request("GET", "/habit") or []
        habits = []
        for raw in data:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            goal = raw.get("goal")
            habits.append(
                Habit(
                    id=str(raw["id"]),
                    name=raw.get("name") or "",
                    goal=1.0 if goal is None else float(goal),
                )
            )
        return habits

    def habit_checkins(
        self,
        habit_ids: Sequence[str],
        start: date,
        end: date,
    ) -> dict[tuple[str, date], float]:
        """打卡值按 (habitId, 日期) 展开；参数名是 `habitIds`，不是 `habits`。

        **`to` 是排他的**（实测：`from=20261023&to=20261023` 返回空，
        `from=20261023&to=20261024` 才返回 10-23 的打卡），所以闭区间
        `[start, end]` 要传 `to = end + 1 天`。
        """
        ids = [str(habit_id) for habit_id in habit_ids]
        if not ids:
            return {}
        data = (
            self._request(
                "GET",
                "/habit/checkins",
                query={
                    "habitIds": ",".join(ids),
                    "from": start.strftime("%Y%m%d"),
                    "to": (end + timedelta(days=1)).strftime("%Y%m%d"),
                },
            )
            or []
        )
        values: dict[tuple[str, date], float] = {}
        for entry in data:
            if not isinstance(entry, dict):
                continue
            habit_id = str(entry.get("habitId") or "")
            for checkin in entry.get("checkins") or ():
                if not isinstance(checkin, dict):
                    continue
                day = _parse_stamp(checkin.get("stamp"))
                if day is None:
                    continue
                values[(habit_id, day)] = float(checkin.get("value") or 0)
        return values
