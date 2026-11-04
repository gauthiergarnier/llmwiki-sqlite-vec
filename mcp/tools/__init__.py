def register(mcp, get_user_id, fs_factory) -> None:
    from .comments import register as register_comments
    from .delete import register as register_delete
    from .guide import register as register_guide
    from .lint import register as register_lint
    from .list import register as register_list
    from .read import register as register_read
    from .reply import register as register_reply
    from .search import register as register_search
    from .write import register as register_write

    register_guide(mcp, get_user_id, fs_factory)
    register_list(mcp, get_user_id, fs_factory)
    register_search(mcp, get_user_id, fs_factory)
    register_read(mcp, get_user_id, fs_factory)
    register_write(mcp, get_user_id, fs_factory)
    register_delete(mcp, get_user_id, fs_factory)
    register_lint(mcp, get_user_id, fs_factory)
    register_reply(mcp, get_user_id, fs_factory)
    register_comments(mcp, get_user_id, fs_factory)
