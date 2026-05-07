from __future__ import annotations


class PythinkerCLIException(Exception):
    """Base exception class for Pythinker CLI."""

    pass


class ConfigError(PythinkerCLIException, ValueError):
    """Configuration error."""

    pass


class AgentSpecError(PythinkerCLIException, ValueError):
    """Agent specification error."""

    pass


class InvalidToolError(PythinkerCLIException, ValueError):
    """Invalid tool error."""

    pass


class SystemPromptTemplateError(PythinkerCLIException, ValueError):
    """System prompt template error."""

    pass


class MCPConfigError(PythinkerCLIException, ValueError):
    """MCP config error."""

    pass


class MCPRuntimeError(PythinkerCLIException, RuntimeError):
    """MCP runtime error."""

    pass
