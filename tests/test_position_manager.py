"""Tests for PositionManager — rules-based position exit automation.

NO MOCKING — uses real Portfolio, OrderManager, ExecutionEngine (dry_run),
and EventBus objects throughout.  _check_all_positions() is called directly
instead of starting the background loop.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from polystation.automation.position_manager import ExitConfig, PositionManager
from polystation.core.engine import TradingEngine
from polystation.core.events import EventBus
from polystation.core.orders import OrderManager, OrderStatus
from polystation.core.portfolio import Portfolio
from polystation.trading.execution import ExecutionEngine


# ---------------------------------------------------------------------------
# Shared token/market constants
# ---------------------------------------------------------------------------

TOKEN_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
TOKEN_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
MARKET_1 = "market-condition-id-001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(config: ExitConfig | None = None) -> tuple[TradingEngine, PositionManager]:
    """Return a fully-wired TradingEngine + PositionManager in dry_run mode.

    No exchange adapter — execution runs in dry_run only.  No market_data
    client so the manager never calls get_midpoint(); prices are set directly
    on Position objects in tests.
    """
    engine = TradingEngine()
    engine.portfolio = Portfolio()
    engine.orders = OrderManager()
    engine.execution = ExecutionEngine(
        exchange=None,
        order_manager=engine.orders,
        portfolio=engine.portfolio,
    )
    engine.execution.set_dry_run(True)
    engine.market_data = None  # no live market data in unit tests

    pm = PositionManager(engine, config=config, check_interval=10.0)
    return engine, pm


def _buy_position(
    engine: TradingEngine,
    token_id: str = TOKEN_A,
    price: float = 0.5,
    size: float = 100.0,
    market_id: str = MARKET_1,
) -> None:
    """Record a BUY fill directly on the portfolio to open a position."""
    engine.portfolio.record_fill(token_id, "BUY", price, size, market_id=market_id)


# ---------------------------------------------------------------------------
# ExitConfig defaults
# ---------------------------------------------------------------------------


class TestExitConfigDefaults:
    """Verify dataclass defaults match the spec."""

    def test_all_rules_disabled_by_default(self) -> None:
        cfg = ExitConfig()
        assert cfg.trailing_stop_pct is None
        assert cfg.profit_target_pct is None
        assert cfg.stop_loss_pct is None
        assert cfg.max_hold_hours is None

    def test_expiry_exit_hours_default_is_two(self) -> None:
        cfg = ExitConfig()
        assert cfg.expiry_exit_hours == 2.0

    def test_enabled_default_is_true(self) -> None:
        cfg = ExitConfig()
        assert cfg.enabled is True

    def test_custom_values_stored(self) -> None:
        cfg = ExitConfig(
            trailing_stop_pct=5.0,
            profit_target_pct=20.0,
            stop_loss_pct=10.0,
            max_hold_hours=24.0,
            enabled=False,
        )
        assert cfg.trailing_stop_pct == 5.0
        assert cfg.profit_target_pct == 20.0
        assert cfg.stop_loss_pct == 10.0
        assert cfg.max_hold_hours == 24.0
        assert cfg.enabled is False


# ---------------------------------------------------------------------------
# PositionManager construction
# ---------------------------------------------------------------------------


class TestPositionManagerConstruction:
    """Constructor stores config and initialises internal state correctly."""

    def test_default_config_is_exit_config(self) -> None:
        _, pm = _make_engine()
        assert isinstance(pm.config, ExitConfig)

    def test_custom_config_stored(self) -> None:
        cfg = ExitConfig(trailing_stop_pct=7.5)
        _, pm = _make_engine(config=cfg)
        assert pm.config.trailing_stop_pct == pytest.approx(7.5)

    def test_check_interval_stored(self) -> None:
        _, pm = _make_engine()
        assert pm.check_interval == pytest.approx(10.0)

    def test_initial_state_not_running(self) -> None:
        _, pm = _make_engine()
        assert pm._running is False

    def test_initial_peak_prices_empty(self) -> None:
        _, pm = _make_engine()
        assert pm._peak_prices == {}

    def test_initial_exit_history_empty(self) -> None:
        _, pm = _make_engine()
        assert pm._exit_history == []

    def test_initial_per_position_config_empty(self) -> None:
        _, pm = _make_engine()
        assert pm._per_position_config == {}


# ---------------------------------------------------------------------------
# Trailing stop
# ---------------------------------------------------------------------------


class TestTrailingStop:
    """Trailing stop triggers when price drops >= threshold from its peak."""

    @pytest.mark.asyncio
    async def test_trailing_stop_triggers_on_sufficient_drop(self) -> None:
        """Peak 0.80, current 0.74 → drop 7.5% >= 5% threshold → exit."""
        cfg = ExitConfig(trailing_stop_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.80        # sets initial peak
        pm._peak_prices[TOKEN_A] = 0.80
        pos.current_price = 0.74        # 7.5% drop from 0.80

        await pm._check_all_positions()

        assert len(pm._exit_history) == 1
        assert "trailing_stop" in pm._exit_history[0]["reason"]

    @pytest.mark.asyncio
    async def test_trailing_stop_does_not_trigger_below_threshold(self) -> None:
        """Peak 0.80, current 0.78 → drop 2.5% < 5% threshold → no exit."""
        cfg = ExitConfig(trailing_stop_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pm._peak_prices[TOKEN_A] = 0.80
        pos.current_price = 0.78        # 2.5% drop → below threshold

        await pm._check_all_positions()

        assert len(pm._exit_history) == 0

    @pytest.mark.asyncio
    async def test_trailing_stop_triggers_at_exact_threshold(self) -> None:
        """Drop equals the threshold — should trigger.

        Uses peak=0.20, current=0.18 to avoid float rounding below the
        boundary (0.20->0.18 gives a drop of 10.000...0089 % in IEEE-754).
        """
        cfg = ExitConfig(trailing_stop_pct=10.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pm._peak_prices[TOKEN_A] = 0.20
        pos.current_price = 0.18        # ~10% drop (0.20 -> 0.18)

        await pm._check_all_positions()

        assert len(pm._exit_history) == 1

    @pytest.mark.asyncio
    async def test_trailing_stop_updates_peak_on_new_high(self) -> None:
        """Price rises to a new high — peak should be updated, no exit."""
        cfg = ExitConfig(trailing_stop_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pm._peak_prices[TOKEN_A] = 0.60
        pos.current_price = 0.70        # new high

        await pm._check_all_positions()

        assert pm._peak_prices.get(TOKEN_A) == pytest.approx(0.70)
        assert len(pm._exit_history) == 0


# ---------------------------------------------------------------------------
# Profit target
# ---------------------------------------------------------------------------


class TestProfitTarget:
    """Profit target exits when unrealized P&L reaches +N% of cost basis."""

    @pytest.mark.asyncio
    async def test_profit_target_triggers_at_plus_20_pct(self) -> None:
        """Entry 0.5, current 0.62 → pnl 12/50 = 24% >= 20% → exit."""
        cfg = ExitConfig(profit_target_pct=20.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)   # cost_basis = 50

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.62        # pnl = (0.62 - 0.5) * 100 = 12 → 24%

        await pm._check_all_positions()

        assert len(pm._exit_history) == 1
        assert "profit_target" in pm._exit_history[0]["reason"]

    @pytest.mark.asyncio
    async def test_profit_target_does_not_trigger_below_threshold(self) -> None:
        """Entry 0.5, current 0.58 → pnl 8/50 = 16% < 20% → no exit."""
        cfg = ExitConfig(profit_target_pct=20.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.58        # 16% gain

        await pm._check_all_positions()

        assert len(pm._exit_history) == 0

    @pytest.mark.asyncio
    async def test_profit_target_triggers_exactly_at_threshold(self) -> None:
        """P&L exactly equals the target percentage."""
        cfg = ExitConfig(profit_target_pct=20.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)   # cost_basis = 50

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.60        # pnl = 10 / 50 = exactly 20%

        await pm._check_all_positions()

        assert len(pm._exit_history) == 1

    @pytest.mark.asyncio
    async def test_profit_target_reason_contains_pct(self) -> None:
        """Exit reason string should mention the P&L percentage."""
        cfg = ExitConfig(profit_target_pct=15.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.4, size=100.0)   # cost_basis = 40

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.50        # pnl = 10 / 40 = 25%

        await pm._check_all_positions()

        assert len(pm._exit_history) == 1
        reason = pm._exit_history[0]["reason"]
        assert "+" in reason


# ---------------------------------------------------------------------------
# Stop loss
# ---------------------------------------------------------------------------


class TestStopLoss:
    """Stop loss exits when unrealized P&L falls to -N% of cost basis."""

    @pytest.mark.asyncio
    async def test_stop_loss_triggers_at_minus_10_pct(self) -> None:
        """Entry 0.5, current 0.44 → pnl -6/50 = -12% <= -10% → exit."""
        cfg = ExitConfig(stop_loss_pct=10.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)   # cost_basis = 50

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.44        # pnl = (0.44 - 0.5) * 100 = -6 → -12%

        await pm._check_all_positions()

        assert len(pm._exit_history) == 1
        assert "stop_loss" in pm._exit_history[0]["reason"]

    @pytest.mark.asyncio
    async def test_stop_loss_does_not_trigger_above_threshold(self) -> None:
        """Entry 0.5, current 0.47 → pnl -3/50 = -6% > -10% → no exit."""
        cfg = ExitConfig(stop_loss_pct=10.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.47        # -6% loss

        await pm._check_all_positions()

        assert len(pm._exit_history) == 0

    @pytest.mark.asyncio
    async def test_stop_loss_triggers_exactly_at_threshold(self) -> None:
        """P&L exactly equals the stop-loss threshold."""
        cfg = ExitConfig(stop_loss_pct=10.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)   # cost_basis = 50

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.45        # pnl = -5 / 50 = exactly -10%

        await pm._check_all_positions()

        assert len(pm._exit_history) == 1

    @pytest.mark.asyncio
    async def test_stop_loss_reason_contains_pct(self) -> None:
        """Exit reason should include the P&L percentage."""
        cfg = ExitConfig(stop_loss_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.4, size=100.0)   # cost_basis = 40

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.30        # pnl = -10 / 40 = -25%

        await pm._check_all_positions()

        reason = pm._exit_history[0]["reason"]
        assert "stop_loss" in reason
        assert "-" in reason


# ---------------------------------------------------------------------------
# Time exit (max_hold_hours)
# ---------------------------------------------------------------------------


class TestTimeExit:
    """Time exit triggers after a position has been held for max_hold_hours."""

    @pytest.mark.asyncio
    async def test_time_exit_triggers_after_max_hold(self) -> None:
        """Backdate entry time by 3h when limit is 2h → should exit."""
        cfg = ExitConfig(max_hold_hours=2.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.5

        # Simulate having held the position for 3 hours
        pm._entry_times[TOKEN_A] = datetime.now(timezone.utc) - timedelta(hours=3)

        await pm._check_all_positions()

        assert len(pm._exit_history) == 1
        assert "time_exit" in pm._exit_history[0]["reason"]

    @pytest.mark.asyncio
    async def test_time_exit_does_not_trigger_before_limit(self) -> None:
        """Held for 1h with a 2h limit → no exit."""
        cfg = ExitConfig(max_hold_hours=2.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.5

        pm._entry_times[TOKEN_A] = datetime.now(timezone.utc) - timedelta(hours=1)

        await pm._check_all_positions()

        assert len(pm._exit_history) == 0

    @pytest.mark.asyncio
    async def test_time_exit_reason_contains_hours(self) -> None:
        """Reason string should include both elapsed and max hours."""
        cfg = ExitConfig(max_hold_hours=1.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.5

        pm._entry_times[TOKEN_A] = datetime.now(timezone.utc) - timedelta(hours=2)

        await pm._check_all_positions()

        reason = pm._exit_history[0]["reason"]
        assert "time_exit" in reason
        assert "1.0h" in reason     # max_hold_hours appears in reason string

    @pytest.mark.asyncio
    async def test_entry_time_recorded_on_first_check(self) -> None:
        """First call to _check_all_positions records the entry time."""
        cfg = ExitConfig(max_hold_hours=999.0)   # won't trigger
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.5

        assert TOKEN_A not in pm._entry_times

        await pm._check_all_positions()

        assert TOKEN_A in pm._entry_times


# ---------------------------------------------------------------------------
# No exit when rules disabled
# ---------------------------------------------------------------------------


class TestNoExitWhenDisabled:
    """When enabled=False no exit rules should fire."""

    @pytest.mark.asyncio
    async def test_disabled_config_skips_all_rules(self) -> None:
        """Even with very aggressive thresholds, a disabled config fires nothing."""
        cfg = ExitConfig(
            trailing_stop_pct=0.1,
            profit_target_pct=0.1,
            stop_loss_pct=0.1,
            max_hold_hours=0.0001,
            enabled=False,
        )
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.01    # enormous loss — still shouldn't exit

        pm._entry_times[TOKEN_A] = datetime.now(timezone.utc) - timedelta(hours=999)
        pm._peak_prices[TOKEN_A] = 0.99

        await pm._check_all_positions()

        assert len(pm._exit_history) == 0

    @pytest.mark.asyncio
    async def test_no_rules_configured_produces_no_exit(self) -> None:
        """Default ExitConfig (all None) should never trigger an exit."""
        cfg = ExitConfig()  # all rules are None
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.01    # huge loss

        pm._entry_times[TOKEN_A] = datetime.now(timezone.utc) - timedelta(hours=999)
        pm._peak_prices[TOKEN_A] = 0.99

        await pm._check_all_positions()

        assert len(pm._exit_history) == 0

    @pytest.mark.asyncio
    async def test_zero_size_position_skipped(self) -> None:
        """Positions with size <= 0 are never evaluated."""
        cfg = ExitConfig(stop_loss_pct=1.0)
        engine, pm = _make_engine(config=cfg)

        # Add then fully close a position
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)
        engine.portfolio.record_fill(TOKEN_A, "SELL", 0.5, 100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        assert pos.size == pytest.approx(0.0)
        pos.current_price = 0.01

        await pm._check_all_positions()

        assert len(pm._exit_history) == 0


# ---------------------------------------------------------------------------
# Per-position config overrides global
# ---------------------------------------------------------------------------


class TestPerPositionConfig:
    """Per-position ExitConfig overrides the global config."""

    @pytest.mark.asyncio
    async def test_per_position_config_overrides_global(self) -> None:
        """Global: stop_loss 5%.  Per-position for TOKEN_A: stop_loss 50%.
        A -10% loss should trigger the global rule for TOKEN_B but not TOKEN_A.
        """
        global_cfg = ExitConfig(stop_loss_pct=5.0)
        engine, pm = _make_engine(config=global_cfg)

        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)
        _buy_position(engine, TOKEN_B, price=0.5, size=100.0)

        # Override TOKEN_A with a very lenient stop
        pm.set_config(TOKEN_A, ExitConfig(stop_loss_pct=50.0))

        pos_a = engine.portfolio.get_position(TOKEN_A)
        pos_b = engine.portfolio.get_position(TOKEN_B)
        assert pos_a is not None and pos_b is not None

        # -10% loss for both
        pos_a.current_price = 0.45
        pos_b.current_price = 0.45

        await pm._check_all_positions()

        # Only TOKEN_B should have exited (global 5% rule)
        exited_tokens = [r["token_id"] for r in pm._exit_history]
        assert TOKEN_B in exited_tokens
        assert TOKEN_A not in exited_tokens

    @pytest.mark.asyncio
    async def test_per_position_disabled_while_global_enabled(self) -> None:
        """Per-position config can disable exits for one token."""
        global_cfg = ExitConfig(stop_loss_pct=5.0)
        engine, pm = _make_engine(config=global_cfg)

        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pm.set_config(TOKEN_A, ExitConfig(enabled=False))

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.01    # enormous loss

        await pm._check_all_positions()

        assert len(pm._exit_history) == 0

    @pytest.mark.asyncio
    async def test_set_config_global_replaces_config(self) -> None:
        """Calling set_config(None, ...) replaces the global config."""
        _, pm = _make_engine()
        pm.set_config(None, ExitConfig(profit_target_pct=99.0))
        assert pm.config.profit_target_pct == pytest.approx(99.0)

    def test_set_config_per_position_stored(self) -> None:
        """Per-position config is stored and retrievable."""
        _, pm = _make_engine()
        cfg = ExitConfig(trailing_stop_pct=3.0)
        pm.set_config(TOKEN_A, cfg)
        assert pm._per_position_config[TOKEN_A].trailing_stop_pct == pytest.approx(3.0)

    def test_multiple_per_position_overrides_tracked(self) -> None:
        """Each token stores its own independent override config."""
        _, pm = _make_engine()
        pm.set_config(TOKEN_A, ExitConfig(trailing_stop_pct=3.0))
        pm.set_config(TOKEN_B, ExitConfig(stop_loss_pct=8.0))
        assert len(pm._per_position_config) == 2
        assert pm._per_position_config[TOKEN_A].trailing_stop_pct == pytest.approx(3.0)
        assert pm._per_position_config[TOKEN_B].stop_loss_pct == pytest.approx(8.0)


# ---------------------------------------------------------------------------
# Exit creates a SELL order in OrderManager
# ---------------------------------------------------------------------------


class TestExitCreatesOrder:
    """Executing an exit places a SELL order via OrderManager + ExecutionEngine."""

    @pytest.mark.asyncio
    async def test_exit_creates_sell_order(self) -> None:
        """After an exit triggers, a SELL order should exist in OrderManager."""
        cfg = ExitConfig(stop_loss_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.44    # -12% loss

        await pm._check_all_positions()

        sell_orders = [
            o for o in engine.orders.orders.values()
            if o.side == "SELL" and o.token_id == TOKEN_A
        ]
        assert len(sell_orders) == 1

    @pytest.mark.asyncio
    async def test_exit_order_kernel_name_is_position_manager(self) -> None:
        """SELL order created by PositionManager carries the correct kernel name."""
        cfg = ExitConfig(stop_loss_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.44

        await pm._check_all_positions()

        sell_orders = [
            o for o in engine.orders.orders.values()
            if o.side == "SELL" and o.token_id == TOKEN_A
        ]
        assert sell_orders[0].kernel_name == "position_manager"

    @pytest.mark.asyncio
    async def test_exit_order_size_matches_position_size(self) -> None:
        """The SELL order size equals the full position size."""
        cfg = ExitConfig(stop_loss_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=250.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.40    # large loss

        await pm._check_all_positions()

        sell_orders = [
            o for o in engine.orders.orders.values()
            if o.side == "SELL" and o.token_id == TOKEN_A
        ]
        assert sell_orders[0].size == pytest.approx(250.0)

    @pytest.mark.asyncio
    async def test_exit_order_filled_in_dry_run(self) -> None:
        """ExecutionEngine (dry_run) should fill the SELL order immediately."""
        cfg = ExitConfig(profit_target_pct=10.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.60    # +20%

        await pm._check_all_positions()

        sell_orders = [
            o for o in engine.orders.orders.values()
            if o.side == "SELL" and o.token_id == TOKEN_A
        ]
        assert len(sell_orders) == 1
        assert sell_orders[0].status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_exit_order_price_is_current_price(self) -> None:
        """Exit order price should match the position's current_price."""
        cfg = ExitConfig(profit_target_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.65

        await pm._check_all_positions()

        sell_orders = [
            o for o in engine.orders.orders.values()
            if o.side == "SELL" and o.token_id == TOKEN_A
        ]
        assert sell_orders[0].price == pytest.approx(0.65)


# ---------------------------------------------------------------------------
# Exit history records the exit
# ---------------------------------------------------------------------------


class TestExitHistory:
    """_exit_history accumulates records for each triggered exit."""

    @pytest.mark.asyncio
    async def test_exit_history_records_one_entry_per_exit(self) -> None:
        cfg = ExitConfig(stop_loss_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.40

        await pm._check_all_positions()

        assert len(pm._exit_history) == 1

    @pytest.mark.asyncio
    async def test_exit_history_contains_token_id(self) -> None:
        cfg = ExitConfig(stop_loss_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.40

        await pm._check_all_positions()

        assert pm._exit_history[0]["token_id"] == TOKEN_A

    @pytest.mark.asyncio
    async def test_exit_history_contains_reason(self) -> None:
        cfg = ExitConfig(profit_target_pct=10.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.65

        await pm._check_all_positions()

        assert "reason" in pm._exit_history[0]
        assert "profit_target" in pm._exit_history[0]["reason"]

    @pytest.mark.asyncio
    async def test_exit_history_contains_size_and_price(self) -> None:
        cfg = ExitConfig(stop_loss_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=150.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.40

        await pm._check_all_positions()

        record = pm._exit_history[0]
        assert record["size"] == pytest.approx(150.0)
        assert record["price"] == pytest.approx(0.40)

    @pytest.mark.asyncio
    async def test_exit_history_result_is_success_on_dry_run(self) -> None:
        cfg = ExitConfig(stop_loss_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.40

        await pm._check_all_positions()

        assert pm._exit_history[0]["result"] == "success"

    @pytest.mark.asyncio
    async def test_exit_history_contains_timestamp(self) -> None:
        cfg = ExitConfig(stop_loss_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.40

        await pm._check_all_positions()

        assert "timestamp" in pm._exit_history[0]
        # Timestamp should be a valid ISO-8601 string
        ts = pm._exit_history[0]["timestamp"]
        datetime.fromisoformat(ts)  # raises on invalid format

    @pytest.mark.asyncio
    async def test_multiple_exits_accumulate_in_history(self) -> None:
        """Two separate positions each triggering exits → two history entries."""
        cfg = ExitConfig(stop_loss_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)
        _buy_position(engine, TOKEN_B, price=0.5, size=100.0)

        pos_a = engine.portfolio.get_position(TOKEN_A)
        pos_b = engine.portfolio.get_position(TOKEN_B)
        assert pos_a is not None and pos_b is not None

        pos_a.current_price = 0.40
        pos_b.current_price = 0.40

        await pm._check_all_positions()

        assert len(pm._exit_history) == 2


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    """get_status() returns the expected structure."""

    def test_status_keys_present(self) -> None:
        _, pm = _make_engine()
        status = pm.get_status()
        assert "running" in status
        assert "check_interval" in status
        assert "config" in status
        assert "tracked_positions" in status
        assert "exit_history" in status
        assert "per_position_overrides" in status

    def test_status_running_false_before_start(self) -> None:
        _, pm = _make_engine()
        assert pm.get_status()["running"] is False

    def test_status_check_interval_matches(self) -> None:
        engine = TradingEngine()
        pm = PositionManager(engine, check_interval=30.0)
        assert pm.get_status()["check_interval"] == pytest.approx(30.0)

    def test_status_config_subkeys(self) -> None:
        cfg = ExitConfig(trailing_stop_pct=5.0, profit_target_pct=20.0)
        _, pm = _make_engine(config=cfg)
        cfg_status = pm.get_status()["config"]
        assert cfg_status["trailing_stop_pct"] == pytest.approx(5.0)
        assert cfg_status["profit_target_pct"] == pytest.approx(20.0)
        assert cfg_status["stop_loss_pct"] is None
        assert cfg_status["max_hold_hours"] is None
        assert cfg_status["expiry_exit_hours"] == pytest.approx(2.0)
        assert cfg_status["enabled"] is True

    def test_status_tracked_positions_zero_initially(self) -> None:
        _, pm = _make_engine()
        assert pm.get_status()["tracked_positions"] == 0

    @pytest.mark.asyncio
    async def test_status_tracked_positions_increments_after_check(self) -> None:
        """After the first check, peak_prices should be populated for open positions."""
        cfg = ExitConfig()   # no rules — won't exit
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.55

        await pm._check_all_positions()

        assert pm.get_status()["tracked_positions"] == 1

    def test_status_exit_history_limited_to_20(self) -> None:
        """get_status returns at most 20 exit history entries."""
        _, pm = _make_engine()
        # Inject 30 fake history entries
        for i in range(30):
            pm._exit_history.append({"timestamp": f"2026-01-01T{i:02d}:00:00+00:00"})
        assert len(pm.get_status()["exit_history"]) == 20

    def test_status_per_position_overrides_count(self) -> None:
        _, pm = _make_engine()
        pm.set_config(TOKEN_A, ExitConfig(stop_loss_pct=5.0))
        pm.set_config(TOKEN_B, ExitConfig(profit_target_pct=20.0))
        assert pm.get_status()["per_position_overrides"] == 2


# ---------------------------------------------------------------------------
# Tracking cleanup after exit
# ---------------------------------------------------------------------------


class TestTrackingCleanupAfterExit:
    """peak_prices and entry_times are cleaned up once an exit fires."""

    @pytest.mark.asyncio
    async def test_peak_price_removed_after_exit(self) -> None:
        cfg = ExitConfig(stop_loss_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pm._peak_prices[TOKEN_A] = 0.50
        pos.current_price = 0.40

        await pm._check_all_positions()

        assert TOKEN_A not in pm._peak_prices

    @pytest.mark.asyncio
    async def test_entry_time_removed_after_exit(self) -> None:
        cfg = ExitConfig(stop_loss_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pm._entry_times[TOKEN_A] = datetime.now(timezone.utc) - timedelta(hours=1)
        pos.current_price = 0.40

        await pm._check_all_positions()

        assert TOKEN_A not in pm._entry_times


# ---------------------------------------------------------------------------
# EventBus integration
# ---------------------------------------------------------------------------


class TestEventBusIntegration:
    """position.exit_triggered event is published after an exit."""

    @pytest.mark.asyncio
    async def test_exit_publishes_event(self) -> None:
        """Subscribe to the event and verify it fires after a triggered exit."""
        cfg = ExitConfig(stop_loss_pct=5.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=100.0)

        received_events: list[dict[str, Any]] = []

        async def on_exit(**kwargs: Any) -> None:
            received_events.append(kwargs)

        engine.events.subscribe("position.exit_triggered", on_exit)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.40

        await pm._check_all_positions()

        assert len(received_events) == 1
        assert received_events[0]["token_id"] == TOKEN_A
        assert "stop_loss" in received_events[0]["reason"]

    @pytest.mark.asyncio
    async def test_exit_event_contains_size(self) -> None:
        cfg = ExitConfig(profit_target_pct=10.0)
        engine, pm = _make_engine(config=cfg)
        _buy_position(engine, TOKEN_A, price=0.5, size=75.0)

        received_events: list[dict[str, Any]] = []

        async def on_exit(**kwargs: Any) -> None:
            received_events.append(kwargs)

        engine.events.subscribe("position.exit_triggered", on_exit)

        pos = engine.portfolio.get_position(TOKEN_A)
        assert pos is not None
        pos.current_price = 0.60

        await pm._check_all_positions()

        assert received_events[0]["size"] == pytest.approx(75.0)
