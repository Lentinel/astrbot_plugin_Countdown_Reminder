import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register


PLUGIN_NAME = "astrbot_plugin_countdown_reminder"
EVENT_TEMPLATE_KEY = "countdown_event"


@dataclass(slots=True)
class CountdownEvent:
    name: str
    target_date: date


@register(
    PLUGIN_NAME,
    "Lentinel",
    "群聊倒计时播报插件，支持中文指令查询与每日定时提醒。",
    "1.0.0",
)
class CountdownReminderPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self._scheduler_task: asyncio.Task | None = None

    async def initialize(self) -> None:
        self._ensure_config_defaults()
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("CountdownReminderPlugin 初始化完成。")

    async def terminate(self) -> None:
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._scheduler_task

    @filter.command("添加倒计时")
    async def add_countdown(self, event: AstrMessageEvent):
        """添加一个新的倒计时事件。"""
        parsed = self._parse_add_command(event.message_str)
        if parsed is None:
            yield event.plain_result(self._help_text())
            return
        name, parsed_date = parsed
        name = self._normalize_name(name)
        if not name:
            yield event.plain_result(self._help_text())
            return

        today = self._today()
        if not self._allow_past_events() and parsed_date < today:
            yield event.plain_result("这个日期已经过去啦，默认不允许添加过去的事件。")
            return

        events = self._load_events()
        if any(self._normalize_name(item.name) == name for item in events):
            yield event.plain_result(f"“{name}” 已经在倒计时清单里啦，换个名字试试吧。")
            return

        events.append(CountdownEvent(name=name, target_date=parsed_date))
        self._save_events(events)

        days_left = (parsed_date - today).days
        if days_left == 0:
            text = f"已记下“{name}”，就是今天，冲呀！"
        else:
            text = f"已记下“{name}”，距离目标日还有 {days_left} 天。"
        yield event.plain_result(text)

    @filter.command("删除倒计时")
    async def delete_countdown(self, event: AstrMessageEvent):
        """删除一个倒计时事件。"""
        name = self._normalize_name(self._parse_delete_command(event.message_str))
        if not name:
            yield event.plain_result(
                "格式要这样写：/删除倒计时 事件名称\n例如：/删除倒计时 数学建模国赛"
            )
            return

        events = self._load_events()
        remaining = [
            item for item in events if self._normalize_name(item.name) != name
        ]
        if len(remaining) == len(events):
            yield event.plain_result(f"没有找到“{name}”，我这边还没记住它。")
            return

        self._save_events(remaining)
        yield event.plain_result(f"“{name}” 已从倒计时清单移除。")

    @filter.command("倒计时")
    async def show_countdowns(self, event: AstrMessageEvent):
        """查看当前所有倒计时事件。"""
        yield event.plain_result(self._render_summary(is_broadcast=False))

    @filter.command("倒计时帮助")
    async def countdown_help(self, event: AstrMessageEvent):
        """查看倒计时插件帮助。"""
        yield event.plain_result(self._help_text())

    @filter.command("开启倒计时播报")
    async def enable_broadcast(self, event: AstrMessageEvent):
        """把当前会话加入每日播报名单。"""
        targets = self._get_broadcast_targets()
        umo = event.unified_msg_origin
        if umo in targets:
            yield event.plain_result("这个会话已经在每日播报名单里啦。")
            return

        targets.append(umo)
        self.config["broadcast_targets"] = targets
        self.config.save_config()
        yield event.plain_result("已开启本会话的每日倒计时播报。")

    @filter.command("关闭倒计时播报")
    async def disable_broadcast(self, event: AstrMessageEvent):
        """把当前会话移出每日播报名单。"""
        targets = self._get_broadcast_targets()
        umo = event.unified_msg_origin
        if umo not in targets:
            yield event.plain_result("这个会话本来就没开启每日播报。")
            return

        targets = [item for item in targets if item != umo]
        self.config["broadcast_targets"] = targets
        self.config.save_config()
        yield event.plain_result("已关闭本会话的每日倒计时播报。")

    async def _scheduler_loop(self) -> None:
        while True:
            try:
                await self._maybe_broadcast()
            except Exception as exc:  # pragma: no cover - 防止后台任务静默崩溃
                logger.exception(f"倒计时定时任务执行失败: {exc}")
            await asyncio.sleep(30)

    async def _maybe_broadcast(self) -> None:
        targets = self._get_broadcast_targets()
        if not targets:
            return

        now = self._now()
        broadcast_hour, broadcast_minute = self._parse_broadcast_time(
            self.config.get("broadcast_time", "08:00")
        )
        if broadcast_hour is None or broadcast_minute is None:
            await self._maybe_warn_bad_broadcast_time(
                self.config.get("broadcast_time", "08:00")
            )
            return

        today_str = now.date().isoformat()
        last_broadcast_date = await self.get_kv_data("last_broadcast_date", "")
        has_reached_time = (now.hour, now.minute) >= (broadcast_hour, broadcast_minute)

        if not has_reached_time or last_broadcast_date == today_str:
            return

        summary = self._render_summary(is_broadcast=True)
        for target in targets:
            try:
                await self.context.send_message(target, MessageChain().message(summary))
            except Exception as exc:  # pragma: no cover - 平台差异较大
                logger.exception(f"发送倒计时播报失败，target={target}: {exc}")

        await self.put_kv_data("last_broadcast_date", today_str)

    def _render_summary(self, is_broadcast: bool) -> str:
        events = self._load_events()
        visible_lines = self._build_event_lines(events)

        if is_broadcast:
            if visible_lines:
                header = "早上好呀，今天的倒计时播报来啦："
                return "\n".join([header, *visible_lines])
            return "早上好呀，当前还没有可播报的倒计时事件。"

        if visible_lines:
            header = "倒计时清单已送达，请查收："
            return "\n".join([header, *visible_lines])
        return "现在还没有有效的倒计时事件，先用 /添加倒计时 记一条吧。\n发送 /倒计时帮助 可查看完整用法。"

    def _build_event_lines(self, events: list[CountdownEvent]) -> list[str]:
        today = self._today()
        allow_past = self._allow_past_events()
        lines: list[str] = []

        for item in sorted(events, key=lambda event: event.target_date):
            delta_days = (item.target_date - today).days
            if delta_days < 0 and not allow_past:
                continue

            if delta_days > 0:
                line = f"• {item.name}：还有 {delta_days} 天"
            elif delta_days == 0:
                line = f"• {item.name}：就是今天，准备出发"
            else:
                line = f"• {item.name}：已经过去 {abs(delta_days)} 天"
            lines.append(line)

        return lines

    def _load_events(self) -> list[CountdownEvent]:
        raw_events = self.config.get("events", [])
        events: list[CountdownEvent] = []

        if not isinstance(raw_events, list):
            logger.warning("events 配置不是列表，已忽略异常内容。")
            return events

        for raw in raw_events:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name", "")).strip()
            target_date = self._parse_iso_date(str(raw.get("target_date", "")).strip())
            if not name or target_date is None:
                continue
            events.append(CountdownEvent(name=self._normalize_name(name), target_date=target_date))

        return events

    def _save_events(self, events: list[CountdownEvent]) -> None:
        serialized = [
            {
                "__template_key": EVENT_TEMPLATE_KEY,
                "name": item.name,
                "target_date": item.target_date.isoformat(),
            }
            for item in sorted(events, key=lambda event: (event.target_date, event.name))
        ]
        self.config["events"] = serialized
        self.config.save_config()

    def _get_broadcast_targets(self) -> list[str]:
        raw_targets = self.config.get("broadcast_targets", [])
        if not isinstance(raw_targets, list):
            return []
        cleaned = [str(item).strip() for item in raw_targets if str(item).strip()]
        return list(dict.fromkeys(cleaned))

    def _ensure_config_defaults(self) -> None:
        changed = False
        defaults: dict[str, Any] = {
            "broadcast_time": "08:00",
            "broadcast_targets": [],
            "timezone": "Asia/Shanghai",
            "allow_past_events": False,
            "events": [],
        }
        for key, value in defaults.items():
            if key not in self.config:
                self.config[key] = value
                changed = True

        if changed:
            self.config.save_config()

    def _allow_past_events(self) -> bool:
        return bool(self.config.get("allow_past_events", False))

    def _parse_add_command(self, message: str) -> tuple[str, date] | None:
        body = self._extract_command_body(message, "添加倒计时")
        if not body:
            return None

        parts = body.rsplit(" ", 1)
        if len(parts) != 2:
            parts = body.rsplit(None, 1)
        if len(parts) != 2:
            return None

        name = parts[0].strip()
        target_date_text = parts[1].strip()
        if not name or not target_date_text:
            return None

        target_date = self._parse_iso_date(target_date_text)
        if target_date is None:
            return None
        return name, target_date

    def _parse_delete_command(self, message: str) -> str:
        return self._extract_command_body(message, "删除倒计时")

    def _extract_command_body(self, message: str, command_name: str) -> str:
        text = message.strip()
        prefixes = (f"/{command_name}", command_name)
        for prefix in prefixes:
            if text.startswith(prefix):
                return text[len(prefix) :].strip()
        return ""

    def _parse_iso_date(self, value: str) -> date | None:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    def _help_text(self) -> str:
        return "\n".join(
            [
                "倒计时插件使用说明：",
                "/添加倒计时 事件名称 YYYY-MM-DD",
                "示例：/添加倒计时 2026 考研 2025-12-20",
                "/删除倒计时 事件名称",
                "示例：/删除倒计时 2026 考研",
                "/倒计时",
                "/开启倒计时播报",
                "/关闭倒计时播报",
                "小提示：事件名称现在支持空格啦。",
            ]
        )

    def _normalize_name(self, name: str) -> str:
        return " ".join(name.split()).strip()

    async def _maybe_warn_bad_broadcast_time(self, value: str) -> None:
        value_str = str(value)
        today = self._today().isoformat()
        key = "broadcast_time_warning_state"
        state = await self.get_kv_data(key, {})
        if not isinstance(state, dict):
            state = {}

        if state.get("date") == today and state.get("value") == value_str:
            return

        logger.warning("broadcast_time 配置格式错误，正确格式应为 HH:MM。")
        await self.put_kv_data(key, {"date": today, "value": value_str})

    def _parse_broadcast_time(self, value: str) -> tuple[int | None, int | None]:
        try:
            parsed = datetime.strptime(value, "%H:%M")
        except ValueError:
            logger.warning("broadcast_time 配置格式错误，正确格式应为 HH:MM。")
            return None, None
        return parsed.hour, parsed.minute

    def _now(self) -> datetime:
        return datetime.now(self._get_timezone())

    def _today(self) -> date:
        return self._now().date()

    def _get_timezone(self) -> ZoneInfo:
        timezone_name = str(self.config.get("timezone", "Asia/Shanghai")).strip()
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            logger.warning(
                f"无效时区配置 {timezone_name}，已回退到 Asia/Shanghai。"
            )
            return ZoneInfo("Asia/Shanghai")
