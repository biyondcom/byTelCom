from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack

from anthropic import AsyncAnthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from storage.database import get_conversation_messages

logger = logging.getLogger(__name__)


class ClaudeBridge:
    """Anthropic API bridge with MCP tool support."""

    def __init__(self, config: dict):
        api_key = config.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = config.get("model", "claude-sonnet-4-20250514")
        self._max_tokens = config.get("max_tokens", 16384)
        self._timeout = config.get("timeout", 300)
        self._system_prompt = config.get("system_prompt", "")
        self._mcp_config = config.get("mcp_server")

        # MCP session state (lazy init)
        self._mcp_session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._tools: list[dict] = []
        self._mcp_lock = asyncio.Lock()

    async def _ensure_mcp(self):
        """Start MCP server subprocess if not already running."""
        if self._mcp_session is not None:
            return
        if not self._mcp_config:
            return

        async with self._mcp_lock:
            if self._mcp_session is not None:
                return

            logger.info("[MCP] Starting server: %s %s",
                        self._mcp_config["command"],
                        " ".join(self._mcp_config.get("args", [])))

            self._exit_stack = AsyncExitStack()
            await self._exit_stack.__aenter__()

            server_params = StdioServerParameters(
                command=self._mcp_config["command"],
                args=self._mcp_config.get("args", []),
                env=self._mcp_config.get("env"),
            )

            stdio_transport = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read_stream, write_stream = stdio_transport
            self._mcp_session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self._mcp_session.initialize()

            # Cache tool definitions
            tools_result = await self._mcp_session.list_tools()
            self._tools = []
            for tool in tools_result.tools:
                self._tools.append({
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema,
                })
            logger.info("[MCP] %d tools available: %s",
                        len(self._tools),
                        [t["name"] for t in self._tools])

    async def send_prompt(self, prompt: str, session_id: str, conv_id: int) -> str:
        """Send a prompt via Anthropic API with MCP tool loop."""
        await self._ensure_mcp()

        # Load conversation history from DB
        history = await get_conversation_messages(conv_id)
        # Add current user message
        messages = [{"role": m["role"], "content": m["content"]} for m in history]
        messages.append({"role": "user", "content": prompt})

        # Build system prompt (include MCP server instructions if available)
        system = self._system_prompt or ""
        if self._mcp_session:
            try:
                instructions = await self._mcp_session.get_prompt("instructions", {})
                if instructions and instructions.messages:
                    for msg in instructions.messages:
                        if hasattr(msg.content, "text"):
                            system += "\n\n" + msg.content.text
            except Exception:
                pass  # Server may not provide instructions prompt

        # API call kwargs
        kwargs: dict = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": messages,
        }
        if system.strip():
            kwargs["system"] = system.strip()
        if self._tools:
            kwargs["tools"] = self._tools

        # Tool-use loop
        max_rounds = 30
        for round_num in range(max_rounds):
            logger.info("[API] Round %d, %d messages", round_num + 1, len(messages))

            try:
                response = await asyncio.wait_for(
                    self._client.messages.create(**kwargs),
                    timeout=self._timeout,
                )
            except asyncio.TimeoutError:
                logger.error("[API] Timeout after %ds", self._timeout)
                return "[Timeout] Claude hat nicht rechtzeitig geantwortet."
            except Exception as e:
                logger.error("[API] Error: %s", e)
                return f"[API Error] {e}"

            logger.info("[API] stop_reason=%s, content_blocks=%d",
                        response.stop_reason, len(response.content))

            # If no tool use, extract text and return
            if response.stop_reason != "tool_use":
                text_parts = []
                for block in response.content:
                    if block.type == "text":
                        text_parts.append(block.text)
                return "\n".join(text_parts) or "[Empty response from Claude]"

            # Process tool calls
            assistant_content = []
            tool_results = []
            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
                    # Execute via MCP
                    logger.info("[MCP] Calling tool: %s(%s)",
                                block.name, json.dumps(block.input, ensure_ascii=False)[:500])
                    try:
                        result = await self._mcp_session.call_tool(block.name, block.input)
                        result_text = ""
                        for item in result.content:
                            if hasattr(item, "text"):
                                result_text += item.text
                        is_error = result.isError if hasattr(result, "isError") else False
                        logger.info("[MCP] Tool %s result (%d chars, error=%s): %s",
                                    block.name, len(result_text), is_error, result_text[:500])
                    except Exception as e:
                        logger.error("[MCP] Tool %s failed: %s", block.name, e)
                        result_text = f"Error calling tool: {e}"
                        is_error = True

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                        "is_error": is_error,
                    })

            # Append assistant turn and tool results to messages
            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})
            kwargs["messages"] = messages

        return "[Error] Maximale Anzahl an Tool-Aufrufen erreicht."

    async def close(self):
        """Shut down MCP server subprocess."""
        if self._exit_stack:
            logger.info("[MCP] Shutting down server")
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                logger.warning("[MCP] Shutdown error: %s", e)
            self._mcp_session = None
            self._exit_stack = None
            self._tools = []
