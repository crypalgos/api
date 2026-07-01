import pytest
import time
from decimal import Decimal
from app.modules.data_service.services.orderbook_projection import (
    OrderBookProjection,
    OrderBookStatus,
    OrderBookLevel,
    InstrumentId,
    MarketType
)

@pytest.mark.anyio
async def test_orderbook_projection_updates():
    inst = InstrumentId(exchange="delta", market_type=MarketType.PERPETUAL, symbol="BTCUSD")
    proj = OrderBookProjection(inst)
    
    # 1. Apply initial updates
    bids = [[Decimal("90000.0"), Decimal("1.5")], [Decimal("89900.0"), Decimal("2.0")]]
    asks = [[Decimal("90100.0"), Decimal("0.5")], [Decimal("90200.0"), Decimal("1.0")]]
    
    changed = proj.apply_update(bids, asks, sequence=101, timestamp=int(time.time() * 1000))
    assert changed is True
    
    snap = proj.get_snapshot(depth=10)
    assert len(snap.bids) == 2
    assert snap.bids[0].price == Decimal("90000.0")
    assert snap.bids[0].size == Decimal("1.5")
    assert snap.status == OrderBookStatus.ACTIVE

    # 2. Apply updates that do NOT change top bid/ask levels
    # (Inserting a lower bid level doesn't change the top of book)
    bids_no_change = [[Decimal("89500.0"), Decimal("5.0")]]
    changed_no_top = proj.apply_update(bids_no_change, [], sequence=102, timestamp=int(time.time() * 1000))
    assert changed_no_top is False

    # 3. Apply updates deleting a level (size=0)
    delete_bid = [[Decimal("90000.0"), Decimal("0.0")]]
    changed_del = proj.apply_update(delete_bid, [], sequence=103, timestamp=int(time.time() * 1000))
    assert changed_del is True
    
    snap_del = proj.get_snapshot(depth=10)
    assert snap_del.bids[0].price == Decimal("89900.0") # Level 90000.0 deleted, top of book is 89900.0

@pytest.mark.anyio
async def test_orderbook_sequence_gap():
    inst = InstrumentId(exchange="delta", market_type=MarketType.PERPETUAL, symbol="BTCUSD")
    proj = OrderBookProjection(inst)
    
    # Initial sequence
    proj.apply_update([], [], sequence=100, timestamp=int(time.time() * 1000))
    assert proj.status == OrderBookStatus.ACTIVE
    
    # Gap sequence (expected 101, got 103)
    proj.apply_update([], [], sequence=103, timestamp=int(time.time() * 1000))
    assert proj.status == OrderBookStatus.OUT_OF_SYNC

@pytest.mark.anyio
async def test_orderbook_staleness():
    inst = InstrumentId(exchange="delta", market_type=MarketType.PERPETUAL, symbol="BTCUSD")
    proj = OrderBookProjection(inst)
    
    # Set received_at to 15 seconds ago
    proj.received_at = int(time.time() * 1000) - 15000
    
    snap = proj.get_snapshot(depth=10)
    assert snap.status == OrderBookStatus.STALE

@pytest.mark.anyio
async def test_orderbook_market_type_constraint():
    from app.modules.data_service.services.orderbook_projection import orderbook_registry
    
    # SPOT instrument
    with pytest.raises(NotImplementedError) as exc:
        orderbook_registry.get_projection(exchange="delta", symbol="BTCUSD", market_type=MarketType.SPOT)
    assert "Only perpetual futures are supported in v1.0" in str(exc.value)

    # OPTIONS instrument
    with pytest.raises(NotImplementedError) as exc:
        orderbook_registry.get_projection(exchange="delta", symbol="BTCUSD", market_type=MarketType.OPTIONS)
    assert "Only perpetual futures are supported in v1.0" in str(exc.value)
