"""Shared Qt signal helpers."""

import warnings


def safe_disconnect(signal):
    """Disconnects all slots from a signal; no-op (no PySide RuntimeWarning) when none connected.

    `signal` is a bound SignalInstance (e.g. ``self.button.clicked``).
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            signal.disconnect()
        except (RuntimeError, TypeError):
            pass
