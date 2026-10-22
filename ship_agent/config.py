"""Connection from LangGraph on MID to the local file server."""

FILE_SERVER_URL = "http://127.0.0.1:8001"

# Map-session API reached by LangGraph when selecting a chat area.
MAP_API_URL = "http://127.0.0.1:8000"

# Addresses reached by the data/map server when the user confirms a drawn area.
# Point each URL at the LangGraph server running the corresponding source.
LANGGRAPH_URL = "http://127.0.0.1:2024"
DEMO_LANGGRAPH_URL = "http://127.0.0.1:2024"
