"""
RentSearch — AI-powered apartment finder
Entry point for Flet desktop + web app.

Run locally:  flet run main.py
Run as web:   flet run --web --port 8080 main.py
Build .exe:   flet build windows
Build Linux:  flet build linux
"""

import flet as ft

from pages.results_page import results_page
from pages.search_page import search_page
from pages.settings_page import settings_page  # rebuilt on each visit
from src.config import has_api_key
from src import state


NAV_ROUTES = ["/search", "/results", "/settings"]
NAV_ICONS = [
    (ft.Icons.SEARCH_OUTLINED, ft.Icons.SEARCH, "Search"),
    (ft.Icons.LIST_ALT_OUTLINED, ft.Icons.LIST_ALT, "Results"),
    (ft.Icons.SETTINGS_OUTLINED, ft.Icons.SETTINGS, "Settings"),
]


def main(page: ft.Page):
    page.title = "RentSearch"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(
        color_scheme_seed=ft.Colors.BLUE,
        visual_density=ft.VisualDensity.COMFORTABLE,
    )
    page.window.width = 1000
    page.window.height = 800
    page.window.min_width = 480
    page.window.min_height = 600
    page.fonts = {}
    page.padding = 0

    # ── content area ────────────────────────────────────────────────────────
    content_area = ft.Container(expand=True, padding=24)

    # ── build search content once (preserves form state) ────────────────────
    search_content = search_page(page)
    # settings and results are rebuilt on each visit

    # ── custom bottom nav ────────────────────────────────────────────────────
    nav_items: list[ft.Container] = []
    current_route: list[str] = ["/search"]  # mutable ref

    def _nav_item(idx: int) -> ft.Container:
        icon_off, icon_on, label = NAV_ICONS[idx]
        route = NAV_ROUTES[idx]

        is_active = current_route[0] == route

        return ft.Container(
            expand=True,
            ink=True,
            on_click=lambda e, r=route: navigate_to(r),
            padding=ft.Padding.symmetric(vertical=8),
            content=ft.Column(
                [
                    ft.Icon(
                        icon_on if is_active else icon_off,
                        color=ft.Colors.BLUE_700 if is_active else ft.Colors.GREY_600,
                        size=24,
                    ),
                    ft.Text(
                        label,
                        size=11,
                        color=ft.Colors.BLUE_700 if is_active else ft.Colors.GREY_600,
                        weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=2,
                tight=True,
            ),
        )

    def _rebuild_nav():
        nav_row.controls = [_nav_item(i) for i in range(len(NAV_ROUTES))]

    nav_row = ft.Row(spacing=0, alignment=ft.MainAxisAlignment.SPACE_AROUND)
    _rebuild_nav()

    nav_bar = ft.Container(
        content=nav_row,
        bgcolor=ft.Colors.WHITE,
        border=ft.Border.only(top=ft.BorderSide(1, ft.Colors.GREY_200)),
        height=64,
    )

    # ── navigation function ──────────────────────────────────────────────────
    def navigate_to(route: str):
        nonlocal search_content
        current_route[0] = route

        if route == "/results":
            content_area.content = results_page(page)
        elif route == "/settings":
            content_area.content = settings_page(page)
        else:
            content_area.content = search_content

        _rebuild_nav()
        page.update()

    # Store navigate_to so page modules can call it
    state.set("navigate_to", navigate_to)

    # ── app bar ──────────────────────────────────────────────────────────────
    app_bar = ft.AppBar(
        title=ft.Text("RentSearch"),
        bgcolor=ft.Colors.BLUE_700,
        color=ft.Colors.WHITE,
        actions=[
            ft.IconButton(
                icon=ft.Icons.SETTINGS,
                icon_color=ft.Colors.WHITE,
                tooltip="Settings",
                on_click=lambda e: navigate_to("/settings"),
            ),
        ],
    )

    # ── root view ────────────────────────────────────────────────────────────
    root_view = ft.View(
        route="/",
        controls=[
            app_bar,
            ft.Column(
                [
                    content_area,
                    nav_bar,
                ],
                expand=True,
                spacing=0,
            ),
        ],
        padding=0,
    )

    page.views.clear()
    page.views.append(root_view)

    # First launch: go to settings if no API key, else search
    start_route = "/search" if has_api_key() else "/settings"
    navigate_to(start_route)


if __name__ == "__main__":
    ft.run(main, assets_dir="assets")
