from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from incilot_agent.claude_code import calls_schema, transcript

TOOLS = [
    {"name": "query_metrics", "parameters": {"type": "object", "properties": {"promql": {}}}},
    {"name": "submit_diagnosis", "parameters": {"type": "object"}},
]


def test_each_call_is_one_of_the_tools_with_its_own_parameters():
    schema = calls_schema(TOOLS, single=False)
    options = schema["properties"]["calls"]["items"]["anyOf"]
    assert [o["properties"]["name"]["const"] for o in options] == [t["name"] for t in TOOLS]
    assert options[0]["properties"]["arguments"] == TOOLS[0]["parameters"]
    assert "maxItems" not in schema["properties"]["calls"]
    assert calls_schema(TOOLS, single=True)["properties"]["calls"]["maxItems"] == 1


def test_the_transcript_keeps_calls_and_their_results_in_order():
    call = {"name": "query_metrics", "args": {"promql": "up"}, "id": "c1"}
    text = transcript(
        [
            HumanMessage("Alert: shop degraded"),
            AIMessage(content="", tool_calls=[call]),
            ToolMessage(content="up = 1", tool_call_id="c1", name="query_metrics"),
        ]
    )
    alert, called, result = (text.index(s) for s in ("Alert", "query_metrics({", "up = 1"))
    assert alert < called < result
    assert text.endswith("Decide the next tool calls.")
