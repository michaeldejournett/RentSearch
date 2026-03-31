"""
Results page — ranked apartments table with download button.
"""

import datetime
import math
import flet as ft
from pathlib import Path

from src.exporter import build_dataframe, export_to_excel
from src import state


def _is_missing(val) -> bool:
    """True for None, NaN, or empty/whitespace string."""
    if val is None:
        return True
    if isinstance(val, str):
        return not val.strip()
    try:
        return math.isnan(float(val))
    except (TypeError, ValueError):
        return False


def results_page(page: ft.Page) -> ft.Column:

    # ---------------------------------------------------------------- loading
    if state.get("search_loading"):
        frac, msg = state.get("search_status") or (0.0, "Searching...")
        loading_bar = ft.ProgressBar(value=frac, color=ft.Colors.BLUE_600)
        loading_label = ft.Text(msg, size=13, color=ft.Colors.BLUE_700)
        state.set("_loading_bar", loading_bar)
        state.set("_loading_label", loading_label)
        return ft.Column([
            ft.Text("Finding Apartments...", size=22, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Please wait while we search and analyse listings with AI.",
                size=13, color=ft.Colors.GREY_600,
            ),
            loading_bar,
            loading_label,
        ], spacing=16, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    # ---------------------------------------------------------------- error
    err = state.get("search_error")
    if err:
        return ft.Column([
            ft.Icon(ft.Icons.ERROR_OUTLINE, size=48, color=ft.Colors.RED_400),
            ft.Text(err, size=15, color=ft.Colors.RED_700),
            ft.OutlinedButton(
                "Back to Search",
                icon=ft.Icons.ARROW_BACK,
                on_click=lambda e: state.get("navigate_to")("/search"),
            ),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=16)

    # ---------------------------------------------------------------- results
    listings = state.get("search_results") or []
    locations = state.get("search_locations") or []
    criteria = state.get("search_criteria") or []
    min_baths = state.get("search_min_baths")
    max_baths = state.get("search_max_baths")
    min_beds = state.get("search_min_beds")
    max_beds = state.get("search_max_beds")

    listing_names_global: dict = state.get("listing_names") or {}
    df = build_dataframe(listings, locations, criteria,
                         min_baths=min_baths, max_baths=max_baths,
                         min_beds=min_beds, max_beds=max_beds,
                         listing_names=listing_names_global)

    total_found = len(listings)
    shown = len(df)
    filtered = total_found - shown

    def _show_snack(msg: str):
        snack = ft.SnackBar(content=ft.Text(msg), open=True)
        page.overlay.append(snack)
        page.update()

    def download_excel(e):
        excel_bytes = export_to_excel(listings, locations, criteria,
                                      min_baths=min_baths, max_baths=max_baths,
                                      min_beds=min_beds, max_beds=max_beds,
                                      listing_names=state.get("listing_names"))
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"apartment_rankings_{timestamp}.xlsx"
        downloads = Path.home() / "Downloads"
        save_dir = downloads if downloads.exists() else Path.cwd()
        save_path = save_dir / filename
        try:
            save_path.write_bytes(excel_bytes)
            _show_snack(f"Saved: {save_path}")
        except OSError as err_:
            _show_snack(f"Save failed: {err_}")

    def go_search(e):
        nav = state.get("navigate_to")
        if nav:
            nav("/search")

    summary_chips = [
        ft.Chip(
            label=ft.Text(f"{shown} apartments ranked"),
            bgcolor=ft.Colors.BLUE_100,
            leading=ft.Icon(ft.Icons.APARTMENT, size=16),
        ),
    ]
    if filtered > 0:
        summary_chips.append(
            ft.Chip(
                label=ft.Text(f"{filtered} filtered out"),
                bgcolor=ft.Colors.ORANGE_100,
                leading=ft.Icon(ft.Icons.FILTER_ALT, size=16),
            )
        )

    if not listings:
        body = ft.Column([
            ft.Icon(ft.Icons.SEARCH_OFF, size=64, color=ft.Colors.GREY_400),
            ft.Text("No search results yet.", size=18, color=ft.Colors.GREY_600),
            ft.OutlinedButton("New Search", icon=ft.Icons.ARROW_BACK, on_click=go_search),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=16)

    elif df.empty:
        body = ft.Column([
            ft.Icon(ft.Icons.SEARCH_OFF, size=64, color=ft.Colors.GREY_400),
            ft.Text("No results matched your criteria.", size=18, color=ft.Colors.GREY_600),
            ft.Text(
                "Try increasing max distance, broadening price range, or adjusting bath filters.",
                size=13, color=ft.Colors.GREY_500,
            ),
            ft.OutlinedButton("New Search", icon=ft.Icons.ARROW_BACK, on_click=go_search),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=16)

    else:
        # Per-listing custom names — seeded from LLM extraction, editable by user
        listing_names: dict = state.get("listing_names") or {}

        # Pre-populate from extracted apartment_name if user hasn't set one yet
        for listing in listings:
            href = listing.get("href", "")
            if href and href not in listing_names:
                extracted_name = (listing.get("extracted") or {}).get("apartment_name")
                if extracted_name:
                    listing_names[href] = extracted_name
        state.set("listing_names", listing_names)

        def _update_name(href: str, val: str):
            listing_names[href] = val
            state.set("listing_names", listing_names)

        # Distance columns — one per geocoded location
        dist_cols = [
            f"distance_to_{loc.get('label', 'Location')}"
            for loc in locations if loc.get("coords")
        ]
        # Criterion columns — one per user criterion (Score + Note paired as single virtual col)
        crit_display_cols = [f"__crit__{c['text'][:30]}" for c in criteria]

        display_cols = [
            "Rank", "Name", "Address", "Monthly Price ($)", "Bedrooms", "Bathrooms",
            *dist_cols,
            *crit_display_cols,
            "Total Score", "Available Date", "AI Summary", "URL",
        ]
        # "Name" and "__crit__*" are virtual — not in df, handled separately
        available_cols = [
            c for c in display_cols
            if c in df.columns or c == "Name" or c.startswith("__crit__")
        ]

        def _score_color_control(score) -> ft.Container:
            try:
                v = float(score)
                ratio = max(0.0, min(1.0, v / 10.0))
                if ratio < 0.5:
                    r, g = 255, int(255 * ratio * 2)
                else:
                    r, g = int(255 * (1 - ratio) * 2), 255
                color_hex = f"#{r:02X}{g:02X}00"
            except (TypeError, ValueError):
                color_hex = "#AAAAAA"
            return ft.Container(
                content=ft.Text(
                    str(round(float(score), 1)) if not _is_missing(score) else "N/A",
                    weight=ft.FontWeight.BOLD,
                    color=ft.Colors.WHITE,
                    size=13,
                ),
                bgcolor=color_hex,
                border_radius=6,
                padding=ft.Padding.symmetric(horizontal=10, vertical=4),
            )

        # Build df subset excluding virtual columns for iteration
        df_cols = [c for c in available_cols if c != "Name" and not c.startswith("__crit__")]

        def _col_header(col: str) -> str:
            if col.startswith("__crit__"):
                return col[len("__crit__"):]
            return col

        columns = [
            ft.DataColumn(ft.Text(_col_header(c), weight=ft.FontWeight.BOLD))
            for c in available_cols
        ]
        rows = []
        for _, row in df[df_cols].iterrows():
            href = str(row.get("URL", "")) if "URL" in df_cols else ""
            cells = []
            for col in available_cols:
                if col == "Name":
                    cells.append(ft.DataCell(
                        ft.TextField(
                            value=listing_names.get(href, ""),
                            hint_text="Add name...",
                            border=ft.InputBorder.UNDERLINE,
                            width=140,
                            text_size=13,
                            on_change=lambda e, h=href: _update_name(h, e.control.value),
                        )
                    ))
                    continue
                if col.startswith("__crit__"):
                    key = col[len("__crit__"):]
                    score_val = row.get(f"{key} Score") if f"{key} Score" in df.columns else None
                    note_val = row.get(f"{key} Note") if f"{key} Note" in df.columns else None
                    if _is_missing(score_val):
                        cells.append(ft.DataCell(ft.Text("—", size=12)))
                    else:
                        cells.append(ft.DataCell(
                            ft.Column([
                                _score_color_control(score_val),
                                ft.Text(
                                    str(note_val)[:60] if not _is_missing(note_val) else "",
                                    size=10,
                                    color=ft.Colors.GREY_600,
                                    italic=True,
                                ),
                            ], spacing=2, tight=True)
                        ))
                    continue
                val = row[col]
                if col == "Total Score":
                    cells.append(ft.DataCell(_score_color_control(val)))
                elif col == "URL" and val and not _is_missing(val):
                    cells.append(ft.DataCell(
                        ft.TextButton(
                            "View listing",
                            url=str(val),
                            style=ft.ButtonStyle(color=ft.Colors.BLUE_600),
                        )
                    ))
                elif col == "AI Summary":
                    summary_text = str(val)[:300] if not _is_missing(val) else "—"
                    cells.append(ft.DataCell(
                        ft.Text(summary_text, size=11, max_lines=3)
                    ))
                elif col == "Monthly Price ($)":
                    display = f"${val:,.0f}" if not _is_missing(val) else "—"
                    cells.append(ft.DataCell(ft.Text(display, size=13)))
                elif col.startswith("distance_to_"):
                    display = f"{float(val):.1f} mi" if not _is_missing(val) else "—"
                    cells.append(ft.DataCell(ft.Text(display, size=13)))
                else:
                    display = str(val) if not _is_missing(val) else "—"
                    cells.append(ft.DataCell(ft.Text(display, size=13)))
            rows.append(ft.DataRow(cells=cells))

        data_table = ft.DataTable(
            columns=columns,
            rows=rows,
            border=ft.Border.all(1, ft.Colors.BLUE_100),
            border_radius=8,
            heading_row_color=ft.Colors.BLUE_50,
            data_row_max_height=88,
        )

        body = ft.Column([
            ft.Row(summary_chips, wrap=True, spacing=8),
            ft.Row([
                ft.FilledButton(
                    "Download Excel Report",
                    icon=ft.Icons.DOWNLOAD,
                    on_click=download_excel,
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.GREEN_700,
                        color=ft.Colors.WHITE,
                        padding=ft.Padding.symmetric(horizontal=20, vertical=12),
                    ),
                ),
                ft.OutlinedButton(
                    "New Search",
                    icon=ft.Icons.ARROW_BACK,
                    on_click=go_search,
                ),
            ], spacing=12),
            ft.Text(
                "Tap any listing URL to open the original page.",
                size=12, color=ft.Colors.GREY_500, italic=True,
            ),
            ft.Container(
                content=ft.Row([data_table], scroll=ft.ScrollMode.AUTO),
                border=ft.Border.all(1, ft.Colors.GREY_200),
                border_radius=8,
                padding=4,
            ),
        ], spacing=16, scroll=ft.ScrollMode.AUTO)

    return ft.Column(
        controls=[body],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
