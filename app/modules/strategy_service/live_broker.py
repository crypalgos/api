import logging
import time
from typing import Dict, Any, Optional
from crypalgos_core.engine.broker import ExecutionBroker, OrderReceipt
from crypalgos_data.exchanges.delta import DeltaAPI
from app.config.settings import settings

logger = logging.getLogger(__name__)

class LiveExchangeBroker(ExecutionBroker):
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, testnet: bool = True):
        key = api_key or settings.get("DELTA_API_KEY", "")
        secret = api_secret or settings.get("DELTA_API_SECRET", "")
        
        # Instantiate Delta API from crypalgos_data
        self.api = DeltaAPI(api_key=key, api_secret=secret, testnet=testnet)

    async def submit_order(self, symbol: str, side: str, qty: float, price: float, order_type: str) -> OrderReceipt:
        logger.info(f"Submitting LIVE order to Delta Exchange: {side} {qty} {symbol} @ {price}")
        
        delta_side = "buy" if side == "LONG" else "sell"
        delta_type = "market" if order_type == "MARKET" else "limit"
        
        try:
            # Place order on Delta Exchange
            order = await self.api.place_order(
                symbol=symbol,
                size=qty,
                side=delta_side,
                order_type=delta_type,
                price=price if order_type == "LIMIT" else None
            )
            
            if not order:
                return OrderReceipt(
                    order_id="",
                    status="REJECTED",
                    filled_qty=0.0,
                    average_price=0.0,
                    timestamp=time.time()
                )
                
            status_str = "FILLED" if order.status.name == "CLOSED" else "SUBMITTED"
            
            return OrderReceipt(
                order_id=order.id,
                status=status_str,
                filled_qty=order.filled_size,
                average_price=order.average_price or price,
                timestamp=order.timestamp / 1000.0
            )
            
        except Exception as e:
            logger.error(f"Live order submission failed: {e}")
            return OrderReceipt(
                order_id="",
                status="REJECTED",
                filled_qty=0.0,
                average_price=0.0,
                timestamp=time.time()
            )

    async def cancel_order(self, order_id: str) -> bool:
        try:
            # Cancel order on Delta Exchange
            res = await self.api.cancel_order(order_id)
            return res is not None
        except Exception as e:
            logger.error(f"Live order cancel failed: {e}")
            return False

    async def get_position(self, symbol: str) -> Dict[str, Any]:
        try:
            positions = await self.api.fetch_positions()
            for pos in positions:
                if pos.symbol == symbol:
                    side = "LONG" if pos.size > 0 else "SHORT"
                    return {
                        "position_id": symbol,
                        "symbol": symbol,
                        "side": side,
                        "qty": abs(pos.size),
                        "entry_price": pos.entry_price,
                        "unrealized_pnl": pos.unrealized_pnl
                    }
        except Exception as e:
            logger.error(f"Failed to fetch live position: {e}")
            
        return {"position_id": "", "symbol": symbol, "side": "LONG", "qty": 0.0, "entry_price": 0.0, "unrealized_pnl": 0.0}

    async def get_balances(self) -> Dict[str, Any]:
        try:
            balances = await self.api.fetch_balances()
            # Calculate total cash/equity across all assets
            total_cash = sum(b.available for b in balances)
            total_equity = sum(b.total for b in balances)
            return {
                "cash": total_cash,
                "equity": total_equity
            }
        except Exception as e:
            logger.error(f"Failed to fetch live balances: {e}")
            
        return {"cash": 0.0, "equity": 0.0}
