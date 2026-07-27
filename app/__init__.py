"""Centurio — персональная панель быстрого запуска приложений."""

# The one place the version is written by hand. pyproject.toml (version,
# build_version) and installer/centurio.iss (MyAppVersion) can't import Python,
# so a test asserts all four stay equal instead.
__version__ = "1.2.0"
