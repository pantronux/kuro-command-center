"""Command routing for Telegram API V2."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from kuro_backend.config import settings
from kuro_backend.enterprise_flags import is_enabled
from kuro_backend.krc_profile import get_app_profile, is_krc_feature_enabled
from kuro_backend.telegram_v2.schemas import TelegramCommandResult


CommandHandler = Callable[..., Dict[str, Any] | str]


def command_name(text: str) -> str:
    first = (text or "").strip().split(maxsplit=1)[0].lower()
    if "@" in first:
        first = first.split("@", 1)[0]
    return first


def command_arg(text: str) -> str:
    parts = (text or "").strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


class TelegramV2CommandRouter:
    def __init__(
        self,
        *,
        chat_handler: Optional[CommandHandler] = None,
        market_handler: Optional[CommandHandler] = None,
        research_handler: Optional[CommandHandler] = None,
        task_handler: Optional[CommandHandler] = None,
        reminder_handler: Optional[CommandHandler] = None,
    ) -> None:
        self.chat_handler = chat_handler or self._default_chat
        self.market_handler = market_handler or self._default_market
        self.research_handler = research_handler or self._default_research
        self.task_handler = task_handler or self._default_task
        self.reminder_handler = reminder_handler or self._default_reminder

    def handle(self, *, text: str, username: str, chat_id: str, sender_id: str) -> TelegramCommandResult:
        cmd = command_name(text)
        arg = command_arg(text)
        if cmd in {"", "/start"}:
            return TelegramCommandResult(
                command="/start",
                action="start",
                response_text="Telegram API V2 is ready. Send /help for commands.",
            )
        if cmd == "/help":
            commands = ["/status", "/chat <message>", "/research <topic>"]
            if self._market_enabled():
                commands.append("/market <symbol>")
            if self._daily_tasks_enabled():
                commands.extend(["/task <title>", "/remind <time> <text>"])
            return TelegramCommandResult(
                command="/help",
                action="help",
                response_text="Commands: " + ", ".join(commands) + ".",
            )
        if cmd == "/status":
            return self._status()
        if cmd == "/chat":
            return self._wrap_result("/chat", "chat", self.chat_handler(username=username, chat_id=chat_id, message=arg))
        if cmd == "/research":
            return self._wrap_result("/research", "research", self.research_handler(username=username, chat_id=chat_id, topic=arg))
        if cmd == "/market":
            if not self._market_enabled():
                return TelegramCommandResult(
                    command="/market",
                    action="disabled",
                    response_text=(
                        "Market commands are disabled in KRC ops mode. "
                        "Enable KURO_KRC_MARKET_ENABLED=true to expose them."
                    ),
                )
            return self._wrap_result("/market", "market", self.market_handler(username=username, chat_id=chat_id, symbol=arg))
        if cmd == "/task":
            if not self._daily_tasks_enabled():
                return TelegramCommandResult(
                    command="/task",
                    action="disabled",
                    response_text="Daily task commands are disabled in KRC ops mode.",
                )
            return self._wrap_result("/task", "task", self.task_handler(username=username, chat_id=chat_id, title=arg))
        if cmd == "/remind":
            if not self._daily_tasks_enabled():
                return TelegramCommandResult(
                    command="/remind",
                    action="disabled",
                    response_text="Daily reminder commands are disabled in KRC ops mode.",
                )
            return self._wrap_result("/remind", "reminder", self.reminder_handler(username=username, chat_id=chat_id, text=arg))
        return self._wrap_result("/chat", "chat", self.chat_handler(username=username, chat_id=chat_id, message=text))

    @staticmethod
    def _market_enabled() -> bool:
        if get_app_profile() == "krc":
            return is_krc_feature_enabled("market")
        return True

    @staticmethod
    def _daily_tasks_enabled() -> bool:
        if get_app_profile() == "krc":
            return is_krc_feature_enabled("daily_tasks")
        return True

    def _status(self) -> TelegramCommandResult:
        from kuro_backend import intelligence_db

        dlq = intelligence_db.get_failed_notification_summary()
        return TelegramCommandResult(
            command="/status",
            action="status",
            response_text=(
                "Telegram API V2 status: "
                f"dlq_pending={int(dlq.get('pending', 0))}, "
                f"market_v2={is_enabled('KURO_MARKET_SENTINEL_V2_ENABLED')}, "
                f"tools_v2={is_enabled('KURO_AGENT_TOOLS_V2_ENABLED')}"
            ),
            data={"dlq": dlq},
        )

    def _wrap_result(self, command: str, action: str, result: Dict[str, Any] | str) -> TelegramCommandResult:
        if isinstance(result, dict):
            text = str(result.get("text") or result.get("message") or result.get("summary") or result)
            return TelegramCommandResult(command=command, action=action, response_text=text, data=result)
        return TelegramCommandResult(command=command, action=action, response_text=str(result or ""))

    def _default_chat(self, *, username: str, chat_id: str, message: str) -> Dict[str, Any]:
        if not message:
            return {"text": "Usage: /chat <message>"}
        from kuro_backend.langgraph_core import process_chat_with_graph

        response = process_chat_with_graph(
            message,
            persona_override="consultant",
            approval_scope=f"telegram_v2:{chat_id}:consultant",
            trace_id=f"telegram_v2_{chat_id}",
            session_id=f"telegram_v2_{chat_id}",
            username=username,
            chat_id=f"telegram_v2_{chat_id}",
            runtime_id="sovereign",
            runtime_namespace="kuro.sovereign",
        )
        return {"text": str(response), "runtime_id": "sovereign"}

    def _default_market(self, *, username: str, chat_id: str, symbol: str) -> Dict[str, Any]:
        if not is_enabled("KURO_MARKET_SENTINEL_V2_ENABLED"):
            return {"text": "Market Sentinel V2 is disabled."}
        from kuro_backend.market_v2.routes import MarketV2Service
        from kuro_backend.market_v2.schemas import MarketAnalyzeRequest

        result = MarketV2Service().analyze(
            username=username,
            request=MarketAnalyzeRequest(symbol=symbol or "", publish_alert=False),
        )
        report = result["report"]
        return {"text": report["summary"], "report_id": report["report_id"]}

    def _default_research(self, *, username: str, chat_id: str, topic: str) -> Dict[str, Any]:
        if not is_enabled("KURO_DEEP_RESEARCH_V2_ENABLED"):
            return {"text": "Deep Research V2 is disabled."}
        from kuro_backend.tools_v2.deep_research import DeepResearchService

        service = DeepResearchService()
        job = service.create_job(username=username, workspace_id="default", query=topic or "")
        completed = service.run_job(job.job_id) or job
        return {"text": f"Research job {completed.status}: {completed.job_id}", "job_id": completed.job_id}

    def _default_task(self, *, username: str, chat_id: str, title: str) -> Dict[str, Any]:
        if not bool(getattr(settings, "KURO_TASKS_V2_ENABLED", False)):
            return {"text": "Tasks V2 is disabled."}
        from kuro_backend.tools_v2.tasks import TaskStore

        task = TaskStore().create_task(username=username, title=title or "Telegram task", source_chat_id=chat_id)
        return {"text": f"Task created: {task['title']}", "task_id": task["task_id"]}

    def _default_reminder(self, *, username: str, chat_id: str, text: str) -> Dict[str, Any]:
        if not bool(getattr(settings, "KURO_TASKS_V2_ENABLED", False)):
            return {"text": "Reminders V2 is disabled."}
        parts = (text or "").split(maxsplit=1)
        remind_at = parts[0] if parts else ""
        label = parts[1] if len(parts) > 1 else "Telegram reminder"
        from kuro_backend.tools_v2.reminders import ReminderStore

        reminder = ReminderStore().create_reminder(
            username=username,
            remind_at=remind_at or "unspecified",
            channel="telegram",
            metadata={"text": label, "source_chat_id": chat_id},
        )
        return {"text": f"Reminder created: {reminder['remind_at']}", "reminder_id": reminder["reminder_id"]}
