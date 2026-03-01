"""Global task progress feedback for Telegram Bot.

Provides a reusable async context manager that displays a text-based progress
bar inside a Telegram message, with step descriptions and auto-pulse animation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from telegram import Message

logger = logging.getLogger(__name__)


@dataclass
class TaskStep:
    """A single step in a multi-step task."""

    name_zh: str
    name_en: str
    weight: float = 1.0


class TaskProgressManager:
    """Async context manager for displaying task progress in a Telegram message.

    Usage::

        steps = [
            TaskStep("正在获取数据", "Fetching data"),
            TaskStep("AI 分析中", "AI analyzing", weight=3.0),
            TaskStep("格式化结果", "Formatting results"),
        ]
        async with TaskProgressManager(msg, steps, language="zh") as progress:
            await do_fetch()
            await progress.advance()       # → step 1
            await progress.update(0.5)     # 50 % through step 1
            await do_analysis()
            await progress.advance()       # → step 2
            await do_format()
            # auto-completes on exit
    """

    MIN_EDIT_INTERVAL: float = 1.5
    PROGRESS_BAR_LENGTH: int = 10
    FILL_CHAR: str = "▓"
    EMPTY_CHAR: str = "░"

    def __init__(
        self,
        message: Message,
        steps: list[TaskStep],
        language: str = "zh",
        title_zh: str = "任务执行中",
        title_en: str = "Processing",
    ) -> None:
        self._message = message
        self._steps = list(steps)
        self._language = language
        self._title_zh = title_zh
        self._title_en = title_en

        # mutable state
        self._current_step: int = 0
        self._step_progress: float = 0.0
        self._status: str = "running"  # running | completed | failed
        self._error_message: Optional[str] = None
        self._last_edit_time: float = 0.0
        self._auto_pulse_task: Optional[asyncio.Task] = None

    # ── context manager ──────────────────────────────────────

    async def __aenter__(self) -> "TaskProgressManager":
        await self._edit_message(force=True)
        self._auto_pulse_task = asyncio.create_task(self._auto_pulse())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._auto_pulse_task:
            self._auto_pulse_task.cancel()
            try:
                await self._auto_pulse_task
            except asyncio.CancelledError:
                pass

        if exc_type is not None:
            self._status = "failed"
            self._error_message = str(exc_val)
            await self._edit_message(force=True)
            return False

        self._status = "completed"
        self._current_step = len(self._steps) - 1
        self._step_progress = 1.0
        await self._edit_message(force=True)
        return False

    # ── public API ───────────────────────────────────────────

    async def advance(self) -> None:
        """Move to the next step."""
        if self._current_step < len(self._steps) - 1:
            self._current_step += 1
            self._step_progress = 0.0
            await self._edit_message()

    async def update(self, progress: float) -> None:
        """Update sub-progress within the current step (0.0 – 1.0)."""
        self._step_progress = max(0.0, min(1.0, progress))
        await self._edit_message()

    async def set_substatus(self, text_zh: str, text_en: str) -> None:
        """Replace the current step's description text."""
        step = self._steps[self._current_step]
        step.name_zh = text_zh
        step.name_en = text_en
        await self._edit_message()

    # ── internal helpers ─────────────────────────────────────

    def _compute_overall_progress(self) -> float:
        total_weight = sum(s.weight for s in self._steps)
        if total_weight == 0:
            return 0.0
        completed_weight = sum(s.weight for s in self._steps[: self._current_step])
        current_weight = self._steps[self._current_step].weight * self._step_progress
        return (completed_weight + current_weight) / total_weight

    def _render_progress_bar(self, progress: float) -> str:
        filled = int(progress * self.PROGRESS_BAR_LENGTH)
        empty = self.PROGRESS_BAR_LENGTH - filled
        pct = int(progress * 100)
        return f"{self.FILL_CHAR * filled}{self.EMPTY_CHAR * empty} {pct}%"

    def _render_message(self) -> str:
        is_en = self._language == "en"
        title = self._title_en if is_en else self._title_zh
        step = self._steps[self._current_step]
        step_name = step.name_en if is_en else step.name_zh
        step_label = (
            f"Step {self._current_step + 1}/{len(self._steps)}"
            if is_en
            else f"步骤 {self._current_step + 1}/{len(self._steps)}"
        )

        if self._status == "failed":
            error_label = "Error" if is_en else "错误"
            bar = self._render_progress_bar(self._compute_overall_progress())
            return (
                f"*{title}*\n\n"
                f"`{bar}`\n\n"
                f"❌ {step_label}: {step_name}\n\n"
                f"⚠️ {error_label}: {self._error_message}"
            )

        if self._status == "completed":
            done = "All tasks completed ✅" if is_en else "✅ 全部任务完成"
            bar = self._render_progress_bar(1.0)
            return f"*{title}*\n\n`{bar}`\n\n{done}"

        # running
        bar = self._render_progress_bar(self._compute_overall_progress())
        return (
            f"*{title}*\n\n"
            f"`{bar}`\n\n"
            f"⏳ {step_label}: {step_name}..."
        )

    async def _edit_message(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_edit_time) < self.MIN_EDIT_INTERVAL:
            return

        try:
            text = self._render_message()
            await self._message.edit_text(text, parse_mode="Markdown")
            self._last_edit_time = time.monotonic()
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                logger.warning("Failed to edit progress message: %s", e)

    async def _auto_pulse(self) -> None:
        """Gently nudge progress so the user knows the system is alive."""
        while True:
            await asyncio.sleep(3.0)
            if self._status != "running":
                break
            if self._step_progress < 0.9:
                self._step_progress = min(self._step_progress + 0.05, 0.9)
                await self._edit_message()


# ── convenience step factories ───────────────────────────────


def ai_analysis_steps() -> list[TaskStep]:
    """Pre-built steps for the /ask command."""
    return [
        TaskStep("正在加载对话历史", "Loading chat history", weight=1),
        TaskStep("正在查询鲸鱼数据", "Fetching whale data", weight=2),
        TaskStep("AI 正在深度分析", "AI analyzing", weight=5),
        TaskStep("正在整理结果", "Formatting results", weight=1),
    ]


def export_steps() -> list[TaskStep]:
    """Pre-built steps for the /export command."""
    return [
        TaskStep("正在查询订单数据", "Querying order data", weight=3),
        TaskStep("正在生成 CSV 文件", "Generating CSV", weight=1),
        TaskStep("正在生成 JSON 文件", "Generating JSON", weight=1),
        TaskStep("正在发送文件", "Sending files", weight=1),
    ]


def query_steps() -> list[TaskStep]:
    """Pre-built steps for natural-language queries."""
    return [
        TaskStep("正在理解您的问题", "Understanding your query", weight=1),
        TaskStep("正在查询数据", "Querying data", weight=2),
        TaskStep("正在生成回答", "Generating answer", weight=3),
    ]


def payment_job_steps() -> list[TaskStep]:
    """Pre-built steps for payment job execution."""
    return [
        TaskStep("正在处理支付", "Processing payment", weight=1),
        TaskStep("正在执行任务", "Executing task", weight=3),
        TaskStep("正在确认结果", "Confirming result", weight=1),
    ]
