def register(mcp, get_user_id, store_factory) -> None:
    from .guide import register as register_guide
    from .recall import register as register_recall
    from .remember import register as register_remember
    from .clarifications import register as register_clarifications

    register_guide(mcp, get_user_id, store_factory)
    register_recall(mcp, get_user_id, store_factory)
    register_remember(mcp, get_user_id, store_factory)
    register_clarifications(mcp, get_user_id, store_factory)
