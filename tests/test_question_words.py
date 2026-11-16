"""The question words come from app/language_data/: the shipped file, plus a server's own languages in
question_words.local.json."""

import json

import pytest

from app.services import question_words
from app.services.question_words import QuestionWords

HEBREW = {"about_an_image": {"he": "תמונה"}, "asks": {"he": "^\\s*(מה)"}}


@pytest.fixture
def words_folder(tmp_path, monkeypatch):
    shipped = json.loads((question_words._FOLDER / "question_words.json").read_text("utf-8"))
    (tmp_path / "question_words.json").write_text(json.dumps(shipped))
    monkeypatch.setattr(question_words, "_FOLDER", tmp_path)
    QuestionWords.pattern.cache_clear()
    yield tmp_path
    QuestionWords.pattern.cache_clear()


def test_the_shipped_file_has_english(words_folder):
    assert QuestionWords.pattern("about_an_image").search("what colour is the car?")
    assert not QuestionWords.pattern("about_an_image").search("tell me a joke")
    assert QuestionWords.pattern("asks").search("why is that")
    assert not QuestionWords.pattern("asks").search("thanks a lot")
    assert not QuestionWords.pattern("asks").search("מה זה")  # no Hebrew in the repo


def test_a_servers_local_file_adds_its_languages(words_folder):
    (words_folder / "question_words.local.json").write_text(json.dumps(HEBREW))
    assert QuestionWords.pattern("asks").search("מה זה")
    assert QuestionWords.pattern("about_an_image").search("בתמונה")
    assert QuestionWords.pattern("asks").search("why is that")  # English still counts
