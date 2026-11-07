"""Alembic initialization script."""

# generic single-database configuration.

from alembic import context
from sqlalchemy import pool

# this is the Alembic Config object, which provides
# the values of the alembic.ini file in Python format.  For Python 2
# support, we'll sometimes use the `compat` module to handle the
# execution of Python expressions.
from alembic.config import Config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if context.config.config_file_name is not None:
    from logging.config import fileConfig
    fileConfig(context.config.config_file_name)

config = context.config

# Autodetect target metadata from models
from app.models import Base
target_metadata = Base.metadata
