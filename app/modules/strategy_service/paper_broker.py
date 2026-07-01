import time
import uuid
from typing import Dict, Any
from crypalgos_core.engine.broker import ExecutionBroker, OrderReceipt

class PaperBroker(ExecutionBroker):
    def __init__(self, initial_capital: float = 10000.0, fee_rate: float = 0.0002):
        self.cash = initial_capital
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.positions: Dict[str, Dict[str, Any]] = {}  # symbol -> position details
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.mark_prices: Dict[str, float] = {}

    def update_mark_price(self, symbol: str, price: float) -> None:
        self.mark_prices[symbol] = price
        if symbol in self.positions:
            pos = self.positions[symbol]
            qty = pos["qty"]
            entry = pos["entry_price"]
            if pos["side"] == "LONG":
                pos["unrealized_pnl"] = qty * (price - entry)
            else:
                pos["unrealized_pnl"] = qty * (entry - price)

    def submit_order(self, symbol: str, side: str, qty: float, price: float, order_type: str) -> OrderReceipt:
        order_id = str(uuid.uuid4())[:8]
        timestamp = time.time()
        
        # Get execution price
        exec_price = price if order_type == "LIMIT" else self.mark_prices.get(symbol, 1.0)
        
        # Fee calculation
        fee = qty * exec_price * self.fee_rate
        total_cost = fee
        
        if side == "LONG":
            margin_required = (qty * exec_price)
            if self.cash < margin_required + fee:
                return OrderReceipt(
                    order_id=order_id, status="REJECTED", filled_qty=0.0, average_price=0.0, timestamp=timestamp
                )
            
            self.cash -= (margin_required + fee)
            
            # Position update
            if symbol not in self.positions or self.positions[symbol]["qty"] == 0:
                self.positions[symbol] = {
                    "position_id": order_id,
                    "symbol": symbol,
                    "side": "LONG",
                    "qty": qty,
                    "entry_price": exec_price,
                    "unrealized_pnl": 0.0,
                    "timestamp": timestamp
                }
            else:
                pos = self.positions[symbol]
                if pos["side"] == "LONG":
                    # Average entry
                    old_cost = pos["qty"] * pos["entry_price"]
                    new_cost = qty * exec_price
                    pos["qty"] += qty
                    pos["entry_price"] = (old_cost + new_cost) / pos["qty"]
                else:
                    # Closing or reducing short
                    old_qty = pos["qty"]
                    if qty >= old_qty:
                        # Fully closed short
                        pnl = old_qty * (pos["entry_price"] - exec_price)
                        self.cash += (old_qty * pos["entry_price"]) + pnl
                        self.positions[symbol] = {
                            "position_id": order_id,
                            "symbol": symbol,
                            "side": "LONG",
                            "qty": qty - old_qty,
                            "entry_price": exec_price,
                            "unrealized_pnl": 0.0,
                            "timestamp": timestamp
                        }
                    else:
                        # Partially reduced short
                        pnl = qty * (pos["entry_price"] - exec_price)
                        self.cash += (qty * pos["entry_price"]) + pnl
                        pos["qty"] -= qty

        else: # SHORT side
            margin_required = (qty * exec_price)
            if self.cash < margin_required + fee:
                return OrderReceipt(
                    order_id=order_id, status="REJECTED", filled_qty=0.0, average_price=0.0, timestamp=timestamp
                )
            
            self.cash -= fee # Deduct fee
            
            if symbol not in self.positions or self.positions[symbol]["qty"] == 0:
                self.positions[symbol] = {
                    "position_id": order_id,
                    "symbol": symbol,
                    "side": "SHORT",
                    "qty": qty,
                    "entry_price": exec_price,
                    "unrealized_pnl": 0.0,
                    "timestamp": timestamp
                }
            else:
                pos = self.positions[symbol]
                if pos["side"] == "SHORT":
                    # Average entry
                    old_cost = pos["qty"] * pos["entry_price"]
                    new_cost = qty * exec_price
                    pos["qty"] += qty
                    pos["entry_price"] = (old_cost + new_cost) / pos["qty"]
                else:
                    # Closing or reducing long
                    old_qty = pos["qty"]
                    if qty >= old_qty:
                        # Fully closed long
                        pnl = old_qty * (exec_price - pos["entry_price"])
                        self.cash += (old_qty * pos["entry_price"]) + pnl
                        self.positions[symbol] = {
                            "position_id": order_id,
                            "symbol": symbol,
                            "side": "SHORT",
                            "qty": qty - old_qty,
                            "entry_price": exec_price,
                            "unrealized_pnl": 0.0,
                            "timestamp": timestamp
                        }
                    else:
                        # Partially reduced long
                        pnl = qty * (exec_price - pos["entry_price"])
                        self.cash += (qty * pos["entry_price"]) + pnl
                        pos["qty"] -= qty

        return OrderReceipt(
            order_id=order_id,
            status="FILLED",
            filled_qty=qty,
            average_price=exec_price,
            timestamp=timestamp
        )

    def cancel_order(self, order_id: str) -> bool:
        return True

    def get_position(self, symbol: str) -> Dict[str, Any]:
        if symbol not in self.positions:
            return {"position_id": "", "symbol": symbol, "side": "LONG", "qty": 0.0, "entry_price": 0.0, "unrealized_pnl": 0.0}
        return self.positions[symbol]

    def get_balances(self) -> Dict[str, Any]:
        margin = 0.0
        for pos in self.positions.values():
            margin += (pos.get("qty", 0.0) * pos.get("entry_price", 0.0))
        equity = self.cash + margin
        for pos in self.positions.values():
            equity += pos.get("unrealized_pnl", 0.0)
        return {
            "cash": self.cash,
            "equity": equity
        }
