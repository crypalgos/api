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
        """Instantiate an authenticated Delta broker for the session environment.

        `PAPER` maps to Delta Testnet and `LIVE` maps to Delta Production;
        both submit real exchange orders using their matching credentials.
        ``testnet`` is resolved from immutable session metadata by RuntimeFactory.
        """
        if broker == "delta":
            from app.modules.strategy_service.live_broker import LiveExchangeBroker

            logger.info(
                "BrokerFactory: creating Delta exchange broker "
                "(mode=%s, testnet=%s)",
                mode,
                testnet,
            )
            return LiveExchangeBroker(
                api_key=api_key,
                api_secret=api_secret,
                testnet=testnet,
            )

        raise ValueError(
            f"Unsupported broker '{broker}' for mode '{mode}'. Supported: broker=delta."
        )
