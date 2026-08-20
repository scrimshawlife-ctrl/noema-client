from noema_client.adapters.openai_compatible import SYSTEM_PROMPT


def test_openai_system_prompt_spends_cargo_when_hold_is_full():
    lower = SYSTEM_PROMPT.lower()
    assert "do not invent verbs" in lower
    assert "untrusted" in lower
    assert "wait" in lower
    assert "repair" in lower
    assert "free storage" in lower or "hold is full" in lower
    assert "harvest" in lower
