"""Document and Chunk models for the RAG knowledge base (logic: app/services/document_service.py)."""

from sqlalchemy import Column, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base
from app.models._base import ID_LEN, Timestamp, new_id, utcnow


class Document(Base):
    """A knowledge-base file (KNOWLEDGE_DIR), chunked and embedded. A derived index kept in sync with disk
    by document_service; also reachable via upload (app/routers/documents.py).
    """

    __tablename__ = "documents"

    id = Column(String(ID_LEN), primary_key=True, default=new_id)
    # Owner: NULL = shared "global" folder (admin upload, visible to everyone's retrieval, see
    # document_service.retrieve_context); a user id = that user's private upload.
    owner_id = Column(String(ID_LEN), ForeignKey("users.id"), nullable=True)
    # Path relative to KNOWLEDGE_DIR ("global/handbook.pdf", "users/<id>/notes.txt"); unique, and the
    # file's identity for sync (document_service._sync_folder).
    filename = Column(String(500), nullable=False, unique=True)
    # SHA-256 of the file at last ingestion; only a changed hash triggers re-embedding.
    content_hash = Column(String(64), nullable=False)
    # Number of chunks produced (shown in the UI).
    chunk_count = Column(Integer, default=0)
    # File size in bytes, for the per-user RAG quota (app/services/document_upload.py) without re-reading disk.
    size_bytes = Column(Integer, nullable=False, default=0)
    # The embedding model its chunks were embedded with; NULL = embedded before this was recorded. Search uses only
    # chunks from the current model (document_retrieval), and sync re-embeds the others (document_sync).
    embedding_model = Column(String(255), nullable=True)
    created_at = Column(Timestamp, default=utcnow)
    # The owner's folder for it on the Knowledge page (DocumentFolder); NULL = the top level. Only a label: the file
    # stays where it is on disk, so moving it never touches the file or its embeddings.
    folder_id = Column(String(ID_LEN), ForeignKey("document_folders.id"), nullable=True, index=True)

    # lazy="selectin" (see Conversation.messages); cascade delete and document.chunks rely on it.
    chunks = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class DocumentFolder(Base):
    """A folder one user groups their private documents in (app/services/knowledge_files.py). One level, no nesting;
    deleting it moves its documents to the top level."""

    __tablename__ = "document_folders"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_document_folders_owner_name"),)

    id = Column(String(ID_LEN), primary_key=True, default=new_id)
    owner_id = Column(String(ID_LEN), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    created_at = Column(Timestamp, default=utcnow)


class Chunk(Base):
    """One embedded slice of a Document's text, for similarity search."""

    __tablename__ = "chunks"

    id = Column(String(ID_LEN), primary_key=True, default=new_id)
    document_id = Column(String(ID_LEN), ForeignKey("documents.id"), nullable=False)
    text = Column(Text, nullable=False)
    # Embedding vector as raw bytes (serialized float32 numpy array). A BLOB with a brute-force cosine scan
    # (document_service.py) suffices at on-prem scale; see ROADMAP.md for a vector store.
    embedding = Column(LargeBinary, nullable=False)

    # lazy="selectin": retrieve_context reads chunk.document.filename (see Conversation.messages).
    document = relationship("Document", back_populates="chunks", lazy="selectin")
