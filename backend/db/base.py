"""Declarative base for the Stockroom schema."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class every model inherits from."""
