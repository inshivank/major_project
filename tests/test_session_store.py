from backend.orchestrator.session_store import SessionStore


def test_history_add_and_read():
    store = SessionStore(max_sessions=5, max_turns=10)
    store.add_turn("s1", "hi", "hello")

    assert store.history("s1") == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_history_truncates_oldest_turns():
    store = SessionStore(max_sessions=5, max_turns=2)
    for index in range(3):
        store.add_turn("s1", f"q{index}", f"a{index}")

    history = store.history("s1")
    assert len(history) == 2
    assert history[-1]["content"] == "a2"


def test_oldest_session_is_evicted():
    store = SessionStore(max_sessions=2, max_turns=10)
    store.add_turn("s1", "a", "b")
    store.add_turn("s2", "a", "b")
    store.add_turn("s3", "a", "b")

    assert store.history("s1") == []
    assert store.history("s2")
    assert store.history("s3")


def test_unknown_session_has_empty_history():
    assert SessionStore().history("missing") == []
