from finance_agent.parsing import strip_code_fence


def test_strip_code_fence_removes_json_fence():
    raw = '```json\n{"tool": "compute_totals", "args": {}}\n```'
    assert strip_code_fence(raw) == '{"tool": "compute_totals", "args": {}}'


def test_strip_code_fence_removes_plain_fence():
    raw = '```\n{"a": 1}\n```'
    assert strip_code_fence(raw) == '{"a": 1}'


def test_strip_code_fence_leaves_unfenced_text_alone():
    raw = '{"a": 1}'
    assert strip_code_fence(raw) == '{"a": 1}'
