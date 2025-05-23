"""
DroidAgent - A wrapper class that coordinates the planning and execution of tasks
to achieve a user's goal on an Android device.
"""

import asyncio
import logging
import time
from typing import Dict, Any, List, Tuple

from llama_index.core.base.llms.types import ChatMessage
from llama_index.core.llms.llm import LLM
from llama_index.core.memory import ChatMemoryBuffer
from droidrun.agent.codeact import CodeActAgent
from droidrun.agent.planner import PlannerAgent, TaskManager
from droidrun.agent.utils.executer import SimpleCodeExecutor
from droidrun.tools import load_tools

logger = logging.getLogger("droidrun")

class DroidAgent:
    """
    A wrapper class that coordinates between PlannerAgent (creates plans) and 
    CodeActAgent (executes tasks) to achieve a user's goal.
    """
    
    def __init__(
        self, 
        goal: str,
        llm: LLM,
        max_steps: int = 15,
        timeout: int = 1000,
        max_retries: int = 3,
        reasoning: bool = True,
        enable_tracing: bool = False,
        debug: bool = False,
        device_serial: str = None,
        **kwargs
    ):
        """
        Initialize the DroidAgent wrapper.
        
        Args:
            goal: The user's goal or command to execute
            llm: The language model to use for both agents
            tools_instance: An instance of the Tools class
            tool_list: Dictionary of available tools
            max_steps: Maximum number of steps for both agents
            timeout: Timeout for agent execution in seconds
            max_retries: Maximum number of retries for failed tasks
            reasoning: Whether to use the PlannerAgent for complex reasoning (True) 
                      or send tasks directly to CodeActAgent (False)
            enable_tracing: Whether to enable Arize Phoenix tracing
            debug: Whether to enable verbose debug logging
            device_serial: Target Android device serial number
            **kwargs: Additional keyword arguments to pass to the agents
        """
        # Setup global tracing first if enabled
        if enable_tracing:
            try:
                from llama_index.core import set_global_handler
                set_global_handler("arize_phoenix")
                logger.info("🔍 Arize Phoenix tracing enabled globally")
            except ImportError:
                logger.warning("⚠️ Arize Phoenix package not found, tracing disabled")
                enable_tracing = False
        
        self.goal = goal
        self.llm = llm
        self.max_steps = max_steps
        self.timeout = timeout
        self.max_retries = max_retries
        self.task_manager = TaskManager()
        self.reasoning = reasoning
        self.debug = debug
        self.device_serial = device_serial
        
        # Store trajectory steps and callback
        self.trajectory_steps = []
        self.trajectory_callback = self._handle_trajectory_step
        
        logger.info("🤖 Initializing DroidAgent wrapper...")

        tool_list, tools_instance = load_tools(serial=device_serial)
        
        self.tools_instance = tools_instance
        self.tool_list = tool_list
        
        # Ensure remember tool is in the tool_list if available
        if hasattr(tools_instance, 'remember') and 'remember' not in tool_list:
            logger.debug("📝 Adding 'remember' tool to the available tools")
            tool_list['remember'] = tools_instance.remember
        
        # Create code executor
        logger.debug("🔧 Initializing Code Executor...")
        loop = asyncio.get_event_loop()
        self.executor = SimpleCodeExecutor(
            loop=loop,
            locals={},
            tools=tool_list,
            globals={"__builtins__": __builtins__}
        )
        
        # Create memory buffer for the planning agent if reasoning is enabled
        if self.reasoning:
            self.planning_memory = ChatMemoryBuffer.from_defaults(llm=llm)
        
        # Create CodeActAgent
        logger.info("🧠 Initializing CodeAct Agent...")
        self.codeact_agent = CodeActAgent(
            llm=llm,
            code_execute_fn=self.executor.execute,
            available_tools=tool_list.values(),
            tools=tools_instance,
            max_steps=999999, 
            debug=debug,
            timeout=timeout,
            trajectory_callback=self.trajectory_callback
        )
        
        if self.reasoning:
            logger.info("📝 Initializing Planner Agent...")
            self.planner_agent = PlannerAgent(
                goal=goal,
                llm=llm,
                agent=self.codeact_agent, 
                tools_instance=tools_instance,
                timeout=timeout,
                max_retries=max_retries,
                debug=debug,
                trajectory_callback=self.trajectory_callback
            )
            
            # Give task manager to the planner
            self.planner_agent.task_manager = self.task_manager
        else:
            logger.debug("🚫 Planning disabled - will execute tasks directly with CodeActAgent")
            self.planner_agent = None
        
        logger.info("✅ DroidAgent initialized successfully.")
    
    async def _handle_trajectory_step(self, step):
        """
        Callback to handle trajectory steps from both agents.
        This adds the step to our trajectory_steps list and yields it if needed.
        
        Args:
            step: A trajectory step dictionary with metadata
        """
        # Add metadata about current time
        step["timestamp"] = time.time()
        
        # Add to trajectory
        self.trajectory_steps.append(step)
        
        # Log for debugging if needed
        logger.debug(f"📝 Trajectory step: {step['type']} (step {step['step']})")
            
    def get_trajectory(self):
        """
        Get the current trajectory.
        
        Returns:
            List of trajectory steps
        """
        return self.trajectory_steps.copy()
    
    async def _get_plan_from_planner(self) -> List[Dict]:
        """
        Get a plan (list of tasks) from the PlannerAgent.
        
        Returns:
            List of task dictionaries
        """
        logger.info("📋 Planning steps to accomplish the goal...")
        
        # Create system and user messages
        system_msg = ChatMessage(role="system", content=self.planner_agent.system_prompt)
        user_msg = ChatMessage(role="user", content=self.planner_agent.user_prompt)
        
        # Check if we have task history to add to the prompt
        task_history = ""
        # Use the persistent task history methods to get ALL completed and failed tasks
        completed_tasks = self.task_manager.get_all_completed_tasks()
        failed_tasks = self.task_manager.get_all_failed_tasks()
        
        # Show any remembered information in task history
        remembered_info = ""
        if hasattr(self.tools_instance, 'memory') and self.tools_instance.memory:
            remembered_info = "\n### Remembered Information:\n"
            for idx, item in enumerate(self.tools_instance.memory, 1):
                remembered_info += f"{idx}. {item}\n"
        
        if completed_tasks or failed_tasks or remembered_info:
            task_history = "### Task Execution History:\n"
            
            if completed_tasks:
                task_history += "✅ Completed Tasks:\n"
                for task in completed_tasks:
                    task_history += f"- {task['description']}\n"

            if failed_tasks:
                task_history += "\n❌ Failed Tasks:\n"
                for task in failed_tasks:
                    failure_reason = task.get('failure_reason', 'Unknown reason')
                    task_history += f"- {task['description']} (Failed: {failure_reason})\n"
            
            if remembered_info:
                task_history += remembered_info
                
            # Add a reminder to use this information
            task_history += "\n⚠️ Please use the above information in your planning. For example, if specific dates or locations were found, include them explicitly in your next tasks instead of just referring to 'the dates' or 'the location'.\n"
            
            # Append task history to user prompt
            user_msg = ChatMessage(
                role="user", 
                content=f"{self.planner_agent.user_prompt}\n\n{task_history}\n\nPlease consider the above task history and discovered information when creating your next plan. Incorporate specific data (dates, locations, etc.) directly into tasks rather than referring to them generally. Remember that previously completed or failed tasks will not be repeated."
            )
        
        # Create message list
        messages = [system_msg, user_msg]
        logger.debug(f"Sending {len(messages)} messages to planner: {[msg.role for msg in messages]}")
        
        # Get response from LLM
        llm_response = await self.planner_agent._get_llm_response(messages)
        code, thoughts = self.planner_agent._extract_code_and_thought(llm_response.message.content)

        # Add trajectory step for plan generation
        if self.trajectory_callback:
            trajectory_step = {
                "type": "planner_plan_generation",
                "step": self.planner_agent.steps_counter,
                "thoughts": thoughts,
                "code": code,
                "timestamp": time.time()
            }
            await self._handle_trajectory_step(trajectory_step)
        
        # Execute the planning code (which should call set_tasks)
        if code:
            try:
                planning_tools = {
                    "set_tasks": self.task_manager.set_tasks,
                    "add_task": self.task_manager.add_task,
                    "get_all_tasks": self.task_manager.get_all_tasks,
                    "clear_tasks": self.task_manager.clear_tasks,
                    "complete_goal": self.task_manager.complete_goal
                }
                planning_executor = SimpleCodeExecutor(
                    loop=asyncio.get_event_loop(),
                    globals={},
                    locals={},
                    tools=planning_tools
                )
                result = await planning_executor.execute(code)

                # Add trajectory step for plan execution
                if self.trajectory_callback:
                    trajectory_step = {
                        "type": "planner_plan_execution",
                        "step": self.planner_agent.steps_counter,
                        "result": result,
                        "timestamp": time.time()
                    }
                    await self._handle_trajectory_step(trajectory_step)

            except Exception as e:
                logger.error(f"Error executing planning code: {e}")
                # If there's an error, create a simple default task
                self.task_manager.set_tasks([f"Achieve the goal: {self.goal}"])
        
        # Get and display the tasks
        tasks = self.task_manager.get_all_tasks()
        if tasks:
            logger.info("📝 Plan created:")
            for i, task in enumerate(tasks, 1):
                if task["status"] == self.task_manager.STATUS_PENDING:
                    logger.info(f"  {i}. {task['description']}")

            # Add trajectory step for final plan
            if self.trajectory_callback:
                trajectory_step = {
                    "type": "planner_final_plan",
                    "step": self.planner_agent.steps_counter,
                    "tasks": [task["description"] for task in tasks if task["status"] == self.task_manager.STATUS_PENDING],
                    "timestamp": time.time()
                }
                await self._handle_trajectory_step(trajectory_step)
        else:
            logger.warning("No tasks were generated in the plan")
            
        return tasks

    async def _execute_task_with_codeact(self, task: Dict) -> Tuple[bool, str]:
        """
        Execute a single task using the CodeActAgent.
        
        Args:
            task: Task dictionary with description and status
            
        Returns:
            Tuple of (success, reason)
        """
        task_description = task["description"]
        logger.info(f"🔧 Executing task: {task_description}")
        
        # Update task status
        task["status"] = self.task_manager.STATUS_ATTEMPTING
        
        # Run the CodeActAgent
        try:
            # Reset the tools finished flag before execution
            self.tools_instance.finished = False
            self.tools_instance.success = None
            self.tools_instance.reason = None
            
            # Execute the CodeActAgent with the task description as input
            # Pass input as a keyword argument, not as a dictionary
            result = await self.codeact_agent.run(input=task_description)
            
            # Check if the tools instance was marked as finished by the 'complete' function
            if self.tools_instance.finished:
                if self.tools_instance.success:
                    task["status"] = self.task_manager.STATUS_COMPLETED
                    logger.debug(f"Task completed successfully: {self.tools_instance.reason}")
                    return True, self.tools_instance.reason or "Task completed successfully"
                else:
                    task["status"] = self.task_manager.STATUS_FAILED
                    task["failure_reason"] = self.tools_instance.reason or "Task failed without specific reason"
                    logger.warning(f"Task failed: {task['failure_reason']}")
                    return False, self.tools_instance.reason or "Task failed without specific reason"
            
            # If tools instance wasn't marked as finished, check the result directly
            if result and isinstance(result, dict) and "success" in result and result["success"]:
                task["status"] = self.task_manager.STATUS_COMPLETED
                logger.debug(f"Task completed with result: {result}")
                return True, result.get("reason", "Task completed successfully")
            else:
                failure_reason = result.get("reason", "Unknown failure") if isinstance(result, dict) else "Task execution failed"
                task["status"] = self.task_manager.STATUS_FAILED
                task["failure_reason"] = failure_reason
                logger.warning(f"Task failed: {failure_reason}")
                return False, failure_reason
                
        except Exception as e:
            logger.error(f"Error during task execution: {e}")
            if self.debug:
                import traceback
                logger.error(traceback.format_exc())
            task["status"] = self.task_manager.STATUS_FAILED
            task["failure_reason"] = f"Error: {str(e)}"
            return False, f"Error: {str(e)}"

    async def run(self) -> Dict[str, Any]:
        """
        Main execution loop that coordinates between planning and execution.
        Yields trajectory steps during execution.
        
        Returns:
            Dict containing the execution result and complete trajectory
        """
        logger.info(f"🚀 Running DroidAgent to achieve goal: {self.goal}")
        
        step_counter = 0
        retry_counter = 0
        overall_success = False
        final_message = ""
        
        # Clear trajectory from any previous runs
        self.trajectory_steps = []
        
        try:
            # If reasoning is disabled, directly execute the goal as a single task in CodeActAgent
            if not self.reasoning:
                logger.info(f"🔄 Direct execution mode - executing goal: {self.goal}")
                # Create a simple task for the goal
                task = {
                    "description": self.goal,
                    "status": self.task_manager.STATUS_PENDING
                }
                
                # Execute the task directly with CodeActAgent
                success, reason = await self._execute_task_with_codeact(task)
                
                return {
                    "success": success,
                    "reason": reason,
                    "steps": 1,
                    "task_history": [task],  # Single task history
                    "trajectory": self.trajectory_steps
                }
            
            # Standard reasoning mode with planning
            while step_counter < self.max_steps:
                step_counter += 1
                logger.debug(f"Planning step {step_counter}/{self.max_steps}")
                
                # 1. Get a plan from the planner
                tasks = await self._get_plan_from_planner()
                
                if self.task_manager.task_completed:
                    # Task is marked as complete by the planner
                    logger.info(f"✅ Goal completed: {self.task_manager.message}")
                    overall_success = True
                    final_message = self.task_manager.message
                    break
                
                if not tasks:
                    logger.warning("No tasks generated by planner")
                    final_message = "Planner did not generate any tasks"
                    break
                
                # 2. Execute each task in the plan sequentially
                for task in tasks:
                    if task["status"] == self.task_manager.STATUS_PENDING:
                        # Reset the CodeActAgent's step counter for this task
                        self.codeact_agent.steps_counter = 0
                        
                        # Execute the task
                        success, reason = await self._execute_task_with_codeact(task)
                        
                        # Update task info with detailed result for the planner
                        task_idx = tasks.index(task)
                        result_info = {
                            "execution_details": reason,
                            "step_executed": step_counter,
                            "codeact_steps": self.codeact_agent.steps_counter
                        }
                        
                        # Only update if not already updated in _execute_task_with_codeact
                        if success:
                            self.task_manager.update_status(
                                task_idx, 
                                self.task_manager.STATUS_COMPLETED, 
                                result_info
                            )
                            logger.info(f"✅ Task completed: {task['description']}")
                        
                        if not success:
                            # Store detailed failure information if not already set
                            if "failure_reason" not in task:
                                self.task_manager.update_status(
                                    task_idx,
                                    self.task_manager.STATUS_FAILED,
                                    {"failure_reason": reason, **result_info}
                                )
                            
                            # Handle retries
                            if retry_counter < self.max_retries:
                                retry_counter += 1
                                logger.info(f"Retrying... ({retry_counter}/{self.max_retries})")
                                # Next iteration will generate a new plan based on current state
                                break
                            else:
                                logger.error(f"Max retries exceeded for task")
                                final_message = f"Failed after {self.max_retries} retries. Reason: {reason}"
                                return {
                                    "success": False, 
                                    "reason": final_message,
                                    "trajectory": self.trajectory_steps
                                }
                
                # Reset retry counter for new task sequence
                retry_counter = 0
                
                # Check if all tasks are completed
                all_completed = all(task["status"] == self.task_manager.STATUS_COMPLETED for task in tasks)
                if all_completed:
                    # Get a new plan (the planner might decide we're done)
                    continue
            
            # Check if we exited due to max steps
            if step_counter >= self.max_steps and not overall_success:
                final_message = f"Reached maximum number of steps ({self.max_steps})"
                overall_success = False
                
            return {
                "success": overall_success,
                "reason": final_message,
                "steps": step_counter,
                "task_history": self.task_manager.get_task_history(),
                "trajectory": self.trajectory_steps
            }
                
        except Exception as e:
            logger.error(f"❌ Error during DroidAgent execution: {e}")
            if self.debug:
                import traceback
                logger.error(traceback.format_exc())
            return {
                "success": False, 
                "reason": str(e),
                "task_history": self.task_manager.get_task_history(),
                "trajectory": self.trajectory_steps
            } 