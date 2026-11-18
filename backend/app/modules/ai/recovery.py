"""Retry database work for an owned CLI outcome, never retry its model request."""

from sqlalchemy.exc import InterfaceError, OperationalError

from app.integrations.call_control import receipt_id

DATABASE_ERRORS = (OperationalError, InterfaceError)


def propagate_database_outage(error):
    if receipt_id() is not None and isinstance(error, DATABASE_ERRORS):
        raise error
