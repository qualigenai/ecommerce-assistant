import uuid
from typing import Any, Dict, List

# TRUST PRINCIPLE: Reliability
#
# Business Purpose:
#     Let a customer's own natural two-turn flow ("find the Trailhead boot"
#     then, separately, "add 1 to my cart") carry a resolved product_id
#     across turns — rather than continuing to demand that a 3B model
#     chain search-then-act perfectly within a single turn, which Day 8's
#     BUG-007 investigation concluded is a genuine capability ceiling at
#     this model size.
#
# Design Decision:
#     A single in-memory dict, keyed by session_id, holding each
#     session's rolling message history. Mocked, same honest pattern as
#     Day 8's _MOCK_CART and _MOCK_ORDERS — no real persistence layer,
#     explicitly out of scope for this project. History is capped at
#     MAX_CONVERSATION_MESSAGES to bound both memory growth and the
#     amount of context sent to the model on every turn.
#
# Benefits:
#     - Turns BUG-007 from "the model must chain perfectly in one turn"
#       into "the model just needs to see its own prior tool result,"
#       a meaningfully easier task
#     - No new persistence infrastructure — consistent with the project's
#       mocked-but-honest pattern for anything beyond the practice
#       project's actual scope
#
# Failure Strategy:
#     History resets on every backend restart — acceptable for a demo,
#     called out explicitly here so it is never mistaken for a durable
#     guarantee. An unknown session_id returns an empty history rather
#     than raising, so a stale or invalid session ID degrades to "start
#     fresh," not an error.
#
# Future Validation:
#     Replace with a real session store (Redis, a database table) and
#     this becomes a live integration point with no change to the
#     function signatures below.
MAX_CONVERSATION_MESSAGES = 20

_CONVERSATIONS: Dict[str, List[Dict[str, Any]]] = {}


def new_session_id() -> str:
    return str(uuid.uuid4())


def get_history(session_id: str) -> List[Dict[str, Any]]:
    if not session_id:
        return []
    return list(_CONVERSATIONS.get(session_id, []))


def set_history(session_id: str, messages: List[Dict[str, Any]]) -> None:
    if not session_id:
        return
    _CONVERSATIONS[session_id] = messages[-MAX_CONVERSATION_MESSAGES:]
