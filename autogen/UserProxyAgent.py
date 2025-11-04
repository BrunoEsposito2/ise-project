# AutoGen  - UserProxyAgent as a mediation artefact 

class UserProxyAgent(BaseChatAgent, Component[UserProxyAgentConfig]):
    def __init__(
        self,
        name: str,
        *,
        description: str = "A human user",
        input_func: Optional[InputFuncType] = None,
    ) -> None:
        super().__init__(name=name, description=description)
        
        # Connection to external resource (human user)
        self.input_func = input_func or cancellable_input  # Default input mechanism
        self._is_async = iscoroutinefunction(self.input_func)  # Function type detection
        
    
    # Mediation configuration (Autogen supports both synchronous and asynchronous functions)

    @property
    def produced_message_types(self) -> Sequence[type[BaseChatMessage]]:
        """ Declaration of mediation capacity (operations in CArtAgO) """
        return (TextMessage, HandoffMessage)  # Can mediate both standard and handoff interactions

    async def on_messages_stream(
        self, 
        messages: Sequence[BaseChatMessage], 
        cancellation_token: CancellationToken
    ) -> AsyncGenerator[BaseAgentEvent | BaseChatMessage | Response, None]:
        
        # Main mediation operation
        
        try:
            # Specialised mediation for handoff 
            handoff = self._get_latest_handoff(messages)
            prompt = (
                f"Handoff received from {handoff.source}. Enter your response: " 
                if handoff else "Enter your response: "
            )

            # ID generation 
            request_id = str(uuid.uuid4())

            # External interaction (signal("input_requested", ...) in CArtAgO)
            input_requested_event = UserInputRequestedEvent(
                request_id=request_id, 
                source=self.name
            )
            yield input_requested_event

            # Context management, manages context for callbacks
            with UserProxyAgent.InputRequestContext.populate_context(request_id):
                # External interaction (human input) 
                user_input = await self._get_input(prompt, cancellation_token)

            # Constructing the response
            if handoff:
                # Specialised for handoff 
                yield Response(chat_message=HandoffMessage(
                    content=user_input, 
                    target=handoff.source, 
                    source=self.name
                ))
            else:
                # Standard, for regular mediation of user input 
                yield Response(chat_message=TextMessage(
                    content=user_input, 
                    source=self.name
                ))

        except asyncio.CancelledError:
            # Cancellation management 
            raise  # Proper async cancellation propagation
        except Exception as e:
            # Error handling (e.g. signal("input_request_failed", ...) in CArtAgO)
            raise RuntimeError(f"Failed to get user input: {str(e)}") from e

    async def _get_input(self, prompt: str, cancellation_token: Optional[CancellationToken]) -> str:
        """ Adaptive external interaction (both synchronous and asynchronous)"""
        
        try:
            if self._is_async:
                # async  
                async_func = cast(AsyncInputFunc, self.input_func)
                return await async_func(prompt, cancellation_token)
            else:
                # sync
                sync_func = cast(SyncInputFunc, self.input_func)
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(None, sync_func, prompt)

        except asyncio.CancelledError:
            # cancellation management 
            raise  # Clean cancellation propagation
        except Exception as e:
            # Conversion of external errors to the system format 
            raise RuntimeError(f"Failed to get user input: {str(e)}") from e

    def _get_latest_handoff(self, messages: Sequence[BaseChatMessage]) -> Optional[HandoffMessage]:
        """Specialised mediation capacity """
        # message analysis 
        if len(messages) > 0 and isinstance(messages[-1], HandoffMessage):
            if messages[-1].target == self.name:
                return messages[-1]  # Valid handoff to this mediator
            else:
                # Validation
                raise RuntimeError(f"Handoff target mismatch: {messages[-1].source}")
        return None

    # Advanced context management 
    class InputRequestContext:
        # Context management system
        
        _INPUT_REQUEST_CONTEXT_VAR: ClassVar[ContextVar[str]] = ContextVar("_INPUT_REQUEST_CONTEXT_VAR")

        @classmethod
        @contextmanager
        def populate_context(cls, ctx: str) -> Generator[None, Any, None]:
            """Provides the request context to callbacks"""
            token = cls._INPUT_REQUEST_CONTEXT_VAR.set(ctx)
            try:
                yield  # Context available during external interaction
            finally:
                cls._INPUT_REQUEST_CONTEXT_VAR.reset(token)  # Clean context cleanup

        @classmethod
        def request_id(cls) -> str:
            """Returns the ID of the current request from the context """
            try:
                return cls._INPUT_REQUEST_CONTEXT_VAR.get()
            except LookupError as e:
                raise RuntimeError(
                    "Context must be accessed within input callback"
                ) from e

    # Operational cycle operations (CArtAgO operations)
    async def on_reset(self, cancellation_token: Optional[CancellationToken] = None) -> None:
        """ Reset operation """
        pass  # Basic implementation

    def _to_config(self) -> UserProxyAgentConfig:
        """Serialisation of status """
        return UserProxyAgentConfig(
            name=self.name, 
            description=self.description, 
            input_func=None  # the functions are not serialisable
        )

    @classmethod
    def _from_config(cls, config: UserProxyAgentConfig) -> Self:
        """ Restoring the status """
        return cls(
            name=config.name, 
            description=config.description, 
            input_func=None
        )

