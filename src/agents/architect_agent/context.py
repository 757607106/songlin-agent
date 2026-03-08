"""ArchitectAgent context schema.

No extra fields — behaviour is driven entirely by the system prompt and tools.
"""

from dataclasses import dataclass

from src.agents.common.context import BaseContext


@dataclass(kw_only=True)
class ArchitectContext(BaseContext):
    pass
