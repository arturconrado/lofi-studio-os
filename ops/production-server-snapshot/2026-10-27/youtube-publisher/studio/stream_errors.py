"""Shared cancellation exception for imported and module-entry transmitters."""

class Stopped(Exception):
    """The operator stopped or replaced the selected transmission."""
