import time
import logging
from decimal import Decimal
from enum import Enum
from datetime import date
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

ORDERBOOK_SCHEMA_VERSION = 1


class OrderBookStatus(str, Enum):
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    OUT_OF_SYNC = "OUT_OF_SYNC"
    RECONNECTING = "RECONNECTING"


class MarketType(str, Enum):
    SPOT = "SPOT"
    PERPETUAL = "PERPETUAL"
    FUTURES = "FUTURES"
    OPTIONS = "OPTIONS"


class OptionType(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


@dataclass(frozen=True, slots=True)
class InstrumentId:
    exchange: str
    market_type: MarketType
    symbol: str
    underlying: Optional[str] = None
    expiry: Optional[date] = None
    strike: Optional[Decimal] = None
    option_type: Optional[OptionType] = None

    def to_dict(self) -> dict:
        return {
            "exchange": self.exchange,
            "market_type": self.market_type.value,
            "symbol": self.symbol,
            "underlying": self.underlying,
            "expiry": self.expiry.isoformat() if self.expiry else None,
            "strike": float(self.strike) if self.strike else None,
            "option_type": self.option_type.value if self.option_type else None,
        }


@dataclass(frozen=True, slots=True)
class InstrumentMetadata:
    instrument: InstrumentId
    base_asset: str
    quote_asset: str
    tick_size: Decimal
    lot_size: Decimal
    price_precision: int
    quantity_precision: int
    contract_size: Optional[Decimal] = None
    expiry: Optional[date] = None
    strike: Optional[Decimal] = None
    option_type: Optional[OptionType] = None


@dataclass(frozen=True)
class ExchangeCapabilities:
    supports_spot: bool
    supports_perpetual: bool
    supports_futures: bool
    supports_options: bool
    supports_reduce_only: bool
    supports_post_only: bool
    supports_trigger_orders: bool


@dataclass(frozen=True, slots=True)
class OrderBookLevel:
    price: Decimal
    size: Decimal


@dataclass(frozen=True, slots=True)
class OrderBookSnapshot:
    instrument: InstrumentId
    sequence: int
    exchange_timestamp: int
    received_at: int
    bids: Tuple[OrderBookLevel, ...]
    asks: Tuple[OrderBookLevel, ...]
    status: OrderBookStatus = OrderBookStatus.ACTIVE
    schema_version: int = ORDERBOOK_SCHEMA_VERSION


logger = logging.getLogger(__name__)


class OrderBookProjection:
    def __init__(self, instrument: InstrumentId):
        self.instrument = instrument
        self.bids: Dict[Decimal, Decimal] = {}
        self.asks: Dict[Decimal, Decimal] = {}
        self.last_sequence: int = -1
        self.exchange_timestamp: int = 0
        self.received_at: int = 0
        self.status: OrderBookStatus = OrderBookStatus.ACTIVE

    def apply_update(
        self,
        bids_delta: List[List[Decimal]],
        asks_delta: List[List[Decimal]],
        sequence: int,
        timestamp: int,
    ) -> bool:
        """Applies incremental updates. Returns True if order book top levels pricing/sizing changed."""
        # Check sequencing gaps
        if (
            self.last_sequence != -1
            and sequence != self.last_sequence + 1
            and sequence != self.last_sequence
        ):
            logger.warning(
                f"Sequence gap detected on {self.instrument.symbol}: expected {self.last_sequence + 1}, got {sequence}. Marking OUT_OF_SYNC."
            )
            self.status = OrderBookStatus.OUT_OF_SYNC
            # Return True to publish out-of-sync alert
            return True

        self.last_sequence = sequence
        self.exchange_timestamp = timestamp
        self.received_at = int(time.time() * 1000)
        self.status = OrderBookStatus.ACTIVE

        old_top_bid = self.get_top_level(is_bid=True)
        old_top_ask = self.get_top_level(is_bid=False)

        # Apply bids
        for price, size in bids_delta:
            if size == Decimal("0"):
                self.bids.pop(price, None)
            else:
                self.bids[price] = size

        # Apply asks
        for price, size in asks_delta:
            if size == Decimal("0"):
                self.asks.pop(price, None)
            else:
                self.asks[price] = size

        # Return True only if top-level bid/ask pricing or sizing changed
        new_top_bid = self.get_top_level(is_bid=True)
        new_top_ask = self.get_top_level(is_bid=False)

        return old_top_bid != new_top_bid or old_top_ask != new_top_ask

    def get_top_level(self, is_bid: bool) -> Optional[Tuple[Decimal, Decimal]]:
        tree = self.bids if is_bid else self.asks
        if not tree:
            return None
        # Bids sorted descending, Asks sorted ascending
        sorted_prices = sorted(tree.keys(), reverse=is_bid)
        top_price = sorted_prices[0]
        return (top_price, tree[top_price])

    def check_staleness(self) -> None:
        """Sets status to STALE if no updates received for more than 10 seconds."""
        current_time_ms = int(time.time() * 1000)
        if self.received_at > 0 and (current_time_ms - self.received_at) > 10000:
            if self.status == OrderBookStatus.ACTIVE:
                logger.warning(
                    f"OrderBook projection for {self.instrument.symbol} is stale."
                )
                self.status = OrderBookStatus.STALE

    def get_snapshot(self, depth: int = 20) -> OrderBookSnapshot:
        self.check_staleness()

        # Enforce allowed depths (10, 20, 50)
        if depth not in (10, 20, 50):
            depth = 20

        # Sort Bids descending (highest price first)
        sorted_bids = sorted(self.bids.keys(), reverse=True)[:depth]
        bids_levels = tuple(
            OrderBookLevel(price=p, size=self.bids[p]) for p in sorted_bids
        )

        # Sort Asks ascending (lowest price first)
        sorted_asks = sorted(self.asks.keys(), reverse=False)[:depth]
        asks_levels = tuple(
            OrderBookLevel(price=p, size=self.asks[p]) for p in sorted_asks
        )

        return OrderBookSnapshot(
            instrument=self.instrument,
            sequence=self.last_sequence,
            exchange_timestamp=self.exchange_timestamp,
            received_at=self.received_at,
            bids=bids_levels,
            asks=asks_levels,
            status=self.status,
        )


class OrderBookProjectionRegistry:
    def __init__(self):
        self._projections: Dict[str, OrderBookProjection] = {}

    def get_projection(
        self, exchange: str, symbol: str, market_type: MarketType = MarketType.PERPETUAL
    ) -> OrderBookProjection:
        if market_type != MarketType.PERPETUAL:
            raise NotImplementedError("Only perpetual futures are supported in v1.0")
        key = f"{exchange}:{market_type.value}:{symbol}"
        if key not in self._projections:
            instrument = InstrumentId(
                exchange=exchange, market_type=market_type, symbol=symbol
            )
            self._projections[key] = OrderBookProjection(instrument)
        return self._projections[key]


# Global projection registry singleton
orderbook_registry = OrderBookProjectionRegistry()
