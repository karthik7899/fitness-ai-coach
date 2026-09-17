"""Coverage for the parts of the agent layer that run without an API key."""

from google.genai import types

from app.agent.coach import SYSTEM_INSTRUCTIONS, declarations, merge_stream_parts
from app.agent.tools import HANDLERS, TOOL_SPECS


def test_every_spec_has_a_handler():
    for spec in TOOL_SPECS:
        assert spec["name"] in HANDLERS
        assert set(spec) == {"name", "description", "parameters"}
        assert spec["parameters"]["type"] == "object"


def test_specs_convert_to_gemini_declarations():
    declared = declarations()
    assert len(declared) == len(TOOL_SPECS)
    for decl, spec in zip(declared, TOOL_SPECS, strict=True):
        assert decl.name == spec["name"]
        assert decl.parameters_json_schema == spec["parameters"]


def test_request_config_serialises_with_schemas_intact():
    """The closest check on request shape that runs without a key."""
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTIONS,
        tools=[types.Tool(function_declarations=declarations())],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    wire = config.model_dump(mode="json", exclude_none=True)
    declared = wire["tools"][0]["function_declarations"]

    assert len(declared) == len(TOOL_SPECS)
    assert wire["automatic_function_calling"]["disable"] is True

    daily = next(d for d in declared if d["name"] == "get_daily_metrics")
    schema = daily["parameters_json_schema"]
    assert schema["required"] == ["start_date", "end_date"]
    assert "steps" in schema["properties"]["metrics"]["items"]["enum"]


def test_streamed_text_fragments_are_merged():
    merged = merge_stream_parts(
        [types.Part(text="Your squat "), types.Part(text="is up "), types.Part(text="4kg.")]
    )
    assert len(merged) == 1
    assert merged[0].text == "Your squat is up 4kg."


def test_function_calls_survive_merging_and_split_the_text():
    merged = merge_stream_parts(
        [
            types.Part(text="Let me "),
            types.Part(text="check."),
            types.Part(function_call=types.FunctionCall(name="get_training_load", args={})),
            types.Part(text="Done."),
        ]
    )
    assert [p.text for p in merged] == ["Let me check.", None, "Done."]
    assert merged[1].function_call.name == "get_training_load"


def test_thought_signature_parts_are_never_merged_away():
    """Gemini needs signatures echoed back verbatim; merging would drop them."""
    merged = merge_stream_parts(
        [
            types.Part(text="a"),
            types.Part(text="b", thought_signature=b"sig"),
            types.Part(text="c"),
        ]
    )
    assert len(merged) == 3
    assert merged[1].thought_signature == b"sig"


def test_thinking_parts_are_not_merged_into_the_reply():
    merged = merge_stream_parts(
        [types.Part(text="reasoning", thought=True), types.Part(text="answer")]
    )
    assert len(merged) == 2
    assert merged[0].thought is True
    assert merged[1].text == "answer"


def test_history_round_trips_through_jsonb():
    """What _persist writes must reload as an equivalent Content."""
    original = types.Content(
        role="model",
        parts=[
            types.Part(text="Checking."),
            types.Part(
                function_call=types.FunctionCall(
                    name="get_workout", args={"d": "2026-01-01"}
                )
            ),
        ],
    )
    stored = [p.model_dump(mode="json", exclude_none=True) for p in original.parts]
    restored = types.Content(
        role="model", parts=[types.Part.model_validate(p) for p in stored]
    )
    assert restored.parts[0].text == "Checking."
    assert restored.parts[1].function_call.name == "get_workout"
    assert restored.parts[1].function_call.args == {"d": "2026-01-01"}
