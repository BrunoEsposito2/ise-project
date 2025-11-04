// CArtAgO - Coordination artefact for managing speaking turns

@ARTIFACT_INFO(
    outports = {
        @OUTPORT(name="out")
    }
)
  
public class MeetingRoomArtifact extends Artifact {
    
    private List<String> participants;
    private String currentSpeaker;
    private Queue<String> speakingQueue;
    private List<String> messageThread;
    private int currentTurn;
    private boolean terminated;
    
    @OPERATION
    public void initializeMeeting(String[] participantNames, String[] descriptions) {
        participants = Arrays.asList(participantNames);
        messageThread = new ArrayList<>();
        currentTurn = 0;
        terminated = false;
        
        // Updates to observable properties
        defineObsProperty("participants", participants.toArray());
        defineObsProperty("current_turn", currentTurn);
        defineObsProperty("terminated", terminated);
        signal("meeting_initialized", participantNames.length);
    }
    
    @OPERATION
    public void startMeeting(String[] initialMessages) {
        if (terminated) {
            signal("meeting_already_terminated");
            return;
        }
        
        // Processing of initial messages
        if (initialMessages != null) {
            Collections.addAll(messageThread, initialMessages);
            defineObsProperty("message_count", messageThread.size());
        }
        
        // Select the next speaker
        selectNextSpeaker();
    }
    
    @OPERATION
    public void handleAgentResponse(String agentName, String message) {
        // Update the message list
        messageThread.add(agentName + ": " + message);
        defineObsProperty("message_count", messageThread.size());
        
        // Remove it from the active speakers
        speakingQueue.remove(agentName);
        
        // Check the termination conditions
        if (checkTerminationCondition(message) || currentTurn >= maxTurns) {
            terminated = true;
            defineObsProperty("terminated", true);
            signal("meeting_terminated", "Condition met");
            return;
        }
        
        // Continue with the next speaker
        currentTurn++;
        defineObsProperty("current_turn", currentTurn);
        selectNextSpeaker();
    }
    
    @OPERATION
    public void selectNextSpeaker() {
        if (terminated || participants.isEmpty()) {
            return;
        }
        
        // Selection logic (can be customised)
        String selectedSpeaker = performSpeakerSelection();
        currentSpeaker = selectedSpeaker;
        
        // Updating observable property
        defineObsProperty("current_speaker", currentSpeaker);
        
        // Request permission to speak
        signal("permission_to_speak", selectedSpeaker);
    }
    
    @OPERATION
    public void resetMeeting() {
        messageThread.clear();
        currentTurn = 0;
        currentSpeaker = null;
        terminated = false;
        speakingQueue.clear();
        
        // Reset observable properties
        defineObsProperty("message_count", 0);
        defineObsProperty("current_turn", 0);
        defineObsProperty("current_speaker", "none");
        defineObsProperty("terminated", false);
        signal("meeting_reset");
    }
    
    private String performSpeakerSelection() {
        // Abstract selection logic (e.g. round-robin as implemented by AutoGen)
        return participants.get(currentTurn % participants.size());
    }
    
    private boolean checkTerminationCondition(String message) {
        // Customisable termination logic
        return message.toLowerCase().contains("terminate") || 
               message.toLowerCase().contains("finish");
    }
}
