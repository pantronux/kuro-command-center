"""Panel renderers for the Telegram cockpit."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping

import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from kuro_backend.config import settings
from .models import Panel


def now_wib_label() -> str:
    tz = pytz.timezone(getattr(settings, "TIMEZONE", "Asia/Jakarta") or "Asia/Jakarta")
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M WIB")


def cockpit_markup(*, include_market: bool = True) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("System", callback_data="panel:status")]]
    if include_market:
        rows[0].append(InlineKeyboardButton("Market", callback_data="panel:sentinel"))
    rows.extend(
        [
            [
                InlineKeyboardButton("Intelligence", callback_data="panel:briefing"),
                InlineKeyboardButton("Queue", callback_data="panel:queue"),
            ],
            [
                InlineKeyboardButton("Chat", callback_data="panel:chat"),
                InlineKeyboardButton("Actions", callback_data="panel:actions"),
            ],
        ]
    )
    return InlineKeyboardMarkup(rows)


def back_home_markup(*, refresh_target: str | None = None) -> InlineKeyboardMarkup:
    row = []
    if refresh_target:
        row.append(InlineKeyboardButton("Refresh", callback_data=f"panel:{refresh_target}"))
    row.append(InlineKeyboardButton("Home", callback_data="home"))
    return InlineKeyboardMarkup([row])


def home_panel(display_name: str, *, include_market: bool = True) -> Panel:
    text = (
        "Kuro Telegram Cockpit\n"
        f"Operator: {display_name}\n"
        f"Time: {now_wib_label()}\n\n"
        "Pilih panel di bawah, atau kirim pesan biasa untuk chat langsung."
    )
    return Panel(text=text, reply_markup=cockpit_markup(include_market=include_market))


def help_panel(
    command_descriptions: Iterable[tuple[str, str]],
    *,
    include_market: bool = True,
) -> Panel:
    lines = [
        "Kuro Command Registry",
        f"Time: {now_wib_label()}",
        "",
    ]
    for name, description in command_descriptions:
        lines.append(f"{name} - {description}")
    return Panel(
        text="\n".join(lines),
        reply_markup=cockpit_markup(include_market=include_market),
    )


def ping_panel(queue_summary: Mapping[str, int]) -> Panel:
    text = (
        "Kuro Ping\n"
        f"Status: online\n"
        f"Time: {now_wib_label()}\n"
        f"Inbound queue: {queue_summary['inbound_size']}/{queue_summary['inbound_maxsize']}\n"
        f"DLQ pending: {queue_summary['dlq_pending']}"
    )
    return Panel(text=text, reply_markup=back_home_markup(refresh_target="ping"))


def queue_panel(queue_summary: Mapping[str, int]) -> Panel:
    text = (
        "Telegram Queue\n"
        f"Time: {now_wib_label()}\n"
        f"Inbound: {queue_summary['inbound_size']}/{queue_summary['inbound_maxsize']}\n"
        f"DLQ pending: {queue_summary['dlq_pending']}\n"
        f"DLQ sent: {queue_summary['dlq_sent']}\n"
        f"DLQ dead: {queue_summary['dlq_dead']}\n"
        f"DLQ total: {queue_summary['dlq_total']}"
    )
    return Panel(text=text, reply_markup=back_home_markup(refresh_target="queue"))


def status_panel(status: Mapping[str, object]) -> Panel:
    text = (
        "Kuro System Status\n"
        f"Time: {now_wib_label()}\n"
        f"CPU: {status['cpu_percent']}%\n"
        f"RAM: {status['ram_used_gb']}GB/{status['ram_total_gb']}GB ({status['ram_percent']}%)\n"
        f"Disk: {status['disk_used_gb']}GB/{status['disk_total_gb']}GB ({status['disk_percent']}%)\n"
        f"Backup: {status.get('backup_status', 'unknown')} at {status.get('backup_at', '-')}\n"
        f"Telegram inbound: {status['inbound_size']}/{status['inbound_maxsize']}; "
        f"DLQ pending: {status['dlq_pending']}"
    )
    return Panel(text=text, reply_markup=back_home_markup(refresh_target="status"))


def sentinel_panel(stale: bool, stocks: list[Mapping[str, object]]) -> Panel:
    lines = [
        "Market Sentinel",
        f"Time: {now_wib_label()}",
        f"Price data: {'STALE' if stale else 'fresh'}",
        "",
    ]
    if stocks:
        for stock in stocks[:5]:
            lines.append(
                f"{stock.get('stock_code', '-')} | Rp {stock.get('current_price_per_share', 0)} "
                f"| ROI 1M {stock.get('projected_roi_1m', 0)}% | {stock.get('conclusion', 'HOLD')}"
            )
    else:
        lines.append("Belum ada data Market Sentinel.")
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Run Sentinel", callback_data="action:run_sentinel")],
            [
                InlineKeyboardButton("Refresh", callback_data="panel:sentinel"),
                InlineKeyboardButton("Home", callback_data="home"),
            ],
        ]
    )
    return Panel(text="\n".join(lines), reply_markup=markup)


def briefing_panel(text: str) -> Panel:
    return Panel(text=text, reply_markup=back_home_markup(refresh_target="briefing"))


def chat_panel(selected_persona: str) -> Panel:
    text = (
        "Kuro Chat\n"
        f"Selected persona: {selected_persona}\n"
        f"Time: {now_wib_label()}\n\n"
        "Kirim pesan biasa untuk ngobrol. Ubah persona lewat tombol di bawah."
    )
    return Panel(text=text, reply_markup=persona_markup(selected_persona))


def persona_markup(selected_persona: str) -> InlineKeyboardMarkup:
    personas = ["tactical", "chill", "advisor", "auditor", "consultant"]
    rows = []
    for i in range(0, len(personas), 2):
        row = []
        for persona in personas[i : i + 2]:
            label = f"{persona}{' *' if persona == selected_persona else ''}"
            row.append(InlineKeyboardButton(label, callback_data=f"persona:{persona}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("Home", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def actions_panel(*, include_market: bool = True) -> Panel:
    text = (
        "Kuro Actions\n"
        f"Time: {now_wib_label()}\n\n"
        "Aksi mutating membutuhkan konfirmasi sebelum dijalankan."
    )
    rows = []
    if include_market:
        rows.append([InlineKeyboardButton("Run Sentinel", callback_data="action:run_sentinel")])
    rows.extend(
        [
            [InlineKeyboardButton("Run Backup", callback_data="action:run_backup")],
            [InlineKeyboardButton("Home", callback_data="home")],
        ]
    )
    markup = InlineKeyboardMarkup(rows)
    return Panel(text=text, reply_markup=markup)


def confirmation_panel(summary: str, token: str, confirm_label: str) -> Panel:
    text = (
        "Confirm Action\n"
        f"Time: {now_wib_label()}\n\n"
        f"{summary}\n\n"
        "Pilih Confirm untuk menjalankan aksi ini."
    )
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(confirm_label, callback_data=f"confirm:{token}"),
                InlineKeyboardButton("Cancel", callback_data=f"cancel:{token}"),
            ],
            [InlineKeyboardButton("Home", callback_data="home")],
        ]
    )
    return Panel(text=text, reply_markup=markup)


def action_result_panel(title: str, message: str) -> Panel:
    text = f"{title}\nTime: {now_wib_label()}\n\n{message}"
    return Panel(text=text, reply_markup=back_home_markup())
