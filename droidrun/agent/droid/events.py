from llama_index.core.workflow import Event
from typing import Any

class CodeActExecuteEvent(Event):
    pass

class CodeActResultEvent(Event):
    success: bool
    reason: str

class ReasoningLogicEvent(Event):
    pass

class FinalizeEvent(Event):
    success: bool
    reason: str
    task: list[dict[str, Any]]
    steps: int = 1

class TaskRunnerEvent(Event):
    pass
