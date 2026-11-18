"""Keyword part of RAG search (keyword_match.py), PDF text cleaning (pdf_text.py) and word-edge chunking."""

import numpy as np
import pytest

from app.services.chunk_vector_index import ChunkVectorIndex
from app.services.document_extract import chunk_text
from app.services.keyword_match import KeywordMatch
from app.services.pdf_text import PdfText

_TEXTS = [
    "The OWASP Top 10 for LLMs in plain words: prompt injection, supply chain.",
    "Weather today: sunny with light wind.",
    "Cooking pasta takes ten minutes in salted water.",
]


def test_shared_topic_words_raise_a_passage_and_one_word_alone_does_not() -> None:
    keywords = KeywordMatch(_TEXTS)
    owasp = keywords.strength("What are the top 10 OWASP for LLM?")  # "llm" matches "llms"
    assert owasp[0] > 0.5 and owasp[1] == owasp[2] == 0
    assert keywords.strength("What is OWASP, in short?")[0] == 0  # one topic word: no lift
    assert not keywords.strength("What is this and how?").any()  # common words only


def test_words_in_other_scripts_match_with_a_prefix() -> None:
    keywords = KeywordMatch(["\u05d4\u05e9\u05e8\u05ea \u05de\u05d0\u05d5\u05d1\u05d8\u05d7 \u05d4\u05d9\u05d8\u05d1"])
    assert keywords.strength("\u05e9\u05e8\u05ea \u05de\u05d0\u05d5\u05d1\u05d8\u05d7")[0] > 0


@pytest.mark.asyncio
async def test_search_adds_the_keyword_part_to_the_score(db, monkeypatch) -> None:
    from tests.test_rag_chat_settings import _add

    near = await _add(db, "near", [1.0, 0.0])
    index = ChunkVectorIndex()
    await index.refresh(db)
    block = next(iter(index._blocks.values()))
    monkeypatch.setattr(block.keywords, "strength", lambda question: np.ones(1, dtype=np.float32))
    query = np.asarray([0.6, 0.8], dtype=np.float32)
    plain = await index.scored(db, query, None, "emb", 1, refresh=False)
    lifted = await index.scored(db, query, None, "emb", 1, refresh=False, question="any words")
    assert plain[0][0] == lifted[0][0] == near and lifted[0][1] == pytest.approx(plain[0][1] + 0.3)


def test_pdf_text_drops_decoration_and_footers_and_joins_wrapped_lines() -> None:
    topics = ["Install", "Configure", "Run", "Update"]
    pages = [
        f"\u25cf \u25cf \u25cf\n$ Step {n}: {topic}\nthe app\n> {topic} it\nwith {topic} notes.\nexample.com {n} / 4"
        for n, topic in enumerate(topics, start=1)
    ]
    text = PdfText(pages).text()
    assert "\u25cf" not in text and "example.com" not in text and "$" not in text
    assert "Step 1: Install the app\nInstall it with Install notes." in text and "Step 4: Update the app" in text
    assert PdfText(["see owasp-top-10-for-\nllms"]).text() == "see owasp-top-10-for-llms"


def test_chunks_end_between_words() -> None:
    chunks = chunk_text("alpha beta gamma delta epsilon zeta eta theta", size=20, overlap=6)
    assert all(not chunk.startswith(" ") and not chunk.endswith(" ") for chunk in chunks)
    words = set("alpha beta gamma delta epsilon zeta eta theta".split())
    assert all(set(chunk.split()) <= words for chunk in chunks)
