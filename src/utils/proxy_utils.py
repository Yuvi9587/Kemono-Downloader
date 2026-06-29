"""
Utility helpers for reading proxy settings from a QSettings object.
Used by all downloader threads that live outside the main PostProcessorWorker path.
"""

from ..config.constants import (
    PROXY_ENABLED_KEY, PROXY_HOST_KEY, PROXY_PORT_KEY,
    PROXY_USERNAME_KEY, PROXY_PASSWORD_KEY
)


def get_proxies_from_settings(settings):
    """
    Reads proxy configuration from a QSettings instance and returns a
    ``requests``-compatible proxy dict, or ``None`` if proxy is disabled
    or incomplete.

    The returned dict uses the correct scheme for the selected proxy type:
    - HTTP   → ``http://``
    - SOCKS4 → ``socks4://``
    - SOCKS5 → ``socks5h://``  (hostname resolved through the proxy)

    Args:
        settings: A QSettings instance (``main_app.settings``).

    Returns:
        dict | None: ``{"http": url, "https": url}`` or ``None``.
    """
    enabled = settings.value(PROXY_ENABLED_KEY, False, type=bool)
    if not enabled:
        return None

    host = settings.value(PROXY_HOST_KEY, "", type=str).strip()
    port = settings.value(PROXY_PORT_KEY, "", type=str).strip()
    if not host or not port:
        return None

    proxy_type = settings.value("proxy_type", "HTTP", type=str).upper()
    if proxy_type == "SOCKS5":
        scheme = "socks5h"
    elif proxy_type == "SOCKS4":
        scheme = "socks4"
    else:
        scheme = "http"

    user = settings.value(PROXY_USERNAME_KEY, "", type=str).strip()
    password = settings.value(PROXY_PASSWORD_KEY, "", type=str).strip()

    if user and password:
        proxy_str = f"{scheme}://{user}:{password}@{host}:{port}"
    else:
        proxy_str = f"{scheme}://{host}:{port}"

    return {"http": proxy_str, "https": proxy_str}
