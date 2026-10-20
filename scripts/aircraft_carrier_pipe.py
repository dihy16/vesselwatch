"""
title: LangGraph Pipe with human-in-the-loop
author: Leandro Pessini - https://github.com/pessini
version: 0.2.0
requires: langgraph-sdk v0.2.6
license: MIT
"""

from html import escape
import logging
import re
from typing import AsyncGenerator, Dict, Optional, Union
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from langgraph_sdk.client import get_client
from langgraph_sdk.schema import Command
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# "LANGGRAPH_SERVER_URL", "http://langgraph-api:8000"  # When running via docker

# When running via langgraph dev and open webui is installed via pip
# "LANGGRAPH_SERVER_URL", "http://localhost:2024"

# "LANGGRAPH_SERVER_URL", "http://host.docker.internal:2024",  # When running via langgraph dev


class Pipe:
    class Valves(BaseModel):
        LANGGRAPH_SERVER_URL: str = Field(default="http://localhost:2024")
        MODEL_ID: str = Field(default="agent")
        VERSION: str = Field(default="v1.0")
        DEBUG_LOGGING: bool = Field(default=False)
        SHOW_TOOL_CALLS: bool = Field(default=False)
        MAP_URL: str = Field(default="", description="URL map mở được từ trình duyệt; để trống để tắt liên kết vùng.")
        MAP_API_URL: str = Field(default="http://127.0.0.1:8000", description="Server map nhìn từ backend Open WebUI, dùng để đọc vùng chat.")

    class Metadata(BaseModel):
        user: str
        user_id: str
        chat_id: str
        message_id: str
        group_id: str
        user_message: str
        model_name: str

    def __init__(self):
        self.name = "LangGraph Pipe"
        self.valves = self.Valves()
        self.client = None

    def _initialize_client(self):
        """Initialize the LangGraph client."""
        try:
            if self.client is None:
                if self.valves.DEBUG_LOGGING:
                    logger.info(
                        f"Initializing LangGraph client with URL: {self.valves.LANGGRAPH_SERVER_URL}"
                    )
                self.client = get_client(url=self.valves.LANGGRAPH_SERVER_URL)
                if self.valves.DEBUG_LOGGING:
                    logger.info("LangGraph client initialized successfully")
                return True
        except Exception as e:
            logger.error(f"Failed to initialize LangGraph client: {e}")
            self.client = None
            return False

    def on_startup(self):
        """Called when the server is started."""
        logger.info(f"on_startup: {__name__}")
        self._initialize_client()

    def on_shutdown(self):
        """Called when the server is shutdown."""
        logger.info(f"on_shutdown: {__name__}")
        if self.client:
            self.client = None

    def _extract_metadata(
        self,
        body: dict,
        __metadata__: Optional[Dict] = None,
        __user__: Optional[Dict] = None,
    ) -> Metadata:
        """
        Extract and validate metadata from OpenWebUI request.

        Returns:
            Metadata object containing validated metadata

        Raises:
            ValueError: If required metadata is missing
        """
        if __metadata__ is None:
            raise ValueError("Missing metadata")

        # Extract required fields
        user = __user__.get("email") if __user__ else "anonymous"
        user_id = __metadata__.get("user_id")
        chat_id = __metadata__.get("chat_id")
        message_id = __metadata__.get("message_id")

        if not user_id or not chat_id:
            raise ValueError("Missing user_id or chat_id in metadata")

        messages = body.get("messages", [])
        if not messages:
            raise ValueError("No messages provided")

        # Extract group_id safely
        try:
            group_id = (
                __metadata__.get("model")
                .get("info")
                .get("access_control")
                .get("read")
                .get("group_ids")[0]
            )
        except (AttributeError, KeyError, IndexError, TypeError):
            group_id = "default"

        user_message = messages[-1]["content"]

        # Get model name for status messages
        model_name = "AI"
        if __metadata__ and "model" in __metadata__:
            model_name = __metadata__["model"].get("name", "AI")

        return self.Metadata(
            user=user,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            group_id=group_id,
            user_message=user_message,
            model_name=model_name,
        )

    def _status(self, message: str = "", done: bool = False) -> Dict:
        """Helper to create status events."""
        return {
            "event": {"type": "status", "data": {"description": message, "done": done}}
        }

    async def _chat_area_snapshot(self, metadata):
        """Read once per question; tools share this exact confirmed-area revision."""
        identity = {"user_id": metadata.user_id, "chat_id": metadata.chat_id}
        if not self.valves.MAP_URL.strip():
            return None
        try:
            url = urlsplit(self.valves.MAP_URL.strip())
            if (url.scheme not in {"http", "https"} or not url.hostname
                    or url.username or url.password):
                raise ValueError("MAP_URL không hợp lệ.")
            url.port
            async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
                response = await client.post(self.valves.MAP_API_URL.rstrip("/") + "/map-sessions",
                                             json=identity)
                response.raise_for_status()
                saved = response.json()
            if (not isinstance(saved, dict)
                    or any(saved.get(key) != value for key, value in identity.items())
                    or not re.fullmatch(r"[a-f0-9]{64}", saved.get("session_id", ""))
                    or type(saved.get("revision")) is not int
                    or saved["revision"] < 0 or "active_area" not in saved):
                raise ValueError("Phản hồi vùng chat không hợp lệ.")
            query = [(key, value) for key, value in parse_qsl(url.query, keep_blank_values=True)
                     if key != "map_session"]
            query.append(("map_session", saved["session_id"]))
            map_url = urlunsplit((url.scheme, url.netloc, url.path, urlencode(query), url.fragment))
            return {**identity, "session_id": saved["session_id"], "active_area": saved["active_area"],
                    "revision": saved["revision"], "map_url": map_url}
        except (httpx.HTTPError, httpx.InvalidURL, ValueError, TypeError):
            # Carry an explicit error, never fall back to last turn's polygon.
            logger.warning("Could not load the confirmed chat area from the map API")
            return {**identity, "error": "map_api_unavailable"}

    @staticmethod
    def _map_artifact(context):
        url = escape(context["map_url"], quote=True)
        return f'''Bản đồ của cuộc chat. Vẽ/chọn một vùng rồi bấm Xác nhận vùng.

```html
<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><title>Bản đồ tàu</title>
<meta name="referrer" content="strict-origin-when-cross-origin">
<style>html,body{{margin:0;padding:0}}iframe{{display:block;width:100%;height:100vh;border:0}}</style>
</head><body><iframe title="Bản đồ tàu" src="{url}"
referrerpolicy="strict-origin-when-cross-origin"
sandbox="allow-scripts allow-same-origin allow-downloads"></iframe></body></html>
```'''

    # threads are created independently and then associated with assistants when you start a run.
    async def create_thread(self, user_id: str, thread_id: str) -> str:
        """Create or get existing thread."""
        if self.client is None:
            if self.valves.DEBUG_LOGGING:
                logger.info("LangGraph client is not initialized. Initializing...")
            if not self._initialize_client():
                raise RuntimeError("Failed to initialize LangGraph client.")

        try:
            thread = await self.client.threads.create(
                thread_id=thread_id,
                metadata={"user_id": user_id},
                if_exists="do_nothing",
            )
            return thread["thread_id"]
        except Exception as e:
            logger.error(f"Failed to create thread {thread_id}: {e}")
            raise

    async def _stream_run(
        self,
        thread_id: str,
        assistant_id: str,
        input_data: Dict | Command,
        metadata: Dict = None,
        config: Dict = None,
    ) -> AsyncGenerator[Union[str, Dict], None]:
        """
        Common streaming method for both new runs and interrupt handling.
        """

        is_command_input = False
        try:
            # Get the current state of the thread
            thread_state = await self.client.threads.get_state(thread_id)

            # Check for interrupts in tasks
            interrupts = (
                thread_state.get("interrupts", [])
                if isinstance(thread_state, dict)
                else getattr(thread_state, "interrupts", [])
            )
            has_interrupts = bool(interrupts)

            # Check if input_data is a user message
            is_user_message = isinstance(input_data, dict) and "messages" in input_data
            if has_interrupts and is_user_message:
                if self.valves.DEBUG_LOGGING:
                    logger.info(
                        f"Converting user message to resume command for thread {thread_id}"
                    )

                input_data = Command(resume=input_data["messages"])
                is_command_input = True

        except Exception as e:
            if self.valves.DEBUG_LOGGING:
                logger.info(
                    f"Could not check thread state for interrupts: {e}, proceeding with normal run"
                )

        # Build base arguments
        stream_args = {
            "thread_id": thread_id,
            "assistant_id": assistant_id,
            "metadata": metadata or {},
            "config": config,
            "stream_mode": ["messages-tuple", "updates"],
        }

        input_key = "command" if is_command_input else "input"
        stream_args[input_key] = input_data

        if self.valves.DEBUG_LOGGING:
            logger.info(f"Starting stream_run with args: {stream_args}")

        try:
            async for chunk in self.client.runs.stream(**stream_args):
                if not chunk or not chunk.data:
                    continue

                if self.valves.DEBUG_LOGGING:
                    self._pretty_print_chunk(chunk)

                event_type = chunk.event
                # Handle different event types
                if event_type == "updates":
                    # Handle human-in-the-loop interrupts
                    if "__interrupt__" in chunk.data:
                        interrupt_data = chunk.data["__interrupt__"][0]
                        interrupt_id = interrupt_data["id"]
                        interrupt_value = interrupt_data["value"]

                        if self.valves.DEBUG_LOGGING:
                            logger.info(
                                f"Interrupt encountered in thread {thread_id}: id={interrupt_id}, value={interrupt_value!r}"
                            )

                        yield interrupt_value
                        continue  # Stop streaming here, wait for next user message

                    # Show tool calls if not hidden
                    if self.valves.SHOW_TOOL_CALLS:
                        try:
                            # Get the first node data (whatever the node name is)
                            node_data = next(iter(chunk.data.values()), None)
                            if node_data and node_data.get("messages"):
                                tool_calls = node_data["messages"][0].get(
                                    "tool_calls", []
                                )
                                if tool_calls:
                                    tool_name = tool_calls[0].get("name")
                                    if tool_name:
                                        yield self._status(
                                            f"🛠️ Tool {tool_name} requested...",
                                            done=False,
                                        )

                        except (IndexError, KeyError, AttributeError, TypeError) as e:
                            logger.error(f"Error extracting tool call info: {e}")

                elif event_type == "messages":
                    message, metadata_chunk, *_ = chunk.data

                    if isinstance(message, dict):
                        content = message.get("content")
                        if not content:
                            continue

                        # Skip if this is from a tools node
                        if (
                            isinstance(metadata_chunk, dict)
                            and metadata_chunk.get("langgraph_node") == "tools"
                        ):
                            continue

                        yield self._status()  # Clear status
                        yield content  # Yield the actual message content

        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield self._status(f"❌ Streaming error: {str(e)}", done=True)

    async def pipe(
        self,
        body: dict,
        __metadata__: Optional[Dict] = None,
        __user__: Optional[Dict] = None,
        __task__: Optional[str] = None,
    ) -> AsyncGenerator[Union[str, Dict], None]:
        """
        Main pipe function for OpenWebUI integration.
        """

        try:
            if __task__:
                yield "VesselWatch"
                return
            # Extract and validate metadata
            metadata = self._extract_metadata(body, __metadata__, __user__)
            area_context = await self._chat_area_snapshot(metadata)
            if metadata.user_message.strip().casefold() in {"map", "mở map", "mở bản đồ"}:
                if area_context is None:
                    yield "Hãy đặt MAP_URL và MAP_API_URL trong Valves của Pipe hiện tại."
                elif area_context.get("error"):
                    yield "Chưa kết nối được API vùng chat. Hãy chạy scripts/run_vessel_map_demo.py và kiểm tra MAP_API_URL."
                else:
                    yield self._map_artifact(area_context)
                return
            # Show initial status
            yield self._status(
                f"🧠 {metadata.model_name} is thinking... Please wait a moment."
            )
            # Create thread
            thread_id = await self.create_thread(metadata.user_id, metadata.chat_id)

            # Prepare metadata and input data
            run_metadata = {
                "langfuse_user_id": metadata.user,
                "langfuse_tags": [metadata.group_id],
                "langfuse_session_id": thread_id,
                "message_id": metadata.message_id,
            }

            # Always use the same flow - _stream_run will handle interrupts internally
            input_data = {"messages": metadata.user_message}

            first_chunk = True
            async for chunk in self._stream_run(
                thread_id=thread_id,
                assistant_id=self.valves.MODEL_ID,
                input_data=input_data,
                metadata=run_metadata,
                config={"configurable": {"chat_area_context": area_context}},
            ):
                # Clear status on first chunk
                if first_chunk:
                    yield self._status()  # Empty message clears status
                    first_chunk = False

                yield chunk

        except ValueError as e:
            logger.error(f"Validation error: {e}")
            yield self._status(f"❌ Error: {str(e)}", done=True)
            return

        except Exception as e:
            logger.error(f"LangGraph pipe error: {e}", exc_info=True)
            yield self._status(f"❌ Error: {str(e)}", done=True)

    def _pretty_print_chunk(self, chunk):
        """Basic pretty printing with pprint"""

        if chunk.event.upper() == "MESSAGES":
            return

        import pprint

        print(f"\n{'=' * 60}")
        print(f"EVENT TYPE: {chunk.event.upper()}")
        print(f"{'=' * 60}")

        # Convert chunk data to dict for better formatting
        if hasattr(chunk, "data") and chunk.data:
            pprint.pprint(chunk.data, indent=2, width=120, depth=10)
        else:
            print("No data available")
