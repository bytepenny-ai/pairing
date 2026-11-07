"""Tests for the pure helpers of instance_proxy_http.py. The ASGI middleware (instance_proxy.py) needs a real
running instance, verified live (real processes, real curl) as the note-slot/scroll/multi-instance features
were, not via a TestClient/ASGI pattern this repo doesn't use.
"""

from app.services.instance_proxy_http import (
    content_length,
    filter_request_headers,
    filter_response_headers,
    is_exempt,
    job_target_index,
)


def test_is_exempt_matches_every_pinned_to_primary_prefix():
    for path in (
        "/api/settings/instances",
        "/api/settings/database",
        "/api/settings/database/test-connection",
        "/api/settings/proxy-mode",
        "/api/settings/llamacpp",
        "/api/settings/llamacpp/start",
        "/api/settings/sdcpp",
        "/api/settings/sdcpp/start",
        "/api/settings/matricxon",
        "/api/settings/matricxon/start",
        "/health",
        "/static/js/app.js",
    ):
        assert is_exempt(path), path


def test_is_exempt_false_for_ordinary_routes():
    for path in ("/api/chat/abc123/stream", "/", "/api/documents/upload", "/api/conversations"):
        assert not is_exempt(path), path


def test_job_target_index_parses_a_prefixed_job_id():
    assert job_target_index("/api/documents/upload/2-" + "a" * 32) == 2
    assert job_target_index("/api/documents/upload/0-" + "f" * 32) == 0


def test_job_target_index_none_for_non_matching_paths():
    assert job_target_index("/api/documents/upload") is None
    assert job_target_index("/api/documents/upload/" + "a" * 32) is None
    assert job_target_index("/api/conversations/abc") is None


def test_filter_request_headers_keeps_the_browsers_host_and_adds_forwarded_for():
    # The sibling's CSRF check compares Origin with Host: it must be the browser's, not "localhost:<port>".
    raw = [(b"Host", b"10.0.0.5:8000"), (b"Cookie", b"session=abc"), (b"Accept", b"*/*")]
    result = dict(filter_request_headers(raw, "203.0.113.5"))
    assert result["Host"] == "10.0.0.5:8000"
    assert result["X-Forwarded-Host"] == "10.0.0.5:8000"
    assert result["Cookie"] == "session=abc"
    assert result["Accept"] == "*/*"
    assert result["X-Forwarded-For"] == "203.0.113.5"


def test_filter_request_headers_drops_a_client_supplied_forwarded_for():
    """Security regression: a client's own X-Forwarded-For must never reach a sibling, not just have the trusted one
    appended after it. Starlette's Headers on the receiving side could return the *forged* value first (or a
    dict-building implementation let it win), letting a client rotate it to bypass auth_service.resolve_client_ip's
    loopback-trust check and the per-IP login rate limiter.
    """
    raw = [(b"X-Forwarded-For", b"203.0.113.9"), (b"Cookie", b"session=abc")]
    result = filter_request_headers(raw, "127.0.0.1")
    values = [v for k, v in result if k.lower() == "x-forwarded-for"]
    assert values == ["127.0.0.1"]


def test_filter_response_headers_drops_hop_by_hop_headers():
    raw = [("Content-Length", "42"), ("Transfer-Encoding", "chunked"), ("Connection", "keep-alive"), ("X-Custom", "y")]
    result = filter_response_headers(raw)
    names = {k.decode("latin-1").lower() for k, _ in result}
    assert names == {"x-custom"}


def _scope(*headers: tuple[str, str]) -> dict:
    return {"headers": [(k.encode(), v.encode()) for k, v in headers]}


def test_content_length_of_a_request_without_body_is_zero():
    # A plain GET (e.g. /login) has neither header: no body, so it can be retried on another instance.
    assert content_length(_scope(("host", "x"))) == 0


def test_content_length_reads_the_header_and_unknown_when_chunked_or_bad():
    assert content_length(_scope(("Content-Length", "42"))) == 42
    assert content_length(_scope(("transfer-encoding", "chunked"))) is None
    assert content_length(_scope(("content-length", "abc"))) is None
