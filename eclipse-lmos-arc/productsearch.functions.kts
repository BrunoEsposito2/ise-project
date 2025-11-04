// Functional artefact interface

function(
    name = "productsearch",
    description = "Search products based on the specifications",
    params = types(
        string(
            name = "query", 
            description = "A query with technical descriptions of the products or user required specifications"
        )
    ),
) { (query) ->
    // dependency injection
    val productSearch = get<ProductSearch>()  // Access to the backend service
    
    // Operation delegation: equivalent to invoking a @OPERATION 
    val contextResult = query?.let { 
        productSearch.searchProduct(it, "")  // Call to the service method
    }
    
    // Formatting and returning the result that can be associated with CArtAgO's signal()
    """
        $contextResult
    """.trimIndent()
}
