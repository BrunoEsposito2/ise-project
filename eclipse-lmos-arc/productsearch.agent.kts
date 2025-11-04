// Use by the agent

agent {
    name = "productsearch-agent"
    description = """
        This agent provides a curated list of product recommendations tailored to 
        explicit technical features and specifications identified by the user, such as 
        RAM, storage, processor type, and resolution. It is designed to match user 
        inquiries with precise products, best suited for those who have detailed 
        feature needs and are ready to choose from available options.
    """
    
    systemPrompt = {
        ...
        
        // Conversation context
        val conversationHistory = mutableListOf<String>()
        for (message in request.messages) {
            conversationHistory.add("${message.role}: ${message.content}")
        }
        
        """
        You are an AI product recommendation agent designed to suggest products 
        based on user inputs. Your task is to analyze the conversation history 
        or user query, generate appropriate search queries, and return a list 
        of recommended products in a specific format.
        
        ...

        To search for products, you have access to the following function: productsearch

        ...

        """.trimIndent()
    }
    
    // Access to the artefact
    tools = listOf("productsearch")  // Artifact access operation
}
