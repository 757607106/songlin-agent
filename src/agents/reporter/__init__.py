__all__ = ["SqlReporterAgent"]


def __getattr__(name: str):
    if name == "SqlReporterAgent":
        from .graph import SqlReporterAgent

        return SqlReporterAgent
    raise AttributeError(name)
