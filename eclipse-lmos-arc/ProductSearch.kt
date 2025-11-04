// ProductSearch Service (Functional Artifact Backend)

@Component  // Service level
class ProductSearch(
    @Value("\${google.search.engine.key}") private val searchEngineKey: String,
    @Value("\${google.cloud.api.key}") private val cloudApiKey: String
) {
    private val logger = LoggerFactory.getLogger(javaClass)
    private val gson = Gson()

    // Core capability implementation: internal logic of a @OPERATION 
    suspend fun searchProduct(query: String, siteSearch: String): List<Product> {
        // Setup client HTTP 
        val client = HttpClient {
            install(ContentNegotiation) {
                json(Json { ignoreUnknownKeys = true })
            }
        }
        
        return runBlocking {
            try {
                // Input validation
                val encodedQuery = URLEncoder.encode(query, StandardCharsets.UTF_8.toString())
                logger.info("Query to search: $query")

                ...
                
                // Config validation
                if (cloudApiKey.isEmpty() || searchEngineKey.isEmpty()) {
                    throw Exception("Environment Variables are not set check Cloud and Search Engine Keys!")
                } else {
                
                	// External API call 
                	val url = "https://www.googleapis.com/customsearch/v1?key=$cloudApiKey&cx=$searchEngineKey&q=$encodedQuery&googlehost=google.com&lr=lang_en&alt=json"
                	logger.info("API Request URL: $url")
                
                	val response: ApiResponse = client.get(url).body()
                
                	// Data processing 
                	val regex = Regex("(price|currency)")
                	val productList = response.items.map { item ->
                    	Product(
                        	name = item.title,
                        	siteName = item.displayLink,
                        	link = item.link,
                        	snippet = item.snippet,
                        	thumbnail = item.pagemap.cse_thumbnail?.get(0)?.src,
                        	imageUrl = item.pagemap.cse_image?.get(0)?.src,
                        	rating = item.pagemap.aggregaterating,
                        	metadata = extractRequiredMetaData(item.pagemap.metatags, regex),
                        	offer = item.pagemap.offer
                    		)
                	}
		}
                
                // Logging result implementable, for example, with the observable property
                logger.debug(gson.toJson(productList))
                productList
                
            } ...
        }
    }

    // Utility operation (equivalent to CArtAgO helper method)
    private fun extractRequiredMetaData(
        metadata: List<Map<String, String>>?, 
        regex: Regex
    ): List<Map<String, String>> {
        val extractedMetaTags = mutableListOf<Map<String, String>>()
        
        if (metadata != null) {
            for (map in metadata) {
                for ((key, value) in map) {
                    if (regex.containsMatchIn(key)) {
                        // Data extraction 
                        extractedMetaTags.add(mapOf(key to value))
                    }
                }
            }
        }
        return extractedMetaTags
    }
}
