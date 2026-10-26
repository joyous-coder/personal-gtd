"""personal-gtd 配置：默认值、加载、初始化。

配置文件只放非敏感项；滴答 token 与 FNS 凭据只从环境变量或外部文件读取，不写入这里。
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

DEFAULT_CONFIG_PATH = str(Path.home() / ".config" / "personal-gtd" / "config.json")
DEFAULT_DIDA_TOKEN_PATH = str(Path.home() / ".config" / "dida-cli" / "config.json")

DEFAULT_TAGS = {
    "consumption": "积分消费",
    "breakthrough": "突破",
    "interrupt_in": "内在干扰",
    "interrupt_out": "外在干扰",
    "u_event": "U事件",
}

# 这些字段必须是数值，JSON 里的 int/float 统一转成 float
_NUMERIC_FIELDS = (
    "salary",
    "reserve",
    "daily_cap",
    "weekly_cap",
    "day_rate",
    "week_rate",
    "month_budget_rate",
    "month_threshold",
)


@dataclass(frozen=True)
class Config:
    vault: str = "Obsidian_Vault"
    salary: float = 0.0
    reserve: float = 5.0
    daily_cap: float = 60.0
    weekly_cap: float = 360.0
    day_rate: float = 2.0
    week_rate: float = 1.0
    month_budget_rate: float = 0.1
    month_threshold: float = 0.6
    dida_base_url: str = "https://api.dida365.com/open/v1"
    dida_token_path: str = DEFAULT_DIDA_TOKEN_PATH
    #: GTD 输出的根目录（相对 vault 根）。skill 在它下面自己建
    #: `1-规划/` 与 `2-回顾/{1-日维度,2-周维度,3-月维度}/`。
    #: 环境变量 `PERSONAL_GTD_DIR` 可覆盖。
    gtd_dir: str = "7-规划回顾"
    #: 读方法论原文的目录（相对 vault 根）；只走配置文件——这是"读"的位置，
    #: 是你已有的笔记目录，不是 skill 建的
    theory_dir: str = "我的方法论"
    penalty_habit: str = "惩罚习惯"
    #: 滴答收集箱 ID（形如 `inbox<账号号>`）。收集箱不在 `GET /project` 列表里，
    #: 要单独拉；这个 ID 带账号号，属于账号相关数据，所以放 config 而不是代码里。
    #: 留空 = 不拉收集箱。
    inbox_id: str = ""
    config_path: str = DEFAULT_CONFIG_PATH
    tags: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TAGS))


def _expand_path(value: str) -> str:
    """把 `~` 展开成当前用户目录；跨机器/跨用户时不要写死绝对路径。"""
    return str(Path(value).expanduser()) if value else value


def _resolve_path(path: Path | None) -> Path:
    if path is None:
        path = os.environ.get("PERSONAL_GTD_CONFIG", DEFAULT_CONFIG_PATH)
    return Path(path).expanduser()


def _coerce(data: dict) -> dict:
    """只保留已知字段；数值字段转 float；tags 与默认值浅合并。"""
    known = {f.name for f in fields(Config)}
    values = {}
    for key, value in data.items():
        if key not in known:
            continue
        if key == "tags":
            if not isinstance(value, dict):
                raise ValueError("config 'tags' must be an object")
            merged = dict(DEFAULT_TAGS)
            merged.update({str(k): str(v) for k, v in value.items()})
            values[key] = merged
        elif key in _NUMERIC_FIELDS:
            try:
                values[key] = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"config '{key}' must be a number, got {value!r}") from exc
        elif key in ("dida_token_path", "config_path"):
            values[key] = _expand_path(str(value))
        else:
            values[key] = value
    return values


def _validate(cfg: Config) -> None:
    if not 0 <= cfg.reserve <= 10:
        raise ValueError(f"reserve must be within [0, 10], got {cfg.reserve}")
    if not math.isfinite(cfg.daily_cap) or cfg.daily_cap < 30:
        # 日分母 = min(daily_cap, max(30, 计划))；cap < 30 会让「30 分保底」失效
        raise ValueError(f"daily_cap must be a finite number >= 30, got {cfg.daily_cap}")
    if not math.isfinite(cfg.weekly_cap) or cfg.weekly_cap <= 0:
        raise ValueError(f"weekly_cap must be a finite number > 0, got {cfg.weekly_cap}")
    if not math.isfinite(cfg.day_rate) or cfg.day_rate <= 0:
        raise ValueError(f"day_rate must be a finite number > 0, got {cfg.day_rate}")
    if not math.isfinite(cfg.week_rate) or cfg.week_rate <= 0:
        raise ValueError(f"week_rate must be a finite number > 0, got {cfg.week_rate}")
    if not 0 <= cfg.month_threshold <= 1:
        raise ValueError(f"month_threshold must be within [0, 1], got {cfg.month_threshold}")


def load_config(path: Path | None = None) -> Config:
    """读配置；文件不存在时返回默认值。未知字段忽略，tags 浅合并。

    跨机器/跨用户约定：
    - 配置路径：显式参数 > `PERSONAL_GTD_CONFIG` > `~/.config/personal-gtd/config.json`
    - 滴答 token：`PERSONAL_GTD_DIDA_CONFIG` > config 里的 `dida_token_path`
    """
    p = _resolve_path(path)
    if not p.is_file():
        cfg = Config(config_path=str(p))
    else:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("config root must be a JSON object")
        cfg = Config(**_coerce(raw))
    if os.environ.get("PERSONAL_GTD_DIDA_CONFIG"):
        cfg = replace(cfg, dida_token_path=_expand_path(os.environ["PERSONAL_GTD_DIDA_CONFIG"]))
    # 目录：只留一个环境变量（GTD 输出根目录），其余子结构由 skill 自己建
    for env_name, field_name in (
        ("PERSONAL_GTD_DIR", "gtd_dir"),
    ):
        value = (os.environ.get(env_name) or "").strip()
        if value:
            cfg = replace(cfg, **{field_name: value.strip("/")})
    cfg = replace(cfg, config_path=str(p))
    _validate(cfg)
    return cfg


def init_config(path: Path | None = None) -> Config:
    """确保配置存在：建父目录，缺文件时写入默认值，返回当前配置。"""
    p = _resolve_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        defaults = replace(
            Config(),
            config_path=str(p),
            dida_token_path=_expand_path(
                os.environ.get("PERSONAL_GTD_DIDA_CONFIG", DEFAULT_DIDA_TOKEN_PATH)
            ),
        )
        p.write_text(
            json.dumps(asdict(defaults), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return load_config(p)
