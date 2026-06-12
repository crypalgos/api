import time

import requests


def main():
    base_url = "http://localhost:8000/api/v1"
    # Wait for API to be ready just in case
    time.sleep(1)
    
    login_data = {
        "username": "ashishjangde54@gmail.com",
        "password": "12345678@As"
    }
    
    resp = requests.post(f"{base_url}/auth/login", data=login_data)
    
    if resp.status_code != 200:
        print("Login failed via form data. Trying raw JSON:")
        resp = requests.post(f"{base_url}/auth/login", json={"email": "ashishjangde54@gmail.com", "password": "12345678@As"})
        if resp.status_code != 200:
            resp = requests.post(f"{base_url}/auth/login", json={"identifier": "ashishjangde54@gmail.com", "password": "12345678@As"})
            if resp.status_code != 200:
                print("Login definitely failed:")
                print(resp.json())
                return
            
    token = resp.json()["data"]["access_token"]
    print("Logged in!")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Profitable Trend Pullback Strategy
    institutional_strategy = {
      "name": "Profitable Trend Pullback Strategy",
      "description": "Uses 1H timeframe EMA 200 trend filter and RSI oversold dips with dynamic ATR-based SL/TP to yield positive equity curve.",
      "canvas_json": {
        "nodes": [
          {
            "id": "start-1",
            "type": "startNode",
            "data": {
              "label": "Start Strategy",
              "exchange": "delta",
              "leverage": 2,
              "position_size_pct": 0.05,
              "max_drawdown_pct": 0.3,
              "atr_sl_mult": 2.5,
              "atr_tp_mult": 5.0,
              "max_open_positions": 3
            }
          },
          {
            "id": "data-btc",
            "type": "dataNode",
            "data": {
              "symbol": "BTCUSD",
              "assetClass": "PERPETUAL",
              "timeframe": "1h"
            }
          },
          {
            "id": "ind-ema",
            "type": "indicatorNode",
            "data": {
              "indicator": "EMA",
              "period": 200
            }
          },
          {
            "id": "ind-rsi",
            "type": "indicatorNode",
            "data": {
              "indicator": "RSI",
              "period": 14
            }
          },
          {
            "id": "cond-complex",
            "type": "conditionNode",
            "data": {
              "ast_root": {
                "type": "GROUP",
                "operator": "AND",
                "children": [
                  {
                    "type": "CONDITION",
                    "left": "Close",
                    "operator": ">",
                    "right": "EMA"
                  },
                  {
                    "type": "CONDITION",
                    "left": "RSI",
                    "operator": "<",
                    "right": 45
                  }
                ]
              }
            }
          },
          {
            "id": "act-close",
            "type": "actionNode",
            "data": {
              "actionType": "close_all",
              "trigger": "BAR"
            }
          },
          {
            "id": "act-buy",
            "type": "actionNode",
            "data": {
              "actionType": "buy",
              "amount": 0.5,
              "trigger": "BAR"
            }
          }
        ],
        "edges": [
          {"id": "e1", "source": "start-1", "target": "data-btc"},
          {"id": "e2", "source": "data-btc", "target": "ind-ema"},
          {"id": "e3", "source": "data-btc", "target": "ind-rsi"},
          {"id": "e4", "source": "ind-ema", "target": "cond-complex"},
          {"id": "e5", "source": "ind-rsi", "target": "cond-complex"},
          {"id": "e6", "source": "cond-complex", "target": "act-close", "sourceHandle": "true"},
          {"id": "e7", "source": "act-close", "target": "act-buy"}
        ]
      }
    }

    print("Creating Institutional Strategy...")
    resp = requests.post(f"{base_url}/strategies", headers=headers, json=institutional_strategy)
    if resp.status_code != 201:
        print("Failed to create Strategy:", resp.text)
        return
    strategy_data = resp.json()["data"]
    s_id = strategy_data["id"]
    print(f"Strategy created with ID: {s_id}")
    print("--- COMPILED CODE ---")
    print(strategy_data["compiled_code"])
    print("---------------------\n")

    bt_payload = {
        "start_date": "2026-05-01T00:00:00Z",
        "end_date": "2026-06-05T00:00:00Z",
        "initial_capital": 100000.0
    }

    print("Triggering Backtest...")
    bt_resp = requests.post(f"{base_url}/strategies/{s_id}/backtest", headers=headers, json=bt_payload)
    if bt_resp.status_code != 202:
        print("Failed to start backtest:", bt_resp.text)
    else:
        print("Backtest started successfully. Output:")
        print(bt_resp.json()["data"])

if __name__ == "__main__":
    main()
