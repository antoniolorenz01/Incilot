"""Claude Code as the agent's model, for running locally on a Claude subscription.

Local only: a subscription cannot back a public service, which keeps using the API.

    container (agent-worker) ──HTTP──► bridge on the host ──► `claude -p`

The bridge (`make claude-bridge`) runs on the host, where Claude Code is logged in, so
the agent's sandbox never sees the credentials. Each call is a headless `claude -p`
with no tools of its own: the conversation and our tools go in as text, and the reply
comes back as structured output (JSON validated against a schema) naming the tool
calls. To the graph it is one more chat model with tool calling.

Enable it with LLM_PROVIDER=claude-code in .env.
"""

import asyncio
import json
import os
import tempfile
from typing import Any
from uuid import uuid4

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

BRIDGE_URL = os.getenv("CLAUDE_BRIDGE_URL", "http://host.docker.internal:8300")
BRIDGE_TIMEOUT_SECONDS = 600
ATTEMPTS = 2  # a reply that is not valid JSON for the schema is retried once

TOOLS_PREAMBLE = """You act only through tools. Reply with the tool calls to make now, \
in the JSON format requested; several independent calls in one reply are fine. Use \
exactly the parameters each tool defines.

Available tools:"""


class ClaudeCodeChat(BaseChatModel):
    """A chat model with tool calling backed by `claude -p` (through the bridge)."""

    model: str = "sonnet"
    bridge_url: str = BRIDGE_URL

    @property
    def _llm_type(self) -> str:
        return "claude-code"

    @property
    def model_name(self) -> str:
        return f"claude-code:{self.model}"

    def bind_tools(self, tools, *, tool_choice: str | None = None, **kwargs):
        specs = [convert_to_openai_tool(t)["function"] for t in tools]
        return self.bind(tools=specs, tool_choice=tool_choice, **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return asyncio.run(self._agenerate(messages, stop, None, **kwargs))

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop=None,
        run_manager=None,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        **_: Any,
    ) -> ChatResult:
        if not tools:
            raise ValueError("ClaudeCodeChat needs tools: the graph always binds them")
        system = "\n\n".join(m.content for m in messages if isinstance(m, SystemMessage))
        request = {
            "model": self.model,
            "system": f"{system}\n\n{tools_prompt(tools)}".strip(),
            "prompt": transcript([m for m in messages if not isinstance(m, SystemMessage)]),
            "schema": calls_schema(tools, single=tool_choice is not None),
        }
        async with httpx.AsyncClient(timeout=BRIDGE_TIMEOUT_SECONDS) as http:
            for attempt in range(ATTEMPTS):
                response = await http.post(f"{self.bridge_url}/complete", json=request)
                if response.status_code == 200 or attempt + 1 == ATTEMPTS:
                    break
        if response.status_code != 200:
            raise RuntimeError(f"claude bridge: HTTP {response.status_code}: {response.text[:300]}")
        body = response.json()
        calls = [
            {"name": c["name"], "args": c["arguments"], "id": f"call_{uuid4().hex[:12]}"}
            for c in body["output"]["calls"]
        ]
        usage = body["usage"]
        message = AIMessage(
            content="",
            tool_calls=calls,
            usage_metadata={
                "input_tokens": usage["input"],
                "output_tokens": usage["output"],
                "total_tokens": usage["input"] + usage["output"],
            },
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


def tools_prompt(tools: list[dict]) -> str:
    lines = [TOOLS_PREAMBLE]
    for tool in tools:
        lines.append(f"\n- {tool['name']}: {tool.get('description', '').strip()}")
        lines.append(f"  parameters: {json.dumps(tool.get('parameters', {}))}")
    return "\n".join(lines)


def calls_schema(tools: list[dict], *, single: bool) -> dict:
    """{"calls": [...]}, each call one of the tools with its own parameter schema."""
    options = [
        {
            "type": "object",
            "properties": {
                "name": {"const": tool["name"]},
                "arguments": tool.get("parameters") or {"type": "object"},
            },
            "required": ["name", "arguments"],
            "additionalProperties": False,
        }
        for tool in tools
    ]
    calls = {"type": "array", "minItems": 1, "items": {"anyOf": options}}
    if single:
        calls["maxItems"] = 1
    return {
        "type": "object",
        "properties": {"calls": calls},
        "required": ["calls"],
        "additionalProperties": False,
    }


def transcript(messages: list[BaseMessage]) -> str:
    """The conversation so far as text: what was asked, the calls made and their results."""
    parts = []
    for message in messages:
        if isinstance(message, ToolMessage):
            parts.append(f"<result of {message.name} ({message.tool_call_id})>\n{message.content}")
        elif isinstance(message, AIMessage):
            calls = [
                f"{c['name']}({json.dumps(c['args'], ensure_ascii=False)}) [{c['id']}]"
                for c in message.tool_calls
            ]
            parts.append("<you called>\n" + "\n".join(calls or [str(message.content)]))
        else:
            parts.append(f"<{message.type}>\n{message.content}")
    parts.append("Decide the next tool calls.")
    return "\n\n".join(parts)


def claude_code_models() -> list[BaseChatModel]:
    names = [os.getenv("CLAUDE_CODE_MODEL", "sonnet")]
    if fallback := os.getenv("CLAUDE_CODE_FALLBACK_MODEL"):
        names.append(fallback)
    return [ClaudeCodeChat(model=name) for name in names]


# --- The bridge (runs on the host) ---------------------------------------------------


async def run_claude(model: str, system: str, prompt: str, schema: dict) -> dict:
    """One headless `claude -p` call: no tools, no MCP, no session saved, from an empty
    directory (so no CLAUDE.md is picked up)."""
    command = [
        "claude", "-p",
        "--tools", "",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--output-format", "json",
        "--model", model,
        "--system-prompt", system,
        "--json-schema", json.dumps(schema),
    ]  # fmt: skip
    with tempfile.TemporaryDirectory(prefix="incilot-claude-") as cwd:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(prompt.encode()), BRIDGE_TIMEOUT_SECONDS
        )
    if process.returncode != 0:
        raise RuntimeError(f"claude exited with {process.returncode}: {stderr.decode()[-300:]}")
    result = json.loads(stdout)
    if result.get("is_error") or not result.get("structured_output"):
        raise RuntimeError(f"claude: {result.get('subtype')}: {str(result.get('result'))[:300]}")
    usage = result.get("usage", {})
    return {
        "output": result["structured_output"],
        "usage": {
            "input": usage.get("input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0),
            "output": usage.get("output_tokens", 0),
        },
    }


def bridge():
    from fastapi import FastAPI, HTTPException

    app = FastAPI(title="Claude Code bridge")
    slots = asyncio.Semaphore(int(os.getenv("CLAUDE_BRIDGE_CONCURRENCY", "2")))

    @app.post("/complete")
    async def complete(request: dict):
        try:
            async with slots:
                return await run_claude(
                    request["model"], request["system"], request["prompt"], request["schema"]
                )
        except (KeyError, RuntimeError, TimeoutError, json.JSONDecodeError) as exc:
            raise HTTPException(502, f"{type(exc).__name__}: {exc}"[:500]) from exc

    return app


if __name__ == "__main__":
    import uvicorn

    # Listens only on the Docker bridge (reachable from the containers, not from the
    # network). CLAUDE_BRIDGE_HOST=127.0.0.1 to use it from the host alone.
    host = os.getenv("CLAUDE_BRIDGE_HOST", "172.17.0.1")
    uvicorn.run(bridge(), host=host, port=int(os.getenv("CLAUDE_BRIDGE_PORT", "8300")))
