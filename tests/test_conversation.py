"""Unit tests for ConversationDirector (Phase 1 coverage of existing API).

HIGH-015 user-scoping is verified by tests in test_session_isolation.py after the
Authentication/Runtime repairs land.
"""

from __future__ import annotations

import pytest

from orchestrator.conversation import (
    ConversationDirector,
    ConversationState,
    InvalidConversationTransitionError,
)


class TestConversationSessionLifecycle:
    def setup_method(self) -> None:
        self.director = ConversationDirector()
        self.session_id = "sess-test-1"

    def test_create_session_initial_state(self) -> None:
        session = self.director.create_session(self.session_id)
        assert session.state is ConversationState.ACTIVE
        assert session.history == []
        assert session.total_tokens == 0

    def test_create_duplicate_raises(self) -> None:
        self.director.create_session(self.session_id)
        with pytest.raises(ValueError):
            self.director.create_session(self.session_id)

    def test_empty_session_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            self.director.create_session("")


class TestStateTransitions:
    def setup_method(self) -> None:
        self.director = ConversationDirector()
        self.session_id = "sess-state-1"
        self.director.create_session(self.session_id)

    def test_active_to_completed_allowed(self) -> None:
        self.director.transition_state(self.session_id, ConversationState.COMPLETED)
        assert self.director.get_metadata(self.session_id)["state"] == "completed"

    def test_active_to_failed_allowed(self) -> None:
        self.director.transition_state(self.session_id, ConversationState.FAILED)
        assert self.director.get_metadata(self.session_id)["state"] == "failed"

    def test_active_to_waiting_allowed(self) -> None:
        self.director.transition_state(self.session_id, ConversationState.WAITING)
        assert self.director.get_metadata(self.session_id)["state"] == "waiting"

    def test_terminal_to_active_blocked(self) -> None:
        self.director.transition_state(self.session_id, ConversationState.COMPLETED)
        with pytest.raises(InvalidConversationTransitionError):
            self.director.transition_state(self.session_id, ConversationState.ACTIVE)

    def test_completed_state_sets_expiration(self) -> None:
        self.director.transition_state(self.session_id, ConversationState.COMPLETED)
        session = self.director.get_session(self.session_id)
        assert session is not None
        assert session.expires_at is not None

    def test_unknown_session_raises(self) -> None:
        with pytest.raises(ValueError):
            self.director.transition_state("unknown", ConversationState.ACTIVE)


class TestHistoryManagement:
    def setup_method(self) -> None:
        self.director = ConversationDirector()
        self.session_id = "sess-hist-1"
        self.director.create_session(self.session_id)

    def test_add_turn_appends(self) -> None:
        self.director.add_turn(self.session_id, "user", "Hello", token_count=2)
        history = self.director.get_history(self.session_id)
        assert len(history) == 1
        assert history[0] == {"role": "user", "content": "Hello"}

    def test_invalid_role_rejected(self) -> None:
        with pytest.raises(ValueError):
            self.director.add_turn(self.session_id, "system", "oops")

    def test_non_string_content_rejected(self) -> None:
        with pytest.raises(TypeError):
            self.director.add_turn(self.session_id, "user", 12345)  # type: ignore[arg-type]

    def test_history_capped_at_max_history_size(self) -> None:
        for i in range(ConversationDirector.MAX_HISTORY_SIZE + 5):
            self.director.add_turn(self.session_id, "user", f"msg-{i}")
        history = self.director.get_history(self.session_id)
        assert len(history) == ConversationDirector.MAX_HISTORY_SIZE
        assert history[-1]["content"] == f"msg-{ConversationDirector.MAX_HISTORY_SIZE + 4}"

    def test_token_total_tracked(self) -> None:
        self.director.add_turn(self.session_id, "user", "A", token_count=5)
        self.director.add_turn(self.session_id, "assistant", "B", token_count=8)
        metadata = self.director.get_metadata(self.session_id)
        assert metadata["total_tokens"] == 13


@pytest.mark.asyncio
async def test_conversation_director_db_sync_round_trip(tmp_path: Any) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    import core.models

    db_path = tmp_path / "test_conv.db"
    test_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with test_engine.begin() as conn:
        await conn.run_sync(lambda sc: core.models.User.__table__.create(sc))
        await conn.run_sync(lambda sc: core.models.ConversationSessionRecord.__table__.create(sc))
        await conn.run_sync(lambda sc: core.models.ConversationMessageRecord.__table__.create(sc))

    session_factory = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

    director = ConversationDirector()
    director.create_session("sess-db-1", owner_email="user@test.com")
    director.add_turn("sess-db-1", "user", "Test question", token_count=4)
    director.add_turn("sess-db-1", "assistant", "Test answer", token_count=6)

    async with session_factory() as db_session:
        await director.persist_session_to_db("sess-db-1", db_session)

    new_director = ConversationDirector()
    async with session_factory() as db_session:
        loaded = await new_director.load_session_from_db("sess-db-1", db_session)

    assert loaded is not None
    assert loaded.session_id == "sess-db-1"
    assert loaded.owner_email == "user@test.com"
    assert len(loaded.history) == 2
    assert loaded.total_tokens == 10

    await test_engine.dispose()

