"""Personal favorites and the two machine overview layouts."""

import json
from unittest.mock import Mock

from PySide6.QtCore import QPoint, Qt

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.services.local_store import LocalStore
from portal_app.ui.main_window import MainWindow
from portal_app.ui.widgets.login_account_selector import LoginAccountSelector
from portal_app.ui.widgets.workstation_cards import (
    WorkstationCard,
    WorkstationCardsWidget,
    WorkstationListRow,
)


def machines():
    return [
        Workstation("WS-1", "Alpha", "alpha", login_accounts=["DOMAIN\\alice"]),
        Workstation("WS-2", "Beta", "beta"),
    ]


def test_personal_favorites_and_view_survive_reload(tmp_path):
    user = MockUser.create_user()
    store = LocalStore(tmp_path / "portal-state.json")
    store.save_favorite("WS-1", True, user)
    store.save_preferred_login_account("WS-1", "DOMAIN\\alice", user)
    store.save_machine_view("list", user)

    reopened = LocalStore(store.path)
    reopened.load([], user)

    assert reopened.favorite_workstations == ["WS-1"]
    assert reopened.preferred_login_accounts == {"WS-1": "DOMAIN\\alice"}
    assert reopened.machine_view == "list"
    reopened.save_favorite("WS-1", False, user)
    reopened.save_preferred_login_account("WS-1", None, user)
    assert reopened.favorite_workstations == []
    assert reopened.preferred_login_accounts == {}


def test_shared_program_keeps_favorites_separate_on_each_client(
    tmp_path, monkeypatch
):
    shared_state = tmp_path / "SharePoint" / "Client" / "state"
    monkeypatch.setattr(
        "portal_app.services.local_store.default_portal_directory",
        lambda: shared_state,
    )
    user = MockUser.create_user()
    client_a = tmp_path / "Client-A" / "LocalAppData"
    client_b = tmp_path / "Client-B" / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(client_a))
    store_a = LocalStore()
    store_a.save(machines(), user, [])
    store_a.save_favorite("WS-1", True, user)

    monkeypatch.setenv("LOCALAPPDATA", str(client_b))
    store_b = LocalStore()
    store_b.load([], user)
    assert store_b.path == store_a.path
    assert store_b.preferences_path != store_a.preferences_path
    assert store_b.favorite_workstations == []
    store_b.save_favorite("WS-2", True, user)

    monkeypatch.setenv("LOCALAPPDATA", str(client_a))
    reopened_a = LocalStore()
    reopened_a.load([], user)
    assert reopened_a.favorite_workstations == ["WS-1"]
    assert "favorite_workstations" not in json.loads(
        store_a.path.read_text(encoding="utf-8")
    )


def test_favorite_filter_and_view_switch_keep_machine_controls(qtbot):
    widget = WorkstationCardsWidget(machines(), MockUser.create_user())
    qtbot.addWidget(widget)
    widget.set_favorites(["WS-2"])

    assert widget.favorites_filter.isChecked()
    assert [item.workstation.workstation_id for item in widget._cards] == ["WS-2"]
    assert isinstance(widget._cards[0], WorkstationCard)
    widget.set_machine_view("list")
    assert len(widget._cards) == 1
    assert isinstance(widget._cards[0], WorkstationListRow)
    assert widget._cards[0].account_selector.combo.count() > 0
    widget.favorites_filter.setChecked(False)
    assert len(widget._cards) == 2
    assert all(isinstance(item, WorkstationListRow) for item in widget._cards)


def test_empty_favorites_start_with_a_way_to_show_all_machines(qtbot):
    widget = WorkstationCardsWidget(machines(), MockUser.create_user())
    qtbot.addWidget(widget)

    assert widget.favorites_filter.isChecked()
    assert widget._cards == []
    assert "Favoritenfilter ausschalten" in widget.grid.itemAt(0).widget().text()
    widget.favorites_filter.click()
    assert [item.workstation.workstation_id for item in widget._cards] == [
        "WS-1", "WS-2"
    ]


