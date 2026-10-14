"""Agent Server entry point; langgraph.json loads environment before calling this."""

from langchain_core.runnables import RunnableConfig

from ship_agent.agent import build_agent


def make_graph(config: RunnableConfig):
    """Build a graph per run so the reference date stays current."""
    return build_agent()
