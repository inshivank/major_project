"""Bounded in-memory conversation memory.

A database-backed store replaces this when sessions must survive restarts.
"""

from __future__ import annotations

from collections import OrderedDict, deque

from backend.config.settings import settings

Turn = dict[str, str]


class SessionStore:
    def __init__(
        self,
        max_sessions: int | None = None,
        max_turns: int | None = None,
    ) -> None:
        self.max_sessions = max_sessions or settings.session_max_sessions
        self.max_turns = max_turns or settings.session_max_turns
        self._sessions: OrderedDict[str, deque[Turn]] = OrderedDict()

    def history(self, session_id: str) -> list[Turn]:
        turns = self._sessions.get(session_id)
        if turns is None:
            return []
        self._sessions.move_to_end(session_id)
        return list(turns)

    def add_turn(self, session_id: str, user_message: str, assistant_message: str) -> None:
        turns = self._sessions.setdefault(session_id, deque(maxlen=self.max_turns))
        self._sessions.move_to_end(session_id)
        turns.append({"role": "user", "content": user_message})
        turns.append({"role": "assistant", "content": assistant_message})

        while len(self._sessions) > self.max_sessions:
            self._sessions.popitem(last=False)

    def __len__(self) -> int:
        return len(self._sessions)
