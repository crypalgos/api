import inspect
from typing import Any


async def resolve_broker_call(value: Any) -> Any:
    """ExecutionBroker's ABC declares submit_order/get_position/get_balances as
    plain sync methods; PaperBroker honors that, but LiveExchangeBroker overrides
    them as `async def` (it has to — it calls Delta's async REST client). Calling
    those without awaiting silently returns a coroutine object instead of the
    real result. Awaiting only when actually awaitable lets callers drive both
    broker types without special-casing broker type.
    """
    if inspect.isawaitable(value):
        return await value
    return value
