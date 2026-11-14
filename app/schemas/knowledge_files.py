"""The Knowledge page's file browser (app/services/knowledge_files.py, routers/knowledge_files.py)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# "ready": searchable with the current embedding model; "outdated": embedded with another one (re-embedded at the next
# sync); "empty": no text to search (e.g. a scanned PDF with no text layer).
FileState = Literal["ready", "outdated", "empty"]


class KnowledgeFileOut(BaseModel):
    id: str
    name: str
    extension: str  # "pdf", "md"…, lower case, for the card's icon
    size_bytes: int
    chunk_count: int
    created_at: datetime
    folder_id: str | None
    state: FileState


class KnowledgeFolderOut(BaseModel):
    id: str
    name: str
    file_count: int


class KnowledgeFolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def tidy(cls, name: str) -> str:
        name = " ".join(name.split())
        if not name or any(c in name for c in "/\\"):
            raise ValueError("A folder name can't be empty or contain / or \\.")
        return name


class KnowledgeMoveIn(BaseModel):
    """Moves files to a folder, or to the top level (`folder_id` None)."""

    file_ids: list[str] = Field(min_length=1, max_length=500)
    folder_id: str | None = None


class KnowledgeDeleteIn(BaseModel):
    """Deletes several of the user's own files at once."""

    file_ids: list[str] = Field(min_length=1, max_length=500)
