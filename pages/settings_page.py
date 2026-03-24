"""
Settings page — LLM provider selection, API key management, and default preferences.
Auto-shown on first launch if no provider is configured.
"""

import threading

import flet as ft

from src.config import PROVIDERS, has_api_key, load_config, save_config, test_llm_connection
from src import state


def settings_page(page: ft.Page) -> ft.Column:
    cfg = load_config()
    first_run = not has_api_key()

    # ----------------------------------------------------------- provider state
    provider_names = list(PROVIDERS.keys())
    current_provider = cfg.get("llm_provider", "Anthropic")
    if current_provider not in PROVIDERS:
        current_provider = "Anthropic"
    meta = PROVIDERS[current_provider]

    # ---------------------------------------------------------------- widgets
    provider_dd = ft.Dropdown(
        label="LLM Provider",
        options=[ft.dropdown.Option(p) for p in provider_names],
        value=current_provider,
        width=220,
    )

    # TextField instead of Dropdown — simple .value updates always propagate
    # correctly in Flet; swapping a mounted Dropdown does not.
    model_field = ft.TextField(
        label="Model",
        value=cfg.get("llm_model", meta["default_model"]),
        hint_text=meta["default_model"],
        expand=True,
    )
    model_hint = ft.Text(
        "Available: " + ", ".join(meta["models"]),
        size=12,
        color=ft.Colors.GREY_600,
        italic=True,
    )

    api_key_field = ft.TextField(
        label="API Key",
        password=True,
        can_reveal_password=True,
        value=cfg.get("llm_api_key", ""),
        hint_text=meta.get("key_hint", ""),
        expand=True,
        border_color=ft.Colors.BLUE_400,
        focused_border_color=ft.Colors.BLUE_700,
        visible=meta.get("needs_key", True),
    )
    api_key_hint = ft.Text(
        f"Get your key at {meta.get('key_url', '')}",
        size=12,
        color=ft.Colors.GREY_600,
        italic=True,
        visible=meta.get("needs_key", True),
    )

    base_url_field = ft.TextField(
        label="Base URL (for Ollama / custom endpoints)",
        value=cfg.get("llm_base_url", meta.get("default_base_url", "")),
        hint_text="http://localhost:11434",
        expand=True,
        visible=not meta.get("needs_key", True),
    )

    test_status = ft.Text("", size=13)
    status_text = ft.Text("", size=14)

    # ------------------------------------------------- provider change handler
    def on_provider_change(e):
        p = provider_dd.value
        m = PROVIDERS.get(p, PROVIDERS["Anthropic"])
        needs_key = m.get("needs_key", True)

        model_field.value = m["default_model"]
        model_field.hint_text = m["default_model"]
        model_hint.value = "Available: " + ", ".join(m["models"])

        api_key_field.hint_text = m.get("key_hint", "")
        api_key_field.visible = needs_key
        api_key_hint.value = f"Get your key at {m.get('key_url', '')}"
        api_key_hint.visible = needs_key
        base_url_field.value = m.get("default_base_url", "")
        base_url_field.visible = not needs_key
        test_status.value = ""
        page.update()

    provider_dd.on_change = on_provider_change

    # --------------------------------------------------------- test connection
    def test_connection(e):
        test_status.value = "Testing..."
        test_status.color = ft.Colors.BLUE_600
        page.update()

        p = provider_dd.value
        m = PROVIDERS.get(p, {})
        key = api_key_field.value.strip() if m.get("needs_key", True) else ""
        model = model_field.value.strip() or m.get("default_model", "")
        url = base_url_field.value.strip()

        if m.get("needs_key", True) and not key:
            test_status.value = "Enter an API key first"
            test_status.color = ft.Colors.RED_600
            page.update()
            return

        def _run():
            success, msg = test_llm_connection(p, model, key, url)
            test_status.value = ("✓ " if success else "✗ ") + msg
            test_status.color = ft.Colors.GREEN_700 if success else ft.Colors.RED_600
            page.update()

        threading.Thread(target=_run, daemon=True).start()

    # -------------------------------------------------------------- save
    def save_settings(e):
        try:
            max_dist = int(default_max_distance_field.value or "15")
        except ValueError:
            max_dist = 15

        model = model_field.value.strip() or meta["default_model"]
        new_cfg = {
            **cfg,
            "llm_provider": provider_dd.value,
            "llm_model": model,
            "llm_api_key": api_key_field.value.strip(),
            "llm_base_url": base_url_field.value.strip(),
            "default_city": default_city_field.value.strip(),
            "default_max_distance": max_dist,
        }
        save_config(new_cfg)
        status_text.value = "Settings saved!"
        status_text.color = ft.Colors.GREEN_700
        page.update()

        if first_run:
            nav = state.get("navigate_to")
            if nav:
                nav("/search")

    # --------------------------------------------------------- defaults fields
    default_city_field = ft.TextField(
        label="Default city / area",
        value=cfg.get("default_city", ""),
        hint_text="e.g. Denver, CO",
        expand=True,
    )
    default_max_distance_field = ft.TextField(
        label="Default max distance (miles)",
        value=str(cfg.get("default_max_distance", 15)),
        keyboard_type=ft.KeyboardType.NUMBER,
        width=200,
    )

    # ------------------------------------------------------------------- UI
    setup_banner = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.WHITE),
            ft.Text(
                "Setup required — choose a provider and enter your API key to get started.",
                color=ft.Colors.WHITE,
                size=14,
            ),
        ], spacing=8),
        bgcolor=ft.Colors.BLUE_700,
        padding=ft.Padding.symmetric(horizontal=16, vertical=10),
        border_radius=8,
        visible=first_run,
    )

    return ft.Column(
        controls=[
            setup_banner,
            ft.Text("Settings", size=26, weight=ft.FontWeight.BOLD),
            ft.Divider(),

            ft.Text("LLM Provider", size=18, weight=ft.FontWeight.W_600),
            ft.Row([provider_dd, model_field], spacing=12),
            model_hint,

            ft.Text("API Key", size=18, weight=ft.FontWeight.W_600),
            ft.Row([api_key_field]),
            api_key_hint,
            base_url_field,

            ft.Row([
                ft.Button(
                    "Test Connection",
                    icon=ft.Icons.WIFI_TETHERING,
                    on_click=test_connection,
                    style=ft.ButtonStyle(
                        color=ft.Colors.WHITE,
                        bgcolor=ft.Colors.BLUE_600,
                    ),
                ),
                test_status,
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),

            ft.Divider(),

            ft.Text("Search Defaults", size=18, weight=ft.FontWeight.W_600),
            ft.Text(
                "Pre-fill search fields on startup (optional)",
                size=12, color=ft.Colors.GREY_600,
            ),
            ft.Row([default_city_field, default_max_distance_field], spacing=12),

            ft.Divider(),
            ft.Row([
                ft.FilledButton(
                    "Save Settings",
                    icon=ft.Icons.SAVE,
                    on_click=save_settings,
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.BLUE_700,
                        color=ft.Colors.WHITE,
                    ),
                ),
                status_text,
            ], spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ],
        spacing=16,
        scroll=ft.ScrollMode.AUTO,
    )
