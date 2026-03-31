"""
Main search page — location entries, qualitative criteria, search parameters.
"""

import datetime
from typing import Optional

import flet as ft

from src.analyzer import analyze_listings_batch, filter_irrelevant_listings
from src.config import has_api_key, load_config
from src.runs import save_run
from src.search import search_listings
from src import state


BATH_OPTIONS = ["Any", "1", "1.5", "2", "2.5", "3", "3+"]


def search_page(page: ft.Page, prefill: dict = None) -> ft.Column:
    cfg = load_config()
    # A prefill dict (from a saved run) overrides config defaults.
    pf_params = (prefill or {}).get("params", {})
    pf_locations = (prefill or {}).get("locations", [])
    pf_criteria = (prefill or {}).get("criteria", [])

    # ------------------------------------------------------------------ state
    locations: list[dict] = []   # [{label, address, weight, coords}]
    criteria: list[dict] = []    # [{text, weight}]

    locations_col = ft.Column(spacing=8)
    criteria_col = ft.Column(spacing=8)

    # Search params — prefill values override config defaults
    city_field = ft.TextField(
        label="City / Area to search (optional)",
        hint_text="e.g. Denver, CO — leave blank to search nationally",
        value=pf_params.get("city", cfg.get("default_city", "")),
        expand=True,
    )
    min_price_field = ft.TextField(
        label="Min price ($/mo)",
        value=str(pf_params.get("min_price", cfg.get("default_min_price", 1000))),
        keyboard_type=ft.KeyboardType.NUMBER,
        width=150,
    )
    max_price_field = ft.TextField(
        label="Max price ($/mo)",
        value=str(pf_params.get("max_price", cfg.get("default_max_price", 3000))),
        keyboard_type=ft.KeyboardType.NUMBER,
        width=150,
    )
    min_beds_dd = ft.Dropdown(
        label="Min beds",
        options=[ft.dropdown.Option(str(i), "Studio" if i == 0 else str(i)) for i in range(6)],
        value=str(pf_params.get("min_beds", cfg.get("default_min_beds", 1))),
        width=110,
    )
    max_beds_dd = ft.Dropdown(
        label="Max beds",
        options=[ft.dropdown.Option(str(i), "Studio" if i == 0 else str(i)) for i in range(6)],
        value=str(pf_params.get("max_beds", cfg.get("default_max_beds", 3))),
        width=110,
    )
    min_baths_dd = ft.Dropdown(
        label="Min baths",
        options=[ft.dropdown.Option(o) for o in BATH_OPTIONS],
        value="Any",
        width=110,
    )
    max_baths_dd = ft.Dropdown(
        label="Max baths",
        options=[ft.dropdown.Option(o) for o in BATH_OPTIONS],
        value="Any",
        width=110,
    )

    # Seed locations/criteria from prefill (strip coords so they get re-geocoded)
    for loc in pf_locations:
        locations.append({
            "label": loc.get("label", ""),
            "address": loc.get("address", ""),
            "weight": loc.get("weight", 5),
            "max_distance": loc.get("max_distance", 15),
            "coords": None,  # will be re-geocoded on search
        })
    for crit in pf_criteria:
        criteria.append({"text": crit.get("text", ""), "weight": crit.get("weight", 5)})

    error_text = ft.Text("", color=ft.Colors.RED_600, size=13, visible=False)

    # ---------------------------------------------------- move-in date range
    earliest_date: list = [None]   # [datetime.date | None]
    latest_date: list = [None]

    def _fmt_date(d) -> str:
        return d.strftime("%b %d, %Y") if d else "Any"

    def _range_label() -> str:
        if earliest_date[0] and latest_date[0]:
            return f"{_fmt_date(earliest_date[0])}  →  {_fmt_date(latest_date[0])}"
        elif earliest_date[0]:
            return f"From {_fmt_date(earliest_date[0])}"
        elif latest_date[0]:
            return f"By {_fmt_date(latest_date[0])}"
        return "Select dates..."

    range_btn_text = ft.Text(_range_label(), size=13, color=ft.Colors.GREY_600)

    def on_range_change(e):
        earliest_date[0] = e.control.start_value
        latest_date[0] = e.control.end_value
        range_btn_text.value = _range_label()
        range_btn_text.color = (
            ft.Colors.BLUE_700 if earliest_date[0] or latest_date[0] else ft.Colors.GREY_600
        )
        page.update()

    range_picker = ft.DateRangePicker(
        first_date=datetime.datetime.now(),
        last_date=datetime.datetime(2028, 12, 31),
        help_text="Select your move-in window",
        field_start_label_text="Earliest",
        field_end_label_text="Latest",
        on_change=on_range_change,
    )
    page.overlay.append(range_picker)

    def open_range_picker(e):
        range_picker.open = True
        page.update()

    # ---------------------------------------------------------- location rows
    def _location_row(idx: int) -> ft.Container:
        loc = locations[idx]

        label_field = ft.TextField(
            label="Label",
            hint_text="e.g. Work",
            value=loc.get("label", ""),
            width=110,
            on_change=lambda e, i=idx: locations[i].update({"label": e.control.value}),
        )
        addr_field = ft.TextField(
            label="Address",
            hint_text="e.g. 123 Main St, Denver CO",
            value=loc.get("address", ""),
            expand=True,
            on_change=lambda e, i=idx: locations[i].update({"address": e.control.value}),
        )
        max_dist_field = ft.TextField(
            label="Preferred max (mi)",
            value=str(loc.get("max_distance", 15)),
            keyboard_type=ft.KeyboardType.NUMBER,
            width=140,
            on_change=lambda e, i=idx: locations[i].update(
                {"max_distance": _safe_float(e.control.value, 15)}
            ),
        )
        weight_slider = ft.Slider(
            min=1, max=10, divisions=9,
            value=loc.get("weight", 5),
            label="{value}/10",
            expand=True,
            on_change=lambda e, i=idx: locations[i].update({"weight": int(e.control.value)}),
        )

        def remove_loc(e, i=idx):
            locations.pop(i)
            _rebuild_locations()

        return ft.Container(
            content=ft.Column([
                ft.Row([label_field, addr_field, max_dist_field], spacing=8),
                ft.Row([
                    ft.Text("Importance:", size=13),
                    weight_slider,
                    ft.IconButton(
                        icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
                        icon_color=ft.Colors.RED_400,
                        tooltip="Remove location",
                        on_click=remove_loc,
                    ),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], spacing=6),
            padding=ft.Padding.all(12),
            border=ft.Border.all(1, ft.Colors.BLUE_100),
            border_radius=8,
            bgcolor=ft.Colors.BLUE_50,
        )

    def _rebuild_locations():
        locations_col.controls = [_location_row(i) for i in range(len(locations))]
        try:
            locations_col.update()
        except Exception:
            page.update()

    def add_location(e):
        locations.append({"label": "", "address": "", "weight": 5, "max_distance": 15, "coords": None})
        _rebuild_locations()

    # ----------------------------------------------------------- criteria rows
    def _criterion_row(idx: int) -> ft.Container:
        crit = criteria[idx]

        text_field = ft.TextField(
            label="What you want",
            hint_text='e.g. "pet friendly", "in-unit laundry"',
            value=crit.get("text", ""),
            expand=True,
            on_change=lambda e, i=idx: criteria[i].update({"text": e.control.value}),
        )
        weight_slider = ft.Slider(
            min=1, max=10, divisions=9,
            value=crit.get("weight", 5),
            label="{value}/10",
            expand=True,
            on_change=lambda e, i=idx: criteria[i].update({"weight": int(e.control.value)}),
        )

        def remove_crit(e, i=idx):
            criteria.pop(i)
            _rebuild_criteria()

        return ft.Container(
            content=ft.Column([
                ft.Row([text_field], spacing=8),
                ft.Row([
                    ft.Text("Importance:", size=13),
                    weight_slider,
                    ft.IconButton(
                        icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
                        icon_color=ft.Colors.RED_400,
                        tooltip="Remove criterion",
                        on_click=remove_crit,
                    ),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], spacing=6),
            padding=ft.Padding.all(12),
            border=ft.Border.all(1, ft.Colors.GREEN_100),
            border_radius=8,
            bgcolor=ft.Colors.GREEN_50,
        )

    def _rebuild_criteria():
        criteria_col.controls = [_criterion_row(i) for i in range(len(criteria))]
        try:
            criteria_col.update()
        except Exception:
            page.update()

    def add_criterion(e):
        criteria.append({"text": "", "weight": 5})
        _rebuild_criteria()

    # --------------------------------------------------------------- search
    def _set_progress(frac: float, msg: str):
        state.set("search_status", (frac, msg))
        bar = state.get("_loading_bar")
        lbl = state.get("_loading_label")
        if bar is not None and lbl is not None:
            bar.value = frac
            lbl.value = msg
            async def _push():
                page.update()
            try:
                page.run_task(_push)
            except Exception:
                pass

    def _safe_float(val: str, default: float) -> float:
        try:
            return float(val) if val else default
        except (ValueError, TypeError):
            return default

    def _parse_bath(val: str) -> Optional[float]:
        if val in (None, "Any"):
            return None
        if val == "3+":
            return 3.0
        try:
            return float(val)
        except ValueError:
            return None

    def _run_search():
        from src.analyzer import _call_llm

        cfg_now = load_config()
        api_key = cfg_now.get("llm_api_key", "").strip()
        model = cfg_now.get("llm_model", "claude-sonnet-4-6")
        base_url = cfg_now.get("llm_base_url", "")

        city = city_field.value.strip()
        if not city and locations:
            addrs = [loc["address"] for loc in locations if loc.get("address", "").strip()]
            if addrs and api_key:
                try:
                    from src.search import _ddg_search
                    _set_progress(0.02, "Looking up your locations to infer search area...")
                    snippets = []
                    for addr in addrs[:3]:
                        try:
                            results = _ddg_search(f"{addr} city location", max_results=3)
                            for r in results[:2]:
                                body = r.get("body", "")[:200]
                                if body:
                                    snippets.append(f"'{addr}': {body}")
                        except Exception:
                            pass
                    context = "\n".join(snippets) if snippets else ""
                    loc_list = "\n".join(f"- {a}" for a in addrs)
                    prompt = (
                        f"A user wants to rent near these locations:\n{loc_list}\n\n"
                        + (f"Web search context:\n{context}\n\n" if context else "")
                        + "What single city or metro area should be searched for apartments? "
                        "Reply with ONLY the city and state, e.g. \"Omaha, NE\". No explanation."
                    )
                    city = _call_llm(model, prompt, api_key, base_url, max_tokens=20).strip().strip('"\'')
                except Exception:
                    city = ""
            if city:
                city_field.value = city
                page.update()

        try:
            min_price = int(min_price_field.value or "0")
            max_price = int(max_price_field.value or "99999")
            min_beds = int(min_beds_dd.value or "0")
            max_beds = int(max_beds_dd.value or "5")
        except ValueError:
            state.set("search_loading", False)
            state.set("search_error", "Invalid number in search parameters.")
            nav = state.get("navigate_to")
            if nav:
                nav("/results")
            return

        min_baths = _parse_bath(min_baths_dd.value)
        max_baths = _parse_bath(max_baths_dd.value)

        # Build effective criteria — prepend move-in date if set
        effective_criteria = list(criteria)
        if earliest_date[0] or latest_date[0]:
            parts = []
            if earliest_date[0]:
                parts.append(f"from {_fmt_date(earliest_date[0])}")
            if latest_date[0]:
                parts.append(f"by {_fmt_date(latest_date[0])}")
            effective_criteria = [
                {"text": "Available for move-in " + " ".join(parts), "weight": 8}
            ] + effective_criteria

        # Ensure every location has a unique non-empty label before geocoding/column naming
        seen_labels: set[str] = set()
        for i, loc in enumerate(locations):
            label = loc.get("label", "").strip()
            if not label:
                label = f"Location {i + 1}"
            # Deduplicate: append index if label already used
            base = label
            counter = 2
            while label in seen_labels:
                label = f"{base} {counter}"
                counter += 1
            seen_labels.add(label)
            loc["label"] = label

        try:
            # Pre-resolve all location addresses with LLM before geocoding.
            # Sending all addresses together lets the LLM cross-reference them
            # (e.g. "Offutt AFB" + "Farnam St" → both in Omaha, NE).
            locs_with_addr = [loc for loc in locations if loc.get("address", "").strip()]
            if locs_with_addr and api_key:
                from src.search import _ddg_search
                _set_progress(0.03, "Resolving location addresses...")
                try:
                    # Gather DDG context for each address
                    all_snippets: list[str] = []
                    for loc in locs_with_addr:
                        try:
                            results = _ddg_search(f"{loc['address']} location address", max_results=3)
                            for r in results[:2]:
                                body = r.get("body", "")[:250]
                                if body:
                                    all_snippets.append(f"[{loc['address']}]: {body}")
                        except Exception:
                            pass

                    addr_list = "\n".join(
                        f"{i+1}. {loc['address']}" for i, loc in enumerate(locs_with_addr)
                    )
                    city_ctx = f"The user is searching for apartments in: {city}\n" if city else ""
                    snippets_ctx = ("Web search context:\n" + "\n".join(all_snippets) + "\n\n") if all_snippets else ""
                    prompt = (
                        f"{city_ctx}"
                        f"A user provided these location addresses. Some may be incomplete or ambiguous.\n"
                        f"{addr_list}\n\n"
                        f"{snippets_ctx}"
                        "For each address, return a fully-qualified geocodable address (street, city, state) "
                        "using all available context to infer the correct city/state. "
                        "Use the other addresses as clues — they are likely in the same metro area.\n"
                        "Reply with ONLY a numbered list matching the input, one per line. "
                        "Example:\n1. 2201 SAC Blvd, Bellevue, NE\n2. 3333 Farnam St, Omaha, NE"
                    )
                    response = _call_llm(model, prompt, api_key, base_url, max_tokens=200).strip()
                    # Parse numbered lines: "1. address"
                    import re as _re
                    resolved_map: dict[int, str] = {}
                    for line in response.splitlines():
                        m = _re.match(r"^\s*(\d+)\.\s+(.+)$", line)
                        if m:
                            resolved_map[int(m.group(1))] = m.group(2).strip().strip('"\'')
                    for i, loc in enumerate(locs_with_addr):
                        resolved = resolved_map.get(i + 1, "")
                        if resolved:
                            loc["resolved_address"] = resolved
                except Exception:
                    pass

            _set_progress(0.05, "Geocoding your important locations...")
            from src.geocode import geocode_address as _geocode
            import time as _time
            import re as _re2

            def _ask_llm_for_coordinates(label: str, original: str) -> Optional[str]:
                """Ask LLM (with DDG context) for a precise geocodable address.
                Searches DDG specifically for coordinates/address of the location.
                """
                if not api_key:
                    return None
                try:
                    from src.search import _ddg_search
                    results = _ddg_search(
                        f'"{original}" exact address coordinates location', max_results=5
                    )
                    snippets = "\n".join(
                        f"- {r.get('body', '')[:300]}" for r in results[:4] if r.get("body")
                    )
                    prompt = (
                        f'What is the precise street address (including city and state) for: "{original}"?\n'
                        f'Web search results:\n{snippets}\n\n'
                        f'Reply with ONLY a single geocodable address string, e.g. "2201 SAC Blvd, Bellevue, NE 68113".\n'
                        f'If it is a landmark or base, give the actual street address of its main gate or headquarters.\n'
                        f'No explanation.'
                    )
                    result = _call_llm(model, prompt, api_key, base_url, max_tokens=60).strip().strip('"\'')
                    return result if result else None
                except Exception:
                    return None

            def _geocode_with_fallbacks(label: str, resolved: str, original: str) -> Optional[tuple]:
                """Try geocoding with progressively specific to broad address forms."""
                candidates = []
                if resolved and resolved.lower() != original.lower():
                    candidates.append(resolved)
                candidates.append(original)

                # Try each candidate; if all fail, ask the LLM specifically for coordinates
                for attempt in candidates:
                    _set_progress(0.06, f"Geocoding '{label}' as: {attempt}")
                    _time.sleep(1.1)
                    coords = _geocode(attempt)
                    if coords:
                        print(f"[GEOCODE] '{label}' → '{attempt}' → {coords}")
                        return coords
                    print(f"[GEOCODE] '{label}' failed for '{attempt}'")

                # All candidates failed — ask LLM specifically for the street address
                _set_progress(0.07, f"Looking up precise address for '{label}'...")
                llm_addr = _ask_llm_for_coordinates(label, original)
                if llm_addr and llm_addr.lower() not in {c.lower() for c in candidates}:
                    print(f"[GEOCODE] '{label}' LLM suggested: '{llm_addr}'")
                    _time.sleep(1.1)
                    coords = _geocode(llm_addr)
                    if coords:
                        print(f"[GEOCODE] '{label}' → '{llm_addr}' → {coords}")
                        return coords
                    # Last resort: city,state only from LLM address
                    parts = [p.strip() for p in llm_addr.split(",")]
                    if len(parts) >= 2:
                        city_state = ", ".join(parts[-2:])
                        _time.sleep(1.1)
                        coords = _geocode(city_state)
                        if coords:
                            print(f"[GEOCODE] '{label}' city fallback → '{city_state}' → {coords}")
                            return coords

                print(f"[GEOCODE] '{label}' could not be geocoded — distances will be unavailable")
                return None

            for loc in locations:
                if not loc.get("address", "").strip():
                    loc["coords"] = None
                    continue
                loc["coords"] = _geocode_with_fallbacks(
                    loc.get("label", "?"),
                    loc.get("resolved_address", ""),
                    loc["address"],
                )

            _set_progress(0.3, f"Searching for apartments{' in ' + city if city else ''}...")
            listings = search_listings(
                city, min_price, max_price, min_beds, max_beds,
                progress_callback=_set_progress,
                api_key=api_key,
                model=model,
                base_url=base_url,
            )

            if not listings:
                state.set("search_loading", False)
                state.set("search_error",
                    "No listings found. Try a broader area or wider price range.")
                async def _nav_no_results():
                    fn = state.get("navigate_to")
                    if fn:
                        fn("/results")
                page.run_task(_nav_no_results)
                return

            listings = filter_irrelevant_listings(
                listings, city, min_price, max_price, min_beds, max_beds,
                api_key=api_key, model=model, base_url=base_url,
                progress_callback=_set_progress,
            )

            listings = analyze_listings_batch(
                listings, effective_criteria, api_key,
                progress_callback=_set_progress,
                model=model,
                base_url=base_url,
            )

            _set_progress(0.97, "Geocoding apartment addresses for distance scoring...")
            from src.geocode import geocode_address
            for listing in listings:
                # Only geocode real street addresses — never use listing title as fallback,
                # which can geocode to the wrong city and produce wildly wrong distances.
                extracted_addr = (listing.get("extracted") or {}).get("address")
                coords = geocode_address(extracted_addr) if extracted_addr else None
                if coords:
                    print(f"[APT-GEOCODE] '{extracted_addr}' → {coords}")
                listing["apt_coords"] = coords

        except Exception as exc:  # noqa: BLE001
            state.set("search_loading", False)
            state.set("search_error", f"Search failed: {exc}")
            async def _nav_error():
                fn = state.get("navigate_to")
                if fn:
                    fn("/results")
            page.run_task(_nav_error)
            return

        # Auto-save this run to history
        try:
            save_run(
                city=city,
                min_price=min_price,
                max_price=max_price,
                min_beds=min_beds,
                max_beds=max_beds,
                min_baths=min_baths,
                max_baths=max_baths,
                locations=list(locations),
                criteria=effective_criteria,
                listings=listings,
                listing_names=state.get("listing_names"),
            )
        except Exception:  # noqa: BLE001
            pass  # never let a save failure break the search result

        state.set("search_results", listings)
        state.set("search_locations", list(locations))
        state.set("search_criteria", effective_criteria)
        state.set("search_min_beds", min_beds)
        state.set("search_max_beds", max_beds)
        state.set("search_min_baths", min_baths)
        state.set("search_max_baths", max_baths)
        state.set("search_loading", False)
        state.set("search_error", None)

        _set_progress(1.0, "Done!")
        async def _nav_done():
            fn = state.get("navigate_to")
            if fn:
                fn("/results")
        page.run_task(_nav_done)

    def start_search(e):
        if not has_api_key():
            error_text.value = "No API key found — go to Settings first."
            error_text.visible = True
            page.update()
            return
        error_text.visible = False
        page.update()

        state.set("search_loading", True)
        state.set("search_error", None)
        state.set("search_status", (0.0, "Starting..."))
        state.set("_loading_bar", None)
        state.set("_loading_label", None)

        nav = state.get("navigate_to")
        if nav:
            nav("/results")

        page.run_thread(_run_search)

    find_btn = ft.FilledButton(
        "Find Apartments",
        icon=ft.Icons.SEARCH,
        on_click=start_search,
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.BLUE_700,
            color=ft.Colors.WHITE,
            padding=ft.Padding.symmetric(horizontal=24, vertical=14),
        ),
    )

    # ------------------------------------------------------------------- UI
    column_content = ft.Column(
        controls=[
            ft.Text("Find Your Apartment", size=26, weight=ft.FontWeight.BOLD),
            ft.Divider(),

            ft.Text("Search Area", size=18, weight=ft.FontWeight.W_600),
            ft.Row([city_field], vertical_alignment=ft.CrossAxisAlignment.END),
            ft.Row(
                [min_price_field, max_price_field, min_beds_dd, max_beds_dd,
                 min_baths_dd, max_baths_dd],
                spacing=10,
                wrap=True,
            ),
            ft.Divider(),

            ft.Text("Move-in Date Range", size=18, weight=ft.FontWeight.W_600),
            ft.Text(
                "Optional — the AI will score listings by availability within your window.",
                size=12, color=ft.Colors.GREY_600,
            ),
            ft.OutlinedButton(
                content=ft.Row(
                    [ft.Icon(ft.Icons.DATE_RANGE, size=16), range_btn_text],
                    spacing=8, tight=True,
                ),
                on_click=open_range_picker,
            ),
            ft.Divider(),

            ft.Text("Important Locations", size=18, weight=ft.FontWeight.W_600),
            ft.Text(
                "Optional — leave empty to rank by criteria only.",
                size=12, color=ft.Colors.GREY_600,
            ),
            locations_col,
            ft.OutlinedButton(
                "+ Add Location",
                icon=ft.Icons.ADD_LOCATION_ALT,
                on_click=add_location,
            ),
            ft.Divider(),

            ft.Text("What I'm Looking For", size=18, weight=ft.FontWeight.W_600),
            ft.Text(
                "Describe features in plain English — the AI will score each listing against them.",
                size=12, color=ft.Colors.GREY_600,
            ),
            criteria_col,
            ft.OutlinedButton(
                "+ Add Criteria",
                icon=ft.Icons.ADD_TASK,
                on_click=add_criterion,
            ),
            ft.Divider(),

            error_text,
            find_btn,
        ],
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )

    # If a re-run was requested from History, auto-start the search once rendered
    if state.get("search_autostart"):
        state.set("search_autostart", False)
        async def _auto_start():
            start_search(None)
        page.run_task(_auto_start)

    return column_content

