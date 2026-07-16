import logging
from crypalgos_core.engine.broker import ExecutionBroker

logger = logging.getLogger(__name__)


class BrokerFactory:
    """
    Open/Closed broker instantiation factory.
    Adding a new broker requires only adding a new branch here —
    LiveTradingRunner and Celery tasks remain unchanged.
    """

    @staticmethod
    def create(
        mode: str,
        broker: str,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = False,
    ) -> ExecutionBroker:
        """
        Instantiate the correct broker based on mode and broker name.

        Args:
            mode:       "LIVE" or "PAPER"
            broker:     "delta" | "paper" (future: "binance", "bybit")
            api_key:    Exchange API key (ignored for PAPER)
            api_secret: Exchange API secret (ignored for PAPER)
            testnet:    Use testnet endpoint for LIVE (default False)

        Returns:
            ExecutionBroker instance ready for use in runner
        """
        if mode == "PAPER":
            from app.modules.strategy_service.paper_broker import PaperBroker

            logger.info("BrokerFactory: creating PaperBroker")
            return PaperBroker()

        if broker == "delta":
            from app.modules.strategy_service.live_broker import LiveExchangeBroker

            logger.info(
                f"BrokerFactory: creating LiveExchangeBroker (testnet={testnet})"
            )
            return LiveExchangeBroker(
                api_key=api_key,
                api_secret=api_secret,
                testnet=testnet,
            )

        raise ValueError(
            f"Unsupported broker '{broker}' for mode '{mode}'. "
            "Supported: mode=PAPER (any broker), mode=LIVE broker=delta."
        )
