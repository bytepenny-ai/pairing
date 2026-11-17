"""Admin settings: how chats use the Knowledge base."""

from pydantic import BaseModel, Field

from app.config import RAG_CHECK_SOURCES, RAG_MIN_SIMILARITY_MAX, RAG_MIN_SIMILARITY_MIN, RAG_SOURCE_MIN_SIMILARITY


class RagChatSetting(BaseModel):
    # Lowest cosine similarity to the question a passage needs; 0 keeps the closest ones always.
    min_similarity: float = Field(ge=RAG_MIN_SIMILARITY_MIN, le=RAG_MIN_SIMILARITY_MAX)
    # Excerpts stay with their message in later turns (prompt cache), or go with that turn only.
    keep_excerpts: bool
    # After a reply: list only documents the answer is this close to (an extra embedding round); off lists all.
    check_sources: bool = RAG_CHECK_SOURCES
    source_min_similarity: float = Field(
        default=RAG_SOURCE_MIN_SIMILARITY, ge=RAG_MIN_SIMILARITY_MIN, le=RAG_MIN_SIMILARITY_MAX
    )
