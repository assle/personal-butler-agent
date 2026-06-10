"""
调度目标配置加载
读取并校验 SCHEDULER_TARGETS_FILE JSON，将配置转换为 webhook 调度目标。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.scheduler.models import WebhookSchedulerTarget


def load_webhook_targets(path: str) -> list[WebhookSchedulerTarget]:
    """从 JSON 文件读取企业微信群 webhook 定时推送目标

    参数:
        path: JSON 配置文件路径，内容为目标数组

    返回:
        list[WebhookSchedulerTarget]: 已启用和未启用目标的结构化配置列表
    """
    config_path = Path(path).expanduser()
    if not config_path.exists():
        raise ValueError(f"SCHEDULER_TARGETS_FILE 不存在: {config_path}")

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("SCHEDULER_TARGETS_FILE 必须是 JSON 数组")

    targets: list[WebhookSchedulerTarget] = []
    seen_names: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 个 scheduler target 必须是对象")
        name = str(item.get("name", "")).strip()
        display_name = str(item.get("display_name", "")).strip() or None
        cron = str(item.get("cron", "")).strip()
        webhook_url = str(item.get("webhook_url", "")).strip()
        message = str(item.get("message", "")).strip()
        mode = str(item.get("mode", "compose")).strip() or "compose"
        weather_query = str(item.get("weather_query", "")).strip() or None
        chat_id = str(item.get("chat_id", "")).strip() or None
        enabled = bool(item.get("enabled", True))
        aliases_raw = item.get("aliases", [])
        if aliases_raw is None:
            aliases_raw = []
        if not isinstance(aliases_raw, list):
            raise ValueError(f"第 {index} 个 scheduler target 的 aliases 必须是数组")
        aliases = tuple(str(alias).strip() for alias in aliases_raw if str(alias).strip())
        overrides_raw = item.get("mention_user_overrides", {})
        if overrides_raw is None:
            overrides_raw = {}
        if not isinstance(overrides_raw, dict):
            raise ValueError(
                f"第 {index} 个 scheduler target 的 mention_user_overrides 必须是对象"
            )
        mention_user_overrides = {
            str(key): str(value)
            for key, value in overrides_raw.items()
            if str(key) and str(value)
        }
        if not name or not cron or not webhook_url or not message:
            raise ValueError(
                "scheduler target 必须包含非空 name/cron/webhook_url/message"
            )
        if mode not in {"compose", "raw"}:
            raise ValueError(
                f"第 {index} 个 scheduler target 的 mode 必须是 compose 或 raw"
            )
        if mode == "compose" and weather_query:
            raise ValueError(
                f"第 {index} 个 scheduler target 的 weather_query 仅支持 raw mode"
            )
        if name in seen_names:
            raise ValueError(f"scheduler target name 重复: {name}")
        seen_names.add(name)
        targets.append(
            WebhookSchedulerTarget(
                name=name,
                display_name=display_name,
                cron=cron,
                webhook_url=webhook_url,
                message=message,
                mode=mode,
                weather_query=weather_query,
                chat_id=chat_id,
                enabled=enabled,
                aliases=aliases,
                mention_user_overrides=mention_user_overrides,
            )
        )
    return targets
