from dataclasses import dataclass


@dataclass
class sides:
    BUY = 'buy'
    SELL = 'sell'


@dataclass
class trade_types:
    LONG = 'long'
    SHORT = 'short'


@dataclass
class order_statuses:
    ACTIVE = 'ACTIVE'
    CANCELED = 'CANCELED'
    EXECUTED = 'EXECUTED'
    PARTIALLY_FILLED = 'PARTIALLY FILLED'
    QUEUED = 'QUEUED'
    LIQUIDATED = 'LIQUIDATED'
    REJECTED = 'REJECTED'


@dataclass
class timeframes:
    MINUTE_1 = '1m'
    MINUTE_3 = '3m'
    MINUTE_5 = '5m'
    MINUTE_15 = '15m'
    MINUTE_30 = '30m'
    MINUTE_45 = '45m'
    HOUR_1 = '1h'
    HOUR_2 = '2h'
    HOUR_3 = '3h'
    HOUR_4 = '4h'
    HOUR_6 = '6h'
    HOUR_8 = '8h'
    HOUR_12 = '12h'
    DAY_1 = '1D'
    DAY_3 = '3D'
    WEEK_1 = '1W'
    MONTH_1 = '1M'


@dataclass
class order_types:
    MARKET = 'MARKET'
    LIMIT = 'LIMIT'
    STOP = 'STOP'
    FOK = 'FOK'
    STOP_LIMIT = 'STOP LIMIT'


@dataclass
class exchanges:
    DELTA_EXCHANGE_PERPETUAL_FUTURES = 'Delta Exchange Perpetual Futures'
    DELTA_EXCHANGE_PERPETUAL_FUTURES_TESTNET = 'Delta Exchange Perpetual Futures Testnet'
    BINANCE_PERPETUAL_FUTURES = 'Binance Perpetual Futures'
    BINANCE_PERPETUAL_FUTURES_TESTNET = 'Binance Perpetual Futures Testnet'


@dataclass
class order_submitted_via:
    STOP_LOSS = 'stop-loss'
    TAKE_PROFIT = 'take-profit'


    
@dataclass
class live_session_statuses:
    DRAFT = 'draft'
    STARTING = 'starting'
    RUNNING = 'running'
    STOPPED = 'stopped'
    TERMINATED = 'terminated'

@dataclass
class live_session_modes:
    LIVETRADE = 'livetrade'
    PAPERTRADE = 'papertrade'
