"""
In-memory state for passing search results between Flet pages.
A simple module-level dict is more reliable than page.session,
whose API changed in Flet 0.80+.
"""

_data: dict = {}


def set(key: str, value) -> None:  # noqa: A001
    _data[key] = value


def get(key: str, default=None):
    return _data.get(key, default)


def clear() -> None:
    _data.clear()
