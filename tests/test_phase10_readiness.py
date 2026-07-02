from app.services.readiness_service import get_readiness


class DummyDB:
    def execute(self, *_args, **_kwargs):
        raise RuntimeError("database not prepared")


def test_readiness_service_degrades_gracefully():
    payload = get_readiness(DummyDB())
    assert payload["status"] == "needs_attention"
    assert isinstance(payload["summary"], list)
    assert isinstance(payload["demo_scenarios"], list)
    assert payload["next_actions"]
