class SaveConnectError(Exception):
    """Base class for SaveConnect errors."""


class AuthenticationError(SaveConnectError):
    """The account's credentials were rejected; logging in again will not help until they change."""
