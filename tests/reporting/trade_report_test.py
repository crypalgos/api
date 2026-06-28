import pytest
from crypalgos_core.metrics.trade import CompletedTrade
from crypalgos_core.reporting.trade_analytics import build_trade_reports

def test_trade_report_calculations():
    # Mock an execution record for a LONG trade
    trade = CompletedTrade(
        symbol="BTCUSD",
        side="LONG",
        entry_price=50000.0,
        exit_price=55000.0,
        amount=1.0,
        entry_time=1700000000000,
        exit_time=1700000000000 + 3600000, # +1 hour
        pnl=4900.0, # Gross PnL (5000) - Total Fees (100) = 4900
        entry_fee=50.0,
        exit_fee=50.0,
        total_fees=100.0,
        leverage=10.0,
        portfolio_equity_after=104900.0,
        exit_label="take_profit"
    )
    
    reports = build_trade_reports([trade])
    assert len(reports) == 1
    
    report = reports[0]
    
    # Verify core calculations
    assert report.trade_number == 1
    assert report.position_value == 50000.0
    assert report.gross_pnl == 5000.0
    assert report.net_pnl == 4900.0
    
    # Margin used = 50000 / 10 = 5000
    # Return % = 4900 / 5000 = 98%
    assert report.return_pct == 98.0
    
    # Fees split
    assert report.fees.entry == 50.0
    assert report.fees.exit == 50.0
    assert report.fees.total == 100.0
    
    # Duration
    assert report.duration_ms == 3600000
    
    # Exit mapping
    assert report.exit_reason.code == "take_profit"
    assert report.exit_reason.label == "Take Profit"
