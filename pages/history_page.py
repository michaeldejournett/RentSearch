"""
History page — browse, load, re-run, and delete past search runs.
"""

import datetime

import flet as ft

from src.runs import list_runs, load_run, delete_run
from src import state


def _fmt_date(iso: str) -> str:
    try:
        dt = datetime.datetime.fromisoformat(iso)
        return dt.strftime("%b %d, %Y  %I:%M %p")
    except Exception:  # noqa: BLE001
        return iso


def history_page(page: ft.Page) -> ft.Column:

    runs = list_runs()
    container = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)

    def _show_snack(msg: str, color=ft.Colors.BLUE_700):
        snack = ft.SnackBar(
            content=ft.Text(msg, color=ft.Colors.WHITE),
            bgcolor=color,
            open=True,
        )
        page.overlay.append(snack)
        page.update()

    def _load_run(run_id: str):
        data = load_run(run_id)
        if not data:
            _show_snack("Could not load run.", ft.Colors.RED_600)
            return
        # Restore all search state from the saved run
        state.set("search_results", data.get("listings", []))
        state.set("search_locations", data.get("locations", []))
        state.set("search_criteria", data.get("criteria", []))
        p = data.get("params", {})
        state.set("search_min_beds", p.get("min_beds"))
        state.set("search_max_beds", p.get("max_beds"))
        state.set("search_min_baths", p.get("min_baths"))
        state.set("search_max_baths", p.get("max_baths"))
        state.set("listing_names", data.get("listing_names", {}))
        state.set("search_loading", False)
        state.set("search_error", None)
        nav = state.get("navigate_to")
        if nav:
            nav("/results")

    def _rerun(run_id: str):
        data = load_run(run_id)
        if not data:
            _show_snack("Could not load run.", ft.Colors.RED_600)
            return
        state.set("search_prefill", data)
        state.set("search_autostart", True)
        nav = state.get("navigate_to")
        if nav:
            nav("/search")

    def _delete(run_id: str, card: ft.Container):
        def confirm(e):
            dlg.open = False
            page.update()
            if delete_run(run_id):
                container.controls.remove(card)
                page.update()
                _show_snack("Run deleted.")
            else:
                _show_snack("Delete failed.", ft.Colors.RED_600)

        def cancel(e):
            dlg.open = False
            page.update()

        dlg = ft.AlertDialog(
            title=ft.Text("Delete this run?"),
            content=ft.Text("This cannot be undone."),
            actions=[
                ft.TextButton("Cancel", on_click=cancel),
                ft.FilledButton(
                    "Delete",
                    on_click=confirm,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.RED_600,
                                         color=ft.Colors.WHITE),
                ),
            ],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _run_card(run: dict) -> ft.Container:
        card = ft.Container()  # forward ref for delete closure

        card.content = ft.Column([
            ft.Row([
                ft.Column([
                    ft.Text(run["label"], size=15, weight=ft.FontWeight.W_600),
                    ft.Text(
                        f"{_fmt_date(run['created_at'])}  ·  "
                        f"{run['listing_count']} listings",
                        size=12, color=ft.Colors.GREY_600,
                    ),
                ], expand=True, spacing=2),
                ft.IconButton(
                    icon=ft.Icons.DELETE_OUTLINE,
                    icon_color=ft.Colors.RED_400,
                    tooltip="Delete",
                    on_click=lambda e, rid=run["run_id"]: _delete(rid, card),
                ),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([
                ft.FilledButton(
                    "Load Results",
                    icon=ft.Icons.OPEN_IN_NEW,
                    on_click=lambda e, rid=run["run_id"]: _load_run(rid),
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.BLUE_700,
                        color=ft.Colors.WHITE,
                    ),
                ),
                ft.OutlinedButton(
                    "Re-run Search",
                    icon=ft.Icons.REPLAY,
                    on_click=lambda e, rid=run["run_id"]: _rerun(rid),
                ),
            ], spacing=10),
        ], spacing=10)
        card.padding = ft.Padding.all(16)
        card.border = ft.Border.all(1, ft.Colors.BLUE_100)
        card.border_radius = 10
        card.bgcolor = ft.Colors.WHITE
        return card

    if not runs:
        container.controls.append(
            ft.Row(
                [ft.Column([
                    ft.Icon(ft.Icons.HISTORY, size=64, color=ft.Colors.GREY_300),
                    ft.Text("No saved runs yet.", size=16, color=ft.Colors.GREY_500),
                    ft.Text(
                        "Completed searches are saved automatically.",
                        size=13, color=ft.Colors.GREY_400,
                    ),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12)],
                alignment=ft.MainAxisAlignment.CENTER,
            )
        )
    else:
        for run in runs:
            container.controls.append(_run_card(run))

    return ft.Column(
        controls=[
            ft.Text("Search History", size=24, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Load past results instantly or re-run a search with the same parameters.",
                size=13, color=ft.Colors.GREY_600,
            ),
            ft.Divider(),
            container,
        ],
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )
