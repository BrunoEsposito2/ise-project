# CAMEL Official - Workforce as a Hierarchical Organisation

class Workforce(BaseNode):
    """
    Hierarchical organisation in CAMEL
    
    Implements a hierarchical system where multiple worker nodes (agents) cooperate
    to solve complex tasks. It can assign tasks to worker nodes and adopt
    strategies such as creating new workers, breaking down tasks, etc.
    
    The workforce uses three specialised internal ChatAgents:
    - Coordinator Agent: Assigns tasks to workers based on their capabilities
    - Task Planner Agent: Breaks down complex tasks and compiles results
    - Dynamic Workers: Created at runtime when tasks fail repeatedly
    """
    
    def __init__(
        self,
        description: str,                                    # Description of the organisation
        children: Optional[List[BaseNode]] = None,           # Hierarchical structure 
        coordinator_agent_kwargs: Optional[Dict] = None,     # Coordinator Configuration
        task_agent_kwargs: Optional[Dict] = None,           # Planner Configuration
        new_worker_agent_kwargs: Optional[Dict] = None,     # Dynamic worker configuration
        graceful_shutdown_timeout: float = 15.0,            # Failure Management
        share_memory: bool = False,                          # Knowledge sharing
    ) -> None:
        super().__init__(description)
        
        # Hierarchical structure
        self._children = children or []                      # Sub-organizations/workers
        self._child_listening_tasks: Deque[asyncio.Task] = deque()
        
        # Organisational status
        self._state = WorkforceState.IDLE                   # Workforce execution state
        self._task: Optional[Task] = None                   # Main task being processed
        self._pending_tasks: Deque[Task] = deque()          # Task queue
        self._completed_tasks: List[Task] = []              # Completed tasks
        self._task_dependencies: Dict[str, List[str]] = {}  # Task dependency graph
        self._assignees: Dict[str, str] = {}                # Task-to-worker assignments
        self._in_flight_tasks: int = 0                      # Currently executing tasks
        
        # Human intervention support
        self._pause_event = asyncio.Event()
        self._pause_event.set()                             # Initially not paused
        self._stop_requested = False
        self._snapshots: List[WorkforceSnapshot] = []       # State snapshots
        
        # Coordinating agent, specified with the coordinator role in Moise
        coord_agent_sys_msg = BaseMessage.make_assistant_message(
            role_name="Workforce Manager",
            content="You are coordinating a group of workers. A worker can be "
                   "a group of agents or a single agent. Each worker is "
                   "created to solve a specific kind of task. Your job "
                   "includes assigning tasks to a existing worker, creating "
                   "a new worker for a task, etc.",
        )
        self.coordinator_agent = ChatAgent(
            coord_agent_sys_msg,
            **(coordinator_agent_kwargs or {}),
        )

        # Planning agent, specifiable with the task_planner role in Moise
        task_sys_msg = BaseMessage.make_assistant_message(
            role_name="Task Planner",
            content="You are going to compose and decompose tasks. Keep "
                   "tasks that are sequential and require the same type of "
                   "agent together in one agent process. Only decompose tasks "
                   "that can be handled in parallel and require different types "
                   "of agents. This ensures efficient execution by minimizing "
                   "context switching between agents.",
        )
        _task_agent_kwargs = dict(task_agent_kwargs or {})
        extra_tools = TaskPlanningToolkit().get_tools()
        _task_agent_kwargs["tools"] = [
            *_task_agent_kwargs.get("tools", []),
            *extra_tools,
        ]
        self.task_agent = ChatAgent(task_sys_msg, **_task_agent_kwargs)
        
        # Shared memory system (not present in Moise)
        self.share_memory = share_memory
        
        # Metrics and monitoring
        self.metrics_logger = WorkforceLogger(workforce_id=self.node_id)

    # Hierarchical task processing
    async def process_task_async(self, task: Task, interactive: bool = False) -> Task:
        """ 
        Main coordination operation, similar to the execution of a hierarchical scheme Moise
        """
        if interactive:
            return await self._process_task_with_snapshot(task)

        # Task validation
        if not validate_task_content(task.content, task.id):
            task.state = TaskState.FAILED
            task.result = "Task failed: Invalid or empty content provided"
            return task
	 # ...

        self.reset()
        self._task = task
	
	 # ...
        
        # Task decomposition (task_planner goal)

        # The agent tend to be overconfident on the whole task, so we
        # decompose the task into subtasks first
        subtasks = self._decompose_task(task)

	 # ...
        
        if subtasks:
            # Hierarchical delegation

            # If decomposition happened, the original task becomes a container.
            # We only execute its subtasks.
            self._pending_tasks.extendleft(reversed(subtasks))
        else:
            # If no decomposition, execute the original task.
            self._pending_tasks.append(task)

        self.set_channel(TaskChannel())
        await self.start()

        # Composition of results
        if subtasks:
            task.result = "\n\n".join(
                f"--- Subtask {sub.id} Result ---\n{sub.result}"
                for sub in task.subtasks
                if sub.result
            )
            if task.subtasks and all(
                sub.state == TaskState.DONE for sub in task.subtasks
            ):
                task.state = TaskState.DONE
            else:
                task.state = TaskState.FAILED

        return task

    def _decompose_task(self, task: Task) -> List[Task]:
        """ Task decomposition (possible decompose_and_plan goal)"""
        decompose_prompt = WF_TASK_DECOMPOSE_PROMPT.format(
            content=task.content,
            child_nodes_info=self._get_child_nodes_info(),
            additional_info=task.additional_info,
        )
        self.task_agent.reset()
        subtasks = task.decompose(self.task_agent, decompose_prompt)
        task.subtasks = subtasks
        for subtask in subtasks:
            subtask.parent = task
        return subtasks

    def _find_assignee(self, tasks: List[Task]) -> TaskAssignResult:
        """ Task assignment (possible coordinate_workforce goal)
        
        Assign multiple tasks to worker nodes with the best capabilities.
        """
        self.coordinator_agent.reset()

        # Task information formatting
        tasks_info = ""
        for task in tasks:
            tasks_info += f"Task ID: {task.id}\n"
            tasks_info += f"Content: {task.content}\n"
            if task.additional_info:
                tasks_info += f"Additional Info: {task.additional_info}\n"
            tasks_info += "---\n"

        prompt = ASSIGN_TASK_PROMPT.format(
            tasks_info=tasks_info,
            child_nodes_info=self._get_child_nodes_info(),
        )

	# ...

        # Coordinator decision
        response = self.coordinator_agent.step(
            prompt, response_format=TaskAssignResult
        )
        
        if response.msg is None or response.msg.content is None:
            logger.error("Coordinator agent returned empty response for task assignment")
            return TaskAssignResult(assignments=[])

        result_dict = json.loads(response.msg.content, parse_int=str)
        task_assign_result = TaskAssignResult(**result_dict)
        return task_assign_result

    def _create_worker_node_for_task(self, task: Task) -> Worker:
        """ Dynamic worker creation (permission "create_new_workers" in Moise) """
        prompt = CREATE_NODE_PROMPT.format(
            content=task.content,
            child_nodes_info=self._get_child_nodes_info(),
            additional_info=task.additional_info,
        )
        response = self.coordinator_agent.step(prompt, response_format=WorkerConf)
        
        if response.msg is None or response.msg.content is None:
            # Fallback strategy
            new_node_conf = WorkerConf(
                description=f"Fallback worker for task: {task.content[:50]}...",
                role="General Assistant",
                sys_msg="You are a general assistant that can help with various tasks.",
            )
        else:
            result_dict = json.loads(response.msg.content)
            new_node_conf = WorkerConf(**result_dict)

        # Create new agent
        new_agent = self._create_new_agent(new_node_conf.role, new_node_conf.sys_msg)

        # Worker node instantiation
        new_node = SingleAgentWorker(
            description=new_node_conf.description,
            worker=new_agent,
            pool_max_size=10,
        )
        new_node.set_channel(self._channel)

        # Hierarchical integration
        self._children.append(new_node)
	# ...
        self._child_listening_tasks.append(asyncio.create_task(new_node.start()))
        
        return new_node

    # Hierarchical construction methods
    
    def add_single_agent_worker(
        self,
        description: str,
        worker: ChatAgent,
        pool_max_size: int = 10,
    ) -> Workforce:
        """ Added executive worker, equivalent to add a single_agent_worker role in Moise
        """
        worker_node = SingleAgentWorker(
            description=description,
            worker=worker,
            pool_max_size=pool_max_size,
        )
        self._children.append(worker_node)
	# ...
        return self

    def add_role_playing_worker(
        self,
        description: str,
        assistant_role_name: str,
        user_role_name: str,
        assistant_agent_kwargs: Optional[Dict] = None,
        user_agent_kwargs: Optional[Dict] = None,
        summarize_agent_kwargs: Optional[Dict] = None,
        chat_turn_limit: int = 3,
    ) -> Workforce:
        """ Collaborative worker added (addition of a role-playing worker role Moise)
        """
        worker_node = RolePlayingWorker(
            description=description,
            assistant_role_name=assistant_role_name,
            user_role_name=user_role_name,
            assistant_agent_kwargs=assistant_agent_kwargs,
            user_agent_kwargs=user_agent_kwargs,
            summarize_agent_kwargs=summarize_agent_kwargs,
            chat_turn_limit=chat_turn_limit,
        )
        self._children.append(worker_node)
	# ...
        return self

    def add_workforce(self, workforce: Workforce) -> Workforce:
        """ Add sub-organisation (add a Moise sub-group)
        """
        self._children.append(workforce)
        return self

    # Shared memory management (possible evolution compared to Moise)
    
    def _collect_shared_memory(self) -> Dict[str, List]:
        """ Shared knowledge collection"""
        if not self.share_memory:
            return {}

        shared_memory: Dict[str, List] = {
            'coordinator': [],
            'task_agent': [],
            'workers': [],
        }

        try:
            # Coordinator's Memory
            coord_records = self.coordinator_agent.memory.retrieve()
            shared_memory['coordinator'] = [
                record.memory_record.to_dict() for record in coord_records
            ]

            # Task agent memory
            task_records = self.task_agent.memory.retrieve()
            shared_memory['task_agent'] = [
                record.memory_record.to_dict() for record in task_records
            ]

            # Worker memory (SingleAgentWorker only)
            for child in self._children:
                if isinstance(child, SingleAgentWorker):
                    worker_records = child.worker.memory.retrieve()
                    worker_memory = [
                        record.memory_record.to_dict()
                        for record in worker_records
                    ]
                    shared_memory['workers'].extend(worker_memory)

        except Exception as e:
            logger.warning(f"Error collecting shared memory: {e}")

        return shared_memory

    def _sync_shared_memory(self) -> None:
        """ Knowledge synchronisation"""
        if not self.share_memory:
            return

        try:
            shared_memory = self._collect_shared_memory()
            self._share_memory_with_agents(shared_memory)
        except Exception as e:
            logger.warning(f"Error synchronizing shared memory: {e}")

    # Human intervention support 
    
    def pause(self) -> None:
        """ Organisational break"""
        if self._loop and not self._loop.is_closed():
            self._submit_coro_to_loop(self._async_pause())
        else:
            if self._state == WorkforceState.RUNNING:
                self._state = WorkforceState.PAUSED
                self._pause_event.clear()

    def resume(self) -> None:
        """ Organisational recovery"""
        if self._loop and not self._loop.is_closed():
            self._submit_coro_to_loop(self._async_resume())
        else:
            if self._state == WorkforceState.PAUSED:
                self._state = WorkforceState.RUNNING
                self._pause_event.set()

    def save_snapshot(self, description: str = "") -> None:
        """ Status snapshot"""
        snapshot = WorkforceSnapshot(
            main_task=self._task,
            pending_tasks=self._pending_tasks,
            completed_tasks=self._completed_tasks,
            task_dependencies=self._task_dependencies,
            assignees=self._assignees,
            current_task_index=len(self._completed_tasks),
            description=description or f"Snapshot at {time.time()}",
        )
        self._snapshots.append(snapshot)

    # Life cycle management
    
    def reset(self) -> None:
        """ Organisational reset"""
        super().reset()
        self._task = None
        self._pending_tasks.clear()
        self._child_listening_tasks.clear()
        self._task_dependencies.clear()
        self._completed_tasks = []
        self._assignees.clear()
        self._in_flight_tasks = 0
        
        # Hierarchical reset
        self.coordinator_agent.reset()
        self.task_agent.reset()
        for child in self._children:
            child.reset()
        
        self._state = WorkforceState.IDLE
        self._stop_requested = False
