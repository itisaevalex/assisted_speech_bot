"""Position exit automation — monitors positions and executes exits based on rules."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExitConfig:
    """Global or per-position exit rules.

    Attributes:
        trailing_stop_pct: Exit if price drops this % from its peak, e.g. 5.0.
        profit_target_pct: Exit when unrealized P&L reaches +N% of cost basis.
        stop_loss_pct: Exit when unrealized P&L falls to -N% of cost basis.
        max_hold_hours: Exit after holding a position for N hours.
        expiry_exit_hours: Exit N hours before market expiry (future use).
        enabled: Master switch; when False all rules are skipped.
    """

    trailing_stop_pct: float | None = None
    profit_target_pct: float | None = None
    stop_loss_pct: float | None = None
    max_hold_hours: float | None = None
    expiry_exit_hours: float | None = 2.0
    enabled: bool = True


class PositionManager:
    """Monitors open positions and auto-exits based on configurable rules.

    Runs as a background async task.  Checks all positions every
    ``check_interval`` seconds and executes sell orders when exit conditions
    are met.

    Args:
        engine: A :class:`~polystation.core.engine.TradingEngine` instance
            (or any object with ``portfolio``, ``orders``, ``execution``,
            ``events``, and ``market_data`` attributes).
        config: Global :class:`ExitConfig` applied to all positions unless
            overridden via :meth:`set_config`.
        check_interval: Seconds between position sweeps.  Defaults to 10.
    """

    def __init__(
        self,
        engine: Any,
        config: ExitConfig | None = None,
        check_interval: float = 10.0,
    ) -> None:
        self.engine = engine
        self.config = config or ExitConfig()
        self.check_interval = check_interval
        self._running = False
        self._task: asyncio.Task[None] | None = None

        # Per-position tracking
        self._peak_prices: dict[str, float] = {}
        self._entry_times: dict[str, datetime] = {}
        self._exit_history: list[dict[str, Any]] = []
        self._per_position_config: dict[str, ExitConfig] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background monitoring loop."""
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("PositionManager started (interval=%.1fs)", self.check_interval)

    async def stop(self) -> None:
        """Stop the background monitoring loop and wait for it to finish."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("PositionManager stopped")

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _monitor_loop(self) -> None:
        """Periodic sweep — runs until :meth:`stop` is called."""
        while self._running:
            try:
                await self._check_all_positions()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("PositionManager check error")
            await asyncio.sleep(self.check_interval)

    async def _check_all_positions(self) -> None:
        """Evaluate every open position against its exit rules."""
        if not self.engine.portfolio:
            return

        for token_id, pos in list(self.engine.portfolio.positions.items()):
            if pos.size <= 0:
                continue

            # Resolve config — per-position override beats global
            cfg = self._per_position_config.get(token_id, self.config)
            if not cfg.enabled:
                continue

            # Refresh price from market data when available
            if self.engine.market_data:
                try:
                    mid = self.engine.market_data.get_midpoint(token_id)
                    if mid is not None:
                        self.engine.portfolio.update_price(token_id, mid)
                except Exception:
                    pass

            # Record when we first observed this position
            if token_id not in self._entry_times:
                self._entry_times[token_id] = datetime.now(timezone.utc)

            # Track all-time high price for trailing-stop calculation
            current = pos.current_price
            if current is not None:
                peak = self._peak_prices.get(token_id, 0.0)
                if current > peak:
                    self._peak_prices[token_id] = current

            # Evaluate exit rules and act if triggered
            reason = self._evaluate_exit(token_id, pos, cfg)
            if reason:
                await self._execute_exit(token_id, pos, reason)

    # ------------------------------------------------------------------
    # Exit rule evaluation
    # ------------------------------------------------------------------

    def _evaluate_exit(self, token_id: str, pos: Any, cfg: ExitConfig) -> str | None:
        """Check all configured exit rules in order of priority.

        Args:
            token_id: Position token identifier.
            pos: :class:`~polystation.core.portfolio.Position` object.
            cfg: :class:`ExitConfig` to evaluate against.

        Returns:
            A human-readable exit reason string, or ``None`` if no rule fired.
        """
        # 1. Trailing stop -----------------------------------------------
        if cfg.trailing_stop_pct is not None and pos.current_price is not None:
            peak = self._peak_prices.get(token_id, pos.avg_entry_price)
            if peak > 0:
                drop_pct = round(((peak - pos.current_price) / peak) * 100.0, 6)
                if drop_pct >= cfg.trailing_stop_pct:
                    return (
                        f"trailing_stop ({drop_pct:.1f}% from peak {peak:.4f})"
                    )

        # 2. Profit target -----------------------------------------------
        if cfg.profit_target_pct is not None and pos.unrealized_pnl is not None and pos.cost_basis > 0:
            pnl_pct = round((pos.unrealized_pnl / pos.cost_basis) * 100.0, 6)
            if pnl_pct >= cfg.profit_target_pct:
                return f"profit_target (+{pnl_pct:.1f}%)"

        # 3. Stop loss ---------------------------------------------------
        if cfg.stop_loss_pct is not None and pos.unrealized_pnl is not None and pos.cost_basis > 0:
            pnl_pct = round((pos.unrealized_pnl / pos.cost_basis) * 100.0, 6)
            if pnl_pct <= -cfg.stop_loss_pct:
                return f"stop_loss ({pnl_pct:.1f}%)"

        # 4. Maximum hold time -------------------------------------------
        if cfg.max_hold_hours is not None:
            entry_time = self._entry_times.get(token_id)
            if entry_time:
                hours_held = (
                    datetime.now(timezone.utc) - entry_time
                ).total_seconds() / 3600.0
                if hours_held >= cfg.max_hold_hours:
                    return (
                        f"time_exit ({hours_held:.1f}h >= {cfg.max_hold_hours}h)"
                    )

        return None

    # ------------------------------------------------------------------
    # Exit execution
    # ------------------------------------------------------------------

    async def _execute_exit(self, token_id: str, pos: Any, reason: str) -> None:
        """Place a SELL order to close *pos* and record the event.

        Args:
            token_id: Position token identifier.
            pos: :class:`~polystation.core.portfolio.Position` object.
            reason: Human-readable string describing why the exit was triggered.
        """
        logger.info(
            "EXIT TRIGGERED: %s — reason: %s (size=%.0f)",
            token_id[:20],
            reason,
            pos.size,
        )

        try:
            if self.engine.orders and self.engine.execution:
                # Snapshot size and price before submit_order mutates the position
                exit_size = pos.size
                exit_price = pos.current_price or pos.avg_entry_price
                order = self.engine.orders.create_order(
                    token_id=token_id,
                    side="SELL",
                    price=exit_price,
                    size=exit_size,
                    kernel_name="position_manager",
                )
                result = await self.engine.execution.submit_order(order)

                exit_record: dict[str, Any] = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "token_id": token_id,
                    "reason": reason,
                    "size": exit_size,
                    "price": exit_price,
                    "result": "success" if result else "failed",
                }
                self._exit_history.append(exit_record)

                if self.engine.events:
                    await self.engine.events.publish(
                        "position.exit_triggered",
                        token_id=token_id,
                        reason=reason,
                        size=exit_size,
                    )

                # Remove tracking state so we don't fire again on the same position
                self._peak_prices.pop(token_id, None)
                self._entry_times.pop(token_id, None)

        except Exception:
            logger.exception("Failed to execute exit for %s", token_id[:20])

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    def set_config(self, token_id: str | None, config: ExitConfig) -> None:
        """Set exit rules globally or for a single position.

        Args:
            token_id: When ``None`` the global config is replaced; when a
                token ID string is given, that position receives its own
                override config.
            config: :class:`ExitConfig` to apply.
        """
        if token_id is None:
            self.config = config
        else:
            self._per_position_config[token_id] = config

    # ------------------------------------------------------------------
    # Status / inspection
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Return a JSON-safe snapshot of manager state.

        Returns:
            Dict containing running flag, interval, global config values,
            number of tracked positions, recent exit history (last 20), and
            count of per-position overrides.
        """
        return {
            "running": self._running,
            "check_interval": self.check_interval,
            "config": {
                "trailing_stop_pct": self.config.trailing_stop_pct,
                "profit_target_pct": self.config.profit_target_pct,
                "stop_loss_pct": self.config.stop_loss_pct,
                "max_hold_hours": self.config.max_hold_hours,
                "expiry_exit_hours": self.config.expiry_exit_hours,
                "enabled": self.config.enabled,
            },
            "tracked_positions": len(self._peak_prices),
            "exit_history": self._exit_history[-20:],
            "per_position_overrides": len(self._per_position_config),
        }
