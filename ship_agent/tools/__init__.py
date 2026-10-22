"""Tool package; load the public registry only when requested."""

__all__ = ["create_tools"]


def __getattr__(name):
    if name == "create_tools":
        from ship_agent.tools.registry import create_tools
        return create_tools
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