def test_account_popup_star_emits_preference_without_choosing_row(qtbot):
    workstation = machines()[0]
    selector = LoginAccountSelector(workstation, MockUser.create_user())
    qtbot.addWidget(selector)
    selector.resize(320, 90)
    selector.show()
    chosen = []
    preferred = []
    selector.account_selected.connect(lambda *_: chosen.append(True))
    selector.preferred_toggled.connect(lambda _ws, account: preferred.append(account))
    selector.combo.showPopup()
    viewport = selector.combo.view().viewport()
    index = selector.combo.model().index(selector.combo.findData("DOMAIN\\alice"), 0)
    rect = selector.combo.view().visualRect(index)

    qtbot.mouseClick(
        viewport, Qt.LeftButton, pos=QPoint(viewport.width() - 18, rect.center().y())
    )

    assert preferred == ["DOMAIN\\alice"]
    assert chosen == []


def test_account_popup_star_can_be_set_with_keyboard(qtbot):
    selector = LoginAccountSelector(machines()[0], MockUser.create_user())
    qtbot.addWidget(selector)
    selector.show()
    preferred = []
    selector.preferred_toggled.connect(lambda _ws, account: preferred.append(account))
    selector.combo.showPopup()
    selector.combo.view().setCurrentIndex(
        selector.combo.model().index(selector.combo.findData("DOMAIN\\alice"), 0)
    )

    qtbot.keyClick(selector.combo.view(), Qt.Key_D, Qt.ControlModifier)

    assert preferred == ["DOMAIN\\alice"]


def test_dashboard_actions_persist_personal_choices(tmp_path, monkeypatch, qtbot):
    store = LocalStore(tmp_path / "portal-state.json")
    store.save(machines(), MockUser.create_user(), [])
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)

    assert window.overview_view.favorites_filter.isChecked()
    window.overview_view.favorites_filter.click()
    card = next(item for item in window.overview_view._cards
                if item.workstation.workstation_id == "WS-1")
    card.favorite_button.click()
    window.overview_view.favorites_filter.click()
    assert [item.workstation.workstation_id for item in window.overview_view._cards] == [
        "WS-1"
    ]
    window.overview_view.list_button.click()
    row = next(item for item in window.overview_view._cards
               if item.workstation.workstation_id == "WS-1")
    row.account_selector.preferred_toggled.emit(row.workstation, "DOMAIN\\alice")

    reopened = LocalStore(store.path)
    workstations, _, _ = reopened.load([], MockUser.create_user())
    assert reopened.favorite_workstations == ["WS-1"]
    assert reopened.machine_view == "list"
    assert reopened.preferred_login_accounts == {"WS-1": "DOMAIN\\alice"}
    assert workstations[0].selected_login_account == "DOMAIN\\alice"


def test_status_refresh_skips_hidden_calendar_and_admin(tmp_path, monkeypatch, qtbot):
    store = LocalStore(tmp_path / "portal-state.json")
    store.save(machines(), MockUser.create_user(), [])
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)
    calendar_refresh = Mock()
    admin_refresh = Mock()
    monkeypatch.setattr(window.calendar_view, "set_workstations", calendar_refresh)
    monkeypatch.setattr(window.admin_view, "set_workstations", admin_refresh)

    window._refresh_status_views()
    calendar_refresh.assert_not_called()
    admin_refresh.assert_not_called()
    window.nav_buttons[window.PAGE_CALENDAR].click()
    calendar_refresh.assert_called_once_with(window.workstations)


def test_machine_header_is_compact_without_hiding_other_page_titles(
    tmp_path, monkeypatch, qtbot
):
    store = LocalStore(tmp_path / "portal-state.json")
    store.save(machines(), MockUser.create_user(), [])
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)
    window.show()

    assert not window.page_eyebrow.isVisible()
    assert not window.page_subtitle.isVisible()
    assert window.overview_refresh_button.isVisible()
    window.nav_buttons[window.PAGE_CALENDAR].click()
    assert window.page_eyebrow.isVisible()
    assert window.page_subtitle.isVisible()
    assert not window.overview_refresh_button.isVisible()
    window.nav_buttons[window.PAGE_MACHINES].click()
    assert not window.page_eyebrow.isVisible()
    window.on_workstation_selected(window.workstations[0])
    assert window.page_eyebrow.isVisible()
    assert window.page_subtitle.isVisible()
    assert not window.overview_refresh_button.isVisible()
