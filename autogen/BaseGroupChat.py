# AutoGen - BaseGroupChat 

class BaseGroupChat(Team, ABC, ComponentBase[BaseModel]):
    """Organisational framework comparable to Moise"""
    
    component_type = "team"  # Type of organisational component
    
    def __init__(
        self,
        participants: List[ChatAgent],                    # Role definitions
        group_chat_manager_name: str,                     # Coordinator role
        group_chat_manager_class: type[SequentialRoutedAgent],  # Coordination type
        termination_condition: TerminationCondition | None = None,  # 'Goal' completion
        max_turns: int | None = None,                     # Constraints 
        runtime: AgentRuntime | None = None,              # Execution environment
        custom_message_types: List[type[BaseAgentEvent | BaseChatMessage]] | None = None,
        emit_team_events: bool = False,
    ):
        # Validation of the organisational structure 
        if len(participants) == 0:
            raise ValueError("At least one participant is required.")
        if len(participants) != len(set(participant.name for participant in participants)):
            raise ValueError("The participant names must be unique.")
        
        # Structural specification
        self._participants = participants
	      # ...
        self._participant_names: List[str] = [participant.name for participant in participants]
        self._participant_descriptions: List[str] = [participant.description for participant in participants]
        
        # Team identity as that of a group specification
        self._team_id = str(uuid.uuid4())
        
        # Communication topology similar to Moise links
        self._group_topic_type = f"group_topic_{self._team_id}"              # Broadcast channel
        self._group_chat_manager_topic_type = f"{group_chat_manager_name}_{self._team_id}"  # Manager channel
        self._participant_topic_types: List[str] = [                        # Individual channels
            f"{participant.name}_{self._team_id}" for participant in participants
        ]
        self._output_topic_type = f"output_topic_{self._team_id}"            # Output channel
        
        # Coordination configuration
        self._base_group_chat_manager_class = group_chat_manager_class
        self._termination_condition = termination_condition     # 'Goal' termination
        self._max_turns = max_turns                             # Turns limit
        
        # Message factory  
        self._message_factory = MessageFactory()
        if custom_message_types is not None:
            for message_type in custom_message_types:
                self._message_factory.register(message_type)

        # Runtime management
        if runtime is not None:
            self._runtime = runtime
            self._embedded_runtime = False
        else:
            # Embedded runtime
            self._runtime = SingleThreadedAgentRuntime(ignore_unhandled_exceptions=False)
            self._embedded_runtime = True

        # Organisational status
        self._initialized = False     # Initialization state
        self._is_running = False      # Execution state
        self._emit_team_events = emit_team_events
        
        # Output management
        self._output_message_queue: asyncio.Queue[BaseAgentEvent | BaseChatMessage | GroupChatTermination] = (
            asyncio.Queue()
        )

    async def _init(self, runtime: AgentRuntime) -> None:
        """Organisational instantiation"""
        
        # Manager registration 
        group_chat_manager_agent_type = AgentType(self._group_chat_manager_topic_type)
        
        # Registration of participants 
        for participant, agent_type in zip(self._participants, self._participant_topic_types, strict=True):
            # Agent container, wrapper for organisational management
            await ChatAgentContainer.register(
                runtime,
                type=agent_type,
                factory=self._create_participant_factory(
                    self._group_topic_type, self._output_topic_type, participant, self._message_factory
                ),
            )
            
            # Communication subscriptions, as for communication links 
            await runtime.add_subscription(TypeSubscription(topic_type=agent_type, agent_type=agent_type))
            await runtime.add_subscription(TypeSubscription(topic_type=self._group_topic_type, agent_type=agent_type))

        await self._base_group_chat_manager_class.register(
            runtime,
            type=group_chat_manager_agent_type.type,
            factory=self._create_group_chat_manager_factory(
                name=self._group_chat_manager_name,
                group_topic_type=self._group_topic_type,
                output_topic_type=self._output_topic_type,
                participant_names=self._participant_names,
                participant_topic_types=self._participant_topic_types,
                participant_descriptions=self._participant_descriptions,
                output_message_queue=self._output_message_queue,
                termination_condition=self._termination_condition,
                max_turns=self._max_turns,
                message_factory=self._message_factory,
            ),
        )
        
        # Manager subscriptions
        await runtime.add_subscription(
            TypeSubscription(topic_type=self._group_chat_manager_topic_type, agent_type=group_chat_manager_agent_type.type)
        )
        await runtime.add_subscription(
            TypeSubscription(topic_type=self._group_topic_type, agent_type=group_chat_manager_agent_type.type)
        )
        await runtime.add_subscription(
            TypeSubscription(topic_type=self._output_topic_type, agent_type=group_chat_manager_agent_type.type)
        )

        self._initialized = True

    async def run_stream(
        self,
        *,
        task: str | BaseChatMessage | Sequence[BaseChatMessage] | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> AsyncGenerator[BaseAgentEvent | BaseChatMessage | TaskResult, None]:
        """ Organisational implementation """
        
        # Task processing, equivalent to mission 
        messages: List[BaseChatMessage] | None = None
        if task is None:
            pass
        elif isinstance(task, str):
            messages = [TextMessage(content=task, source="user")]
        elif isinstance(task, BaseChatMessage):
            messages = [task]
        elif isinstance(task, list):
            if not task:
                raise ValueError("Task list cannot be empty.")
            messages = []
            for msg in task:
                if not isinstance(msg, BaseChatMessage):
                    raise ValueError("All messages in task list must be valid BaseChatMessage types")
                messages.append(msg)

	    # ...

        # Execution check
        if self._is_running:
            raise ValueError("The team is already running, it cannot run again until it is stopped.")
        self._is_running = True

        # Runtime startup
        if self._embedded_runtime:
            assert isinstance(self._runtime, SingleThreadedAgentRuntime)
            self._runtime.start()

        if not self._initialized:
            await self._init(self._runtime)

        # Shutdown management
        shutdown_task: asyncio.Task[None] | None = None
        if self._embedded_runtime:
            async def stop_runtime() -> None:
                assert isinstance(self._runtime, SingleThreadedAgentRuntime)
                try:
                    await self._runtime.stop_when_idle()
                    await self._output_message_queue.put(
                        GroupChatTermination(
                            message=StopMessage(content="The group chat is stopped.", source=self._group_chat_manager_name)
                        )
                    )
                except Exception as e:
                    await self._output_message_queue.put(
                        GroupChatTermination(
                            message=StopMessage(content="An exception occurred in the runtime.", source=self._group_chat_manager_name),
                            error=SerializableException.from_exception(e),
                        )
                    )
            shutdown_task = asyncio.create_task(stop_runtime())

        try:
            # Mission launch 
            await self._runtime.send_message(
                GroupChatStart(messages=messages),
                recipient=AgentId(type=self._group_chat_manager_topic_type, key=self._team_id),
                cancellation_token=cancellation_token,
            )
            
            # Output collection 
            output_messages: List[BaseAgentEvent | BaseChatMessage] = []
            stop_reason: str | None = None
            
            # Execution loop
            while True:
                message_future = asyncio.ensure_future(self._output_message_queue.get())
                if cancellation_token is not None:
                    cancellation_token.link_future(message_future)
                    
                message = await message_future
                
                if isinstance(message, GroupChatTermination):
                    # Termination management 
                    
                    if message.error is not None:
                        raise RuntimeError(str(message.error))
                    stop_reason = message.message.content
                    break
                    
                yield message
                if isinstance(message, ModelClientStreamingChunkEvent):
                    continue
                output_messages.append(message)

            # Delivery of results
            yield TaskResult(messages=output_messages, stop_reason=stop_reason)

        finally:
            try:
                if shutdown_task is not None:
                    await shutdown_task
            finally:
                # Cleaning
                while not self._output_message_queue.empty():
                    self._output_message_queue.get_nowait()
                self._is_running = False


    # Operational cycle operations

    async def reset(self) -> None:
        """Organisational reset """
        if not self._initialized:
            await self._init(self._runtime)
        if self._is_running:
            raise RuntimeError("The group chat is currently running. It must be stopped before it can be reset.")
        
        self._is_running = True
        if self._embedded_runtime:
            assert isinstance(self._runtime, SingleThreadedAgentRuntime)
            self._runtime.start()

        try:
            # Reset participants
            for participant_topic_type in self._participant_topic_types:
                await self._runtime.send_message(
                    GroupChatReset(),
                    recipient=AgentId(type=participant_topic_type, key=self._team_id),
                )
            # Reset manager
            await self._runtime.send_message(
                GroupChatReset(),
                recipient=AgentId(type=self._group_chat_manager_topic_type, key=self._team_id),
            )
        finally:
            if self._embedded_runtime:
                assert isinstance(self._runtime, SingleThreadedAgentRuntime)
                await self._runtime.stop_when_idle()
            while not self._output_message_queue.empty():
                self._output_message_queue.get_nowait()
            self._is_running = False

    async def pause(self) -> None:
        """Organisational break (not present in Moise)"""
        if not self._initialized:
            raise RuntimeError("The group chat has not been initialized.")
        
        # Broadcast pause to all participants
        for participant_topic_type in self._participant_topic_types:
            await self._runtime.send_message(
                GroupChatPause(),
                recipient=AgentId(type=participant_topic_type, key=self._team_id),
            )
        await self._runtime.send_message(
            GroupChatPause(),
            recipient=AgentId(type=self._group_chat_manager_topic_type, key=self._team_id),
        )

    async def resume(self) -> None:
        """Organisational recovery (not present in Moise)"""
        if not self._initialized:
            raise RuntimeError("The group chat has not been initialized.")
        
        # Broadcast recording to all participants
        for participant_topic_type in self._participant_topic_types:
            await self._runtime.send_message(
                GroupChatResume(),
                recipient=AgentId(type=participant_topic_type, key=self._team_id),
            )
        await self._runtime.send_message(
            GroupChatResume(),
            recipient=AgentId(type=self._group_chat_manager_topic_type, key=self._team_id),
        )

    # Status management 
    async def save_state(self) -> Mapping[str, Any]:
        """Persistence of organisational status"""
        if not self._initialized:
            await self._init(self._runtime)

        # Agent status collection
        agent_states: Dict[str, Mapping[str, Any]] = {}
        
        # Status of participants
        for name, agent_type in zip(self._participant_names, self._participant_topic_types, strict=True):
            agent_id = AgentId(type=agent_type, key=self._team_id)
            agent_states[name] = await self._runtime.agent_save_state(agent_id)
        
        # Manager status
        agent_id = AgentId(type=self._group_chat_manager_topic_type, key=self._team_id)
        agent_states[self._group_chat_manager_name] = await self._runtime.agent_save_state(agent_id)
        
        return TeamState(agent_states=agent_states).model_dump()

    async def load_state(self, state: Mapping[str, Any]) -> None:
        """Restoring organisational status"""
        if not self._initialized:
            await self._init(self._runtime)
        if self._is_running:
            raise RuntimeError("The team cannot be loaded while it is running.")
        
        self._is_running = True
        try:
            team_state = TeamState.model_validate(state)
            
            # Restore participant statuses
            for name, agent_type in zip(self._participant_names, self._participant_topic_types, strict=True):
                agent_id = AgentId(type=agent_type, key=self._team_id)
                if name not in team_state.agent_states:
                    raise ValueError(f"Agent state for {name} not found in the saved state.")
                await self._runtime.agent_load_state(agent_id, team_state.agent_states[name])
            
            # Restore manager status
            agent_id = AgentId(type=self._group_chat_manager_topic_type, key=self._team_id)
            if self._group_chat_manager_name not in team_state.agent_states:
                raise ValueError(f"Agent state for {self._group_chat_manager_name} not found in the saved state.")
            await self._runtime.agent_load_state(agent_id, team_state.agent_states[self._group_chat_manager_name])

        except ValidationError as e:
            raise ValueError("Invalid state format.") from e
        finally:
            self._is_running = False

    # Abstract factory method for specialised managers
    @abstractmethod
    def _create_group_chat_manager_factory(
        self,
        name: str,
        group_topic_type: str,
        output_topic_type: str,
        participant_topic_types: List[str],
        participant_names: List[str],
        participant_descriptions: List[str],
        output_message_queue: asyncio.Queue[BaseAgentEvent | BaseChatMessage | GroupChatTermination],
        termination_condition: TerminationCondition | None,
        max_turns: int | None,
        message_factory: MessageFactory,
    ) -> Callable[[], SequentialRoutedAgent]: ...


