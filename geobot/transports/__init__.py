"""Transport registry. Importing this package registers all built-in transports."""
from .base import REGISTRY, Transport, get, register  # noqa: F401
from . import slack  # noqa: F401  — registers SlackTransport on import
