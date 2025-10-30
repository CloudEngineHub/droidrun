import asyncio
import contextlib
import contextvars
import io
import logging
import traceback
from asyncio import AbstractEventLoop
from typing import Any, Dict, Optional, Set

from pydantic import BaseModel, ConfigDict

from droidrun.config_manager.safe_execution import (
    create_safe_builtins,
    create_safe_import,
)

logger = logging.getLogger("droidrun")


class ExecuterState(BaseModel):
    """State object for the code executor."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    ui_state: Optional[Any] = None


class SimpleCodeExecutor:
    """
    A simple code executor that runs Python code with state persistence.

    This executor maintains a global and local state between executions,
    allowing for variables to persist across multiple code runs.

    NOTE: not safe for production use! Use with caution.
    """

    def __init__(
        self,
        locals: Dict[str, Any] = None,
        globals: Dict[str, Any] = None,
        tools=None,
        use_same_scope: bool = True,
        safe_mode: bool = False,
        allowed_modules: Optional[Set[str]] = None,
        blocked_modules: Optional[Set[str]] = None,
        allowed_builtins: Optional[Set[str]] = None,
        blocked_builtins: Optional[Set[str]] = None,
    ):
        """
        Initialize the code executor.

        Args:
            locals: Local variables to use in the execution context
            globals: Global variables to use in the execution context
            tools: Dict or list of tools available for execution
            use_same_scope: Whether to use the same scope for globals and locals
            safe_mode: Enable restricted execution (limited builtins/imports)
            allowed_modules: Set of allowed modules (None = allow all, empty = allow none)
            blocked_modules: Set of blocked modules (takes precedence)
            allowed_builtins: Set of allowed builtins (None = allow all, empty = use defaults)
            blocked_builtins: Set of blocked builtins (takes precedence)
        """
        if locals is None:
            locals = {}
        if globals is None:
            globals = {}
        if tools is None:
            tools = {}

        self.safe_mode = safe_mode

        # Setup builtins based on safe mode
        if safe_mode:
            logger.info("🔒 Safe execution mode enabled")
            if allowed_modules is not None and not allowed_modules:
                logger.debug("   No imports allowed (allowed_modules is empty)")
            elif allowed_modules is not None:
                logger.debug(f"   Allowed modules: {allowed_modules}")
            else:
                logger.debug("   All imports allowed (except blocked)")
            logger.debug(f"   Blocked modules: {blocked_modules or 'none'}")
            logger.debug(f"   Blocked builtins: {blocked_builtins or 'none'}")

            # Create restricted builtins
            safe_builtins_dict = create_safe_builtins(
                allowed_builtins, blocked_builtins
            )

            # Add safe import function
            safe_builtins_dict["__import__"] = create_safe_import(
                allowed_modules, blocked_modules
            )

            globals["__builtins__"] = safe_builtins_dict
        else:
            # No restrictions - current behavior
            globals["__builtins__"] = __builtins__

        # Add tools to globals (always allowed, even in safe mode)
        if isinstance(tools, dict):
            logger.debug(
                f"🔧 Initializing SimpleCodeExecutor with tools: {list(tools.keys())}"
            )
            globals.update(tools)
        elif isinstance(tools, list):
            logger.debug(f"🔧 Initializing SimpleCodeExecutor with {len(tools)} tools")
            for tool in tools:
                globals[tool.__name__] = tool
        else:
            raise ValueError("Tools must be a dictionary or a list of functions.")

        self.globals = globals
        self.locals = locals
        self.use_same_scope = use_same_scope

        if self.use_same_scope:
            # If using the same scope, merge globals and locals
            self.globals = self.locals = {
                **self.locals,
                **{k: v for k, v in self.globals.items() if k not in self.locals},
            }

    def _execute_in_thread(
        self, code: str, ui_state: Any, ctx: contextvars.Context = None
    ) -> str:
        """Execute code in thread with context propagation."""
        self.globals["ui_state"] = ui_state

        if ctx is not None:
            from droidrun.agent.utils import async_utils

            async_utils._exec_context = ctx

        stdout = io.StringIO()
        stderr = io.StringIO()

        output = ""
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exec(code, self.globals, self.locals)

            output = stdout.getvalue()
            if stderr.getvalue():
                output += "\n" + stderr.getvalue()

        except Exception as e:
            output = f"Error: {type(e).__name__}: {str(e)}\n"
            output += traceback.format_exc()
        finally:
            if ctx is not None:
                from droidrun.agent.utils import async_utils

                async_utils._exec_context = None

        return output

    async def execute(
        self, state: ExecuterState, code: str, timeout: float = 50.0
    ) -> str:
        """Execute code in thread and return output."""
        loop = asyncio.get_running_loop()
        ui_state = state.ui_state
        ctx = contextvars.copy_context()

        try:
            output = await asyncio.wait_for(
                loop.run_in_executor(
                    None, self._execute_in_thread, code, ui_state, ctx
                ),
                timeout=timeout,
            )
            return output
        except asyncio.TimeoutError:
            return f"Error: Execution timed out after {timeout} seconds"
