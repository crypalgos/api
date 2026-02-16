from .base_client import BaseExchangeClient

class DeltaExchangeClient(BaseExchangeClient):
    def __init__(self, broker, symbols=["BTCUSD", "ETHUSD"]):
        URL = "wss://socket.india.delta.exchange"
        super().__init__(broker, "delta", URL)
        self.symbols = symbols

    def get_subscription_payload(self) -> dict:
        return {
            "type": "subscribe",
            "payload": {
                "channels": [
                    {
                        "name": "all_trades",
                        "symbols": self.symbols
                    },
                    {
                        "name": "candlestick_1m",
                        "symbols": self.symbols
                    },
                    {
                        "name": "v2/ticker",
                        "symbols": self.symbols
                    }
                ]
            }
        }

    def normalize_message(self, message: dict):
        # Delta trade message format handled in updates below
        msg_type = message.get("type")
        
        if msg_type == "all_trades":
            return {
                "exchange": "delta",
                "symbol": message.get("symbol"),
                "price": float(message.get("price")),
                "amount": float(message.get("size")),
                "timestamp": message.get("timestamp"),
                "side": "sell" if message.get("buyer_role") == "maker" else "buy"
            }
        
        if msg_type == "candlestick_1m":
            return ("ohlcv", {
                "exchange": "delta",
                "symbol": message.get("symbol"),
                "open": float(message.get("open")),
                "high": float(message.get("high")),
                "low": float(message.get("low")),
                "close": float(message.get("close")),
                "volume": float(message.get("volume")),
                "timestamp": message.get("timestamp")
            })

        if msg_type == "v2/ticker":
            return ("ticker", {
                "exchange": "delta",
                "symbol": message.get("symbol"),
                "bid": float(message.get("best_bid", 0)),
                "ask": float(message.get("best_ask", 0)),
                "last": float(message.get("last_price", 0)),
                "mark_price": float(message.get("mark_price", 0)),
                "volume_24h": float(message.get("volume_24h", 0)),
                "timestamp": message.get("timestamp")
            })
            
        return None
