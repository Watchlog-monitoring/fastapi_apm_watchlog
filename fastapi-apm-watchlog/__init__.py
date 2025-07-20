# fastapi_watchlog_apm/__init__.py

__version__ = "0.2.1"

from .instrument import instrument

__all__ = [
    "instrument",
    "__version__",
]
