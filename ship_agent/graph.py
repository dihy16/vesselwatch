"""Agent Server entry point; langgraph.json loads environment before calling this."""

from langchain_core.runnables import RunnableConfig

from ship_agent.clients.file_server_client import load_observations
from ship_agent.runtime.agent import build_agent


# LangGraph imports this entry point at startup; share the snapshot across runs.
observations = load_observations()


def make_graph(config: RunnableConfig):
    """Keep the reference date current while reusing observations loaded at startup."""
    return build_agent(observations=observations)
