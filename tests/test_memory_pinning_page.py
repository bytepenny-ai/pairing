"""Admin settings > Inference > Memory pinning: the page, its scripts, and that it moves only while shown."""

from pathlib import Path

import pytest

from app.routers import pages
from tests.test_settings_pages import _request

JS = Path(__file__).parent.parent / "app" / "static" / "js"


@pytest.mark.asyncio
async def test_admin_page_has_the_memory_pinning_panel_and_scripts(db, admin_user):
    html = (await pages.admin_settings_page(_request(admin_user.id), db=db)).body.decode()
    for element in (
        "tab-memory-pinning",
        "pin-tiles",
        "pin-grid",
        "pin-tooltip",
        "pin-node",
        "pin-by-model",
        "pin-motion",
        "pin-status",
        "pin-body",
        "pin-engine-off",
    ):
        assert f'id="{element}"' in html
    order = [html.index(f"/static/js/memory_pin_{name}.js") for name in ("common", "grid", "live", "panel", "page")]
    assert order == sorted(order) and html.index("/static/js/settings.js") < order[0]


@pytest.mark.asyncio
async def test_user_settings_has_no_memory_pinning(db, user):
    html = (await pages.settings_page(_request(user.id), db=db)).body.decode()
    assert "tab-memory-pinning" not in html and "memory_pin_" not in html


def test_it_animates_and_polls_only_while_shown() -> None:
    page = (JS / "memory_pin_page.js").read_text()
    grid = (JS / "memory_pin_grid.js").read_text()
    settings = (JS / "settings.js").read_text()
    assert 'memoryPinPage.setActive(name === "memory-pinning")' in settings
    assert "clearInterval(this._timer)" in page and "document.hidden" in page
    assert "prefers-reduced-motion" in grid and "requestAnimationFrame" in grid
    assert "setInterval" not in grid  # frames only while dots move or pins load


def test_files_stay_compact() -> None:
    for name in ("common", "grid", "live", "panel", "page"):
        assert len((JS / f"memory_pin_{name}.js").read_text().splitlines()) <= 250
