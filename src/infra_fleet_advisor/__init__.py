from importlib.metadata import PackageNotFoundError, version

try:
    ADVISOR_VERSION = version("infra-fleet-advisor")
except PackageNotFoundError:
    # Editable/uninstalled checkout (e.g. running from a source tree without
    # `uv sync`) — pyproject.toml stays the single source of truth otherwise.
    ADVISOR_VERSION = "0.0.0+unknown"
