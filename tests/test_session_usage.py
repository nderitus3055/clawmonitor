from datetime import date

from clawmonitor import session_usage


class _FakeResult:
    def __init__(self, data):
        self.ok = True
        self.data = data
        self.raw_stdout = ""
        self.raw_stderr = ""
        self.returncode = 0


def test_usage_range_dates() -> None:
    start, end = session_usage.usage_range_dates(7, today=date(2026, 3, 19))
    assert start == "2026-03-13"
    assert end == "2026-03-19"


def test_fetch_sessions_usage_range_parses_rows(monkeypatch) -> None:
    def fake_gateway_call(openclaw_bin, method, params=None, timeout_ms=0, log_level="silent"):
        assert method == "sessions.usage"
        assert params["startDate"] == "2026-03-19"
        assert params["endDate"] == "2026-03-19"
        return _FakeResult(
            {
                "updatedAt": 123,
                "sessions": [
                    {
                        "key": "agent:main:a",
                        "agentId": "main",
                        "modelProvider": "openai",
                        "model": "gpt-test",
                        "updatedAt": 100,
                        "usage": {
                            "input": 1000,
                            "output": 50,
                            "cacheRead": 25,
                            "cacheWrite": 5,
                            "totalTokens": 1080,
                            "totalCost": 0.12,
                            "messageCounts": {"total": 6, "errors": 1},
                        },
                    },
                    {
                        "key": "agent:worker:b",
                        "agentId": "worker",
                        "usage": {
                            "input": 10,
                            "output": 20,
                            "cacheRead": 0,
                            "cacheWrite": 0,
                            "totalTokens": 30,
                            "totalCost": 0.01,
                            "messageCounts": {"total": 2, "errors": 0},
                        },
                    },
                ],
            }
        )

    monkeypatch.setattr(session_usage, "gateway_call", fake_gateway_call)
    monkeypatch.setattr(session_usage, "usage_range_dates", lambda days: ("2026-03-19", "2026-03-19"))

    result = session_usage.fetch_sessions_usage_range("openclaw", days=1)

    assert result.range_days == 1
    assert result.updated_at_ms == 123
    assert set(result.sessions_by_key.keys()) == {"agent:main:a", "agent:worker:b"}
    first = result.sessions_by_key["agent:main:a"]
    assert first.totals.input_tokens == 1000
    assert first.totals.output_tokens == 50
    assert first.totals.cache_read_tokens == 25
    assert first.totals.cache_write_tokens == 5
    assert first.totals.total_tokens == 1080
    assert first.totals.total_cost == 0.12
    assert first.totals.message_count == 6
    assert first.totals.error_count == 1
    assert result.agent_totals["main"].total_tokens == 1080
    assert result.agent_totals["worker"].total_tokens == 30
