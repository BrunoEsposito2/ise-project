# AutoGen - BaseGroupChatManager as an abstract coordination artefact

class BaseGroupChatManager(SequentialRoutedAgent, ABC):
    
    def __init__(
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
        emit_team_events: bool = False,
    ):
        super().__init__(
            description="Group chat manager",

            # Definition of message types
            sequential_message_types=[
                GroupChatStart,
                GroupChatAgentResponse, 
                GroupChatMessage,
                GroupChatReset,
            ],
        )
        
        # Equivalent to defineObsProperty()
        self._name = name
        self._participant_names = participant_names                    # participants list
        self._participant_descriptions = participant_descriptions      # participant metadata
        self._message_thread: List[BaseAgentEvent | BaseChatMessage] = []  # conversation history
        self._current_turn = 0                                        # turn counter
        self._active_speakers: List[str] = []                         # current active speakers
        
        # Artifact parameters
        self._group_topic_type = group_topic_type
        self._output_topic_type = output_topic_type
        self._participant_name_to_topic_type = {                     # participant mapping
            name: topic_type for name, topic_type in zip(participant_names, participant_topic_types)
        }
        self._termination_condition = termination_condition          # termination logic
        self._max_turns = max_turns                                  # max turn limit
        self._output_message_queue = output_message_queue            # output channel
        self._message_factory = message_factory                      # message factory
        self._emit_team_events = emit_team_events                    # event emission flag

    @rpc
    async def handle_start(self, message: GroupChatStart, ctx: MessageContext) -> None:
        """Main coordination operation"""
        
        # Termination check (status check in CArtAgO)
        if self._termination_condition is not None and self._termination_condition.terminated:
            early_stop_message = StopMessage(
                content="The group chat has already terminated.",
                source=self._name,
            )
            await self._signal_termination(early_stop_message)
            return

        # Validation of the initial state
        await self.validate_group_state(message.messages)

        if message.messages is not None:
            # CArtAgO broadcast signal
            await self.publish_message(
                GroupChatStart(messages=message.messages),
                topic_id=DefaultTopicId(type=self._output_topic_type),
            )
            
            # output queue update
            for msg in message.messages:
                await self._output_message_queue.put(msg)

            # notification to participants
            await self.publish_message(
                GroupChatStart(messages=message.messages),
                topic_id=DefaultTopicId(type=self._group_topic_type),
                cancellation_token=ctx.cancellation_token,
            )

            # observable state update
            await self.update_message_thread(message.messages)

            # termination condition check
            if await self._apply_termination_condition(message.messages):
                return

        # selection of the next speaker
        await self._transition_to_next_speakers(ctx.cancellation_token)

    @event
    async def handle_agent_response(self, message: GroupChatAgentResponse, ctx: MessageContext) -> None:
        """Response management operation"""
        try:
            # Processing the agent's response
            delta: List[BaseAgentEvent | BaseChatMessage] = []
            if message.agent_response.inner_messages is not None:
                for inner_message in message.agent_response.inner_messages:
                    delta.append(inner_message)
            delta.append(message.agent_response.chat_message)

            # Message thread update
            await self.update_message_thread(delta)

            # Active speaker management
            self._active_speakers.remove(message.agent_name)
            if len(self._active_speakers) > 0:
                return  # Still waiting for other speakers

            # Termination condition check
            if await self._apply_termination_condition(delta, increment_turn_count=True):
                return

            # Selection of the next speaker
            await self._transition_to_next_speakers(ctx.cancellation_token)
            
        except Exception as e:
            # Error handling with termination
            error = SerializableException.from_exception(e)
            await self._signal_termination_with_error(error)
            raise

    async def _transition_to_next_speakers(self, cancellation_token: CancellationToken) -> None:
        """Switching to another speaker"""
        
        # Call to the abstract selection method
        speaker_names_future = asyncio.ensure_future(self.select_speaker(self._message_thread))
        cancellation_token.link_future(speaker_names_future)
        speaker_names = await speaker_names_future
        
        # Normalisation of the list of speakers
        if isinstance(speaker_names, str):
            speaker_names = [speaker_names]
        
        # Validation of selected speakers
        for speaker_name in speaker_names:
            if speaker_name not in self._participant_name_to_topic_type:
                raise RuntimeError(f"Speaker {speaker_name} not found in participant names.")
        
        # Selection log
        await self._log_speaker_selection(speaker_names)

        # Activation of selected speakers (signal("permission_to_speak", speaker) in CArtAgO)
        for speaker_name in speaker_names:
            speaker_topic_type = self._participant_name_to_topic_type[speaker_name]
            await self.publish_message(
                GroupChatRequestPublish(),
                topic_id=DefaultTopicId(type=speaker_topic_type),
                cancellation_token=cancellation_token,
            )
            self._active_speakers.append(speaker_name)

    async def _apply_termination_condition(
        self, 
        delta: Sequence[BaseAgentEvent | BaseChatMessage], 
        increment_turn_count: bool = False
    ) -> bool:
        """Termination logic"""
        
        # Custom condition check
        if self._termination_condition is not None:
            stop_message = await self._termination_condition(delta)
            if stop_message is not None:
                # Status reset
                await self._termination_condition.reset()
                self._current_turn = 0
                # Termination notification
                await self._signal_termination(stop_message)
                return True
        
        # Increase turn counter
        if increment_turn_count:
            self._current_turn += 1
        
        # Checking the maximum number of turns
        if self._max_turns is not None and self._current_turn >= self._max_turns:
            stop_message = StopMessage(
                content=f"Maximum number of turns {self._max_turns} reached.",
                source=self._name,
            )
            # Signal and reset
            if self._termination_condition is not None:
                await self._termination_condition.reset()
            self._current_turn = 0
            await self._signal_termination(stop_message)
            return True
        
        return False

    async def _signal_termination(self, message: StopMessage) -> None:
        """Notification of termination"""
        termination_event = GroupChatTermination(message=message)
        
        # Termination broadcast event
        await self.publish_message(
            termination_event,
            topic_id=DefaultTopicId(type=self._output_topic_type),
        )
        # Output queue update
        await self._output_message_queue.put(termination_event)

    @rpc
    async def handle_reset(self, message: GroupChatReset, ctx: MessageContext) -> None:
        """Reset operation"""
        await self.reset()

    async def update_message_thread(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> None:
        """Observable status update (update of CArtAgO observable properties)"""
        self._message_thread.extend(messages)

    # Operations to be implemented in subclasses
    @abstractmethod
    async def validate_group_state(self, messages: List[BaseChatMessage] | None) -> None:
        """Abstract validation operation - must be implemented by subclasses"""
        ...

    @abstractmethod
    async def select_speaker(self, thread: Sequence[BaseAgentEvent | BaseChatMessage]) -> List[str] | str:
        """Abstract speaker selection operation - must be implemented by subclasses"""
        ...

    @abstractmethod
    async def reset(self) -> None:
        """Abstract reset operation - must be implemented by subclasses"""
        ...
