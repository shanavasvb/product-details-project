# product-details-project
Overview
This system takes barcode numbers as input and attempts to retrieve detailed product information through a series of increasingly sophisticated methods:

Local database lookup
Open Food Facts API query
Web search for barcode information
AI-powered processing of web search results
Direct AI queries as a last resort

The system is designed to maximize the chances of finding accurate product information by leveraging multiple data sources and advanced AI capabilities.
Features

Multi-source Lookup: Checks multiple data sources in sequence
Web Search Integration: Uses SerpAPI to search the web for barcode information
AI Processing: Leverages DeepSeek and OpenAI models to extract product information
Fallback System: Gracefully degrades through multiple methods if primary lookups fail
Testing Mode: Provides detailed debugging for individual barcodes
Batch Processing: Handles multiple barcodes from an input file

Requirements

Python 3.7+
Internet connection
API keys (optional but recommended):

SerpAPI key for web searches
DeepSeek API key for AI processing
OpenAI API key for AI processing



Installation

Clone the repository:
bashgit clone https://github.com/yourusername/barcode-lookup-system.git
cd barcode-lookup-system

Install dependencies:
bashpip install -r requirements.txt

Create a .env file with your API keys:
SERPAPI_KEY=your_serp_api_key
DEEPSEEK_API_KEY=your_deepseek_api_key
OPENAI_API_KEY=your_openai_api_key


Usage
Normal Mode
Process multiple barcodes from an input file:
bashpython script.py  # Will prompt for input file
Or specify the input file directly:
bashINPUT_FILE=barcodes.txt python script.py
The input file should contain one barcode per line.
Test Mode
To test a single barcode and see detailed output from each lookup method:
bashTEST_MODE=true TEST_BARCODE=0123456789012 python script.py
This will show the results from each step of the lookup process for debugging purposes.
How It Works

Local Database Check: First checks a local database (if available) for the barcode
Open Food Facts API: Queries the Open Food Facts database for product information
Web Search: If previous methods fail, searches the web for the barcode using SerpAPI
AI Web Processing: Sends web search results to DeepSeek or OpenAI to extract structured product information
Direct AI Query: As a last resort, asks AI models to provide information based on their training data
Fallback: If all methods fail, returns an empty product template

Configuration
The system can be configured through environment variables:

INPUT_FILE: Path to file containing barcodes (one per line)
OUTPUT_FILE: Path for saving results (defaults to results.json)
TEST_MODE: Set to true to enable single barcode testing
TEST_BARCODE: Barcode to use in test mode
SERPAPI_KEY: API key for SerpAPI web searches
DEEPSEEK_API_KEY: API key for DeepSeek AI
OPENAI_API_KEY: API key for OpenAI
SKIP_LOCAL_DB: Set to true to skip local database lookup
SKIP_OPENFOODFACTS: Set to true to skip Open Food Facts API
SKIP_WEB_SEARCH: Set to true to skip web search
SKIP_AI: Set to true to skip all AI-based lookups

Output Format
The system returns product information in JSON format:
json{
  "barcode": "0123456789012",
  "name": "Example Product Name",
  "brand": "Brand Name",
  "description": "Product description text",
  "ingredients": "Ingredient 1, Ingredient 2, ...",
  "nutrition_facts": {
    "serving_size": "100g",
    "calories": 240,
    "protein": "3g",
    "carbohydrates": "25g",
    "fat": "14g"
  },
  "allergens": ["Milk", "Wheat"],
  "source": "web_search_ai",
  "confidence": 0.85
}
Error Handling

If a barcode cannot be found through any method, an empty template is returned
API failures are gracefully handled with appropriate fallbacks
Web search timeouts or failures automatically trigger alternative methods

Contributing
Contributions are welcome! Please feel free to submit a Pull Request.
License
This project is licensed under the MIT License - see the LICENSE file for details.
Acknowledgments

Open Food Facts for their open database and API
SerpAPI for web search capabilities
DeepSeek and OpenAI for AI processing capabilities
