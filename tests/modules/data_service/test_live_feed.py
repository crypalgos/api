from app.modules.data_service.live_feed import LiveFeedSubscriber


async def test_symbol_dispatch_routes_one_decoded_message_only_to_matching_consumers():
    feed = LiveFeedSubscriber("tcp://127.0.0.1:5555")
    received: list[str] = []

    async def btc_callback(topic: str, data: dict) -> None:
        received.append(f"btc:{topic}:{data['symbol']}")

    async def eth_callback(topic: str, data: dict) -> None:
        received.append(f"eth:{topic}:{data['symbol']}")

    async def global_callback(topic: str, data: dict) -> None:
        received.append(f"global:{topic}:{data['symbol']}")

    feed.register_callback("btcusd", btc_callback)
    feed.register_callback("ETHUSD", eth_callback)
    feed.register_global_callback(global_callback)

    await feed._dispatch("trades.delta", {"symbol": "BTCUSD", "price": 100.0})

    assert received == [
        "btc:trades.delta:BTCUSD",
        "global:trades.delta:BTCUSD",
    ]


async def test_symbol_dispatch_keeps_snapshot_when_callback_unregisters_itself():
    feed = LiveFeedSubscriber("tcp://127.0.0.1:5555")
    received: list[str] = []

    async def self_removing_callback(topic: str, data: dict) -> None:
        received.append("self")
        feed.unregister_callback("BTCUSD", self_removing_callback)

    async def persistent_callback(topic: str, data: dict) -> None:
        received.append("persistent")

    feed.register_callback("BTCUSD", self_removing_callback)
    feed.register_callback("BTCUSD", persistent_callback)

    await feed._dispatch("ticker.delta", {"symbol": "BTCUSD", "last": 100.0})
    await feed._dispatch("ticker.delta", {"symbol": "BTCUSD", "last": 101.0})

    assert received == ["self", "persistent", "persistent"]


async def test_symbol_dispatch_ignores_symbol_consumers_for_malformed_messages():
    feed = LiveFeedSubscriber("tcp://127.0.0.1:5555")
    received: list[str] = []

    async def callback(topic: str, data: dict) -> None:
        received.append(topic)

    feed.register_callback("BTCUSD", callback)
    await feed._dispatch("ticker.delta", {})

    assert received == []
