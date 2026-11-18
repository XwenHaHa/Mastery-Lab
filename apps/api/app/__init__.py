"""Mastery Lab 后端应用包。"""

__all__ = ["__version__"]

from .core.config import settings

__version__ = settings.app_version
