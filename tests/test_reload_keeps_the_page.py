"""Pages with inner pages (My/Admin settings, Cluster, Stats) keep the open one in the address (#name), so a reload
reopens it instead of the first page."""

from pathlib import Path

JS = Path(__file__).parent.parent / "app" / "static" / "js"


def test_switching_writes_the_page_into_the_address() -> None:
    for name, switch in (("settings.js", "function activateTab"), ("cluster.js", "function activateClusterView"),
                         ("stats.js", "function activateStatsView")):  # fmt: skip
        text = (JS / name).read_text()
        body = text[text.index(switch) : text.index("\n}\n", text.index(switch))]
        assert 'history.replaceState(null, "", `#${name}`)' in body, name


def test_loading_opens_the_page_in_the_address() -> None:
    assert "decodeURIComponent(location.hash.slice(1))" in (JS / "settings.js").read_text()
    cluster = (JS / "cluster.js").read_text()
    assert (
        'activateClusterView(CLUSTER_VIEWS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "overview")'
        in cluster
    )
    assert "STATS_VIEWS.includes(location.hash.slice(1))" in (JS / "stats.js").read_text()


SCRIPTS = (
    "settings_usage_limits.js", "settings_reembed.js", "settings_diffusion_models.js", "settings_reasoning.js",
    "settings_rerank.js", "settings_rerank_models.js", "settings_engine_token.js", "settings_update_source.js",
    "settings_context_window.js", "settings_mcp_servers.js", "settings_images_check.js",
    "settings_matricxon_api_key.js",
    "settings_cache_persistence.js", "settings_cluster_managed.js", "settings_servers.js", "settings_servers_checks.js",
)  # fmt: skip


def test_inner_pages_load_on_their_first_showing() -> None:
    """Parts of a hidden inner page wait for it (page_views.js) instead of loading with the page."""
    for name in SCRIPTS:
        assert "PageViews.whenShown(" in (JS / name).read_text(), name
    assert "PageViews.whileShown(" in (JS / "settings_quorum.js").read_text()  # polls only while shown
    for name, switch in (("settings.js", "function activateTab"), ("cluster.js", "function activateClusterView")):
        text = (JS / name).read_text()
        assert "PageViews.changed()" in text[text.index(switch) : text.index("\n}\n", text.index(switch))], name


def test_settings_restores_the_page_before_loading_anything() -> None:
    text = (JS / "settings.js").read_text()
    assert text.index("(function restoreTabAfterReload()") < text.index("(async function init()")
    assert 'if (savedTab !== "model") loadTabData(savedTab)' in text  # Models: init loads it once


def test_the_helper_loads_first() -> None:
    templates = Path(__file__).parent.parent / "app" / "templates"
    for page, first_user in (("settings.html", "settings.js"), ("cluster.html", "cluster.js")):
        html = (templates / page).read_text()
        assert html.index("/static/js/page_views.js") < html.index(f"/static/js/{first_user}"), page
