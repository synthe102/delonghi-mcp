"""Custom exceptions for the De'Longhi MCP server."""


class DeLonghiMCPError(Exception):
    """Base exception for all De'Longhi MCP errors."""


class AuthenticationError(DeLonghiMCPError):
    """Failed to authenticate with Ayla IoT cloud."""


class NotAuthenticatedError(DeLonghiMCPError):
    """No active authentication session."""


class DeviceNotFoundError(DeLonghiMCPError):
    """Specified device DSN not found."""


class PropertyNotFoundError(DeLonghiMCPError):
    """Device property not found."""
