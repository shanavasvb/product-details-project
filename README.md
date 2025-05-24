# Product Details Project

A barcode-based product information retrieval system that aggregates data from multiple sources to build a comprehensive product database.

## Overview

The Product Details Project is a versatile system that takes barcode numbers as input and retrieves detailed product information through a series of increasingly sophisticated methods. It leverages multiple data sources including APIs, web scraping, and AI-powered processing to ensure the most accurate and complete product data possible.

## Features

- **Multi-Source Data Collection**: Retrieves product data from:
  - Open Food Facts database
  - BigBasket website
  - DigitEyes API
  - Google Search results
  - OpenAI and DeepSeek AI for enrichment

- **Intelligent Processing Pipeline**: 
  - Progressively tries multiple sources if primary lookups fail
  - Extracts product attributes (name, brand, description, images, etc.)
  - Standardizes data format across different sources
  - Uses AI to enhance incomplete product information

- **Robust Error Handling**: 
  - Gracefully handles errors with appropriate fallbacks
  - Detailed logging of processing steps and issues

- **Batch Processing**: 
  - Efficiently processes thousands of barcodes from Excel files
  - Shows progress tracking during processing
  - Can resume from interruptions without duplicating work

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/shanavasvb/product-details-project.git
   cd product-details-project
   ```

2. Install required packages:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the project root directory with your API keys and configuration:
   ```
   # API Keys
   SERPAPI_KEY=your_serpapi_key_here
   OPENAI_API_KEY=your_openai_api_key_here
   DEEPSEEK_API_KEY=your_deepseek_api_key_here
   DIGITEYES_APP_KEY=your_digiteyes_app_key_here
   DIGITEYES_SIGNATURE=your_digiteyes_signature_here
   ```

## Configuration

The system can be configured through environment variables in your `.env` file:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `INPUT_FILE` | Path to the Excel file with barcodes | - |
| `OUTPUT_FILE` | Path to save JSON results | `barcode_results.json` |
| `API_REQUEST_DELAY` | Delay between API calls in seconds | `1.0` |
| `MAX_RETRIES` | Maximum number of retries for failed requests | `3` |
| `MAX_DAILY_REQUESTS` | Maximum API calls per day | `10000` |
| `SKIP_OPENFOODFACTS` | Set to `true` to skip Open Food Facts API | `false` |
| `SKIP_BIGBASKET` | Set to `true` to skip BigBasket scraping | `false` |
| `SKIP_DIGITEYES` | Set to `true` to skip DigitEyes API | `false` |
| `SKIP_AI` | Set to `true` to skip all AI-based lookups | `false` |

## Usage

### Basic Usage

Run the script to process barcodes from an Excel file:

```bash
python barcodefetcher.py
```

The script will prompt you for the input file path if not specified in the `.env` file.

### Process Specific Input File

```bash
python barcodefetcher.py --input path/to/your/barcodes.xlsx
```

### Start from a Specific Barcode

If processing was interrupted, you can resume from a particular barcode:

```bash
python barcodefetcher.py --start 8902102125808
```

### Test Mode for a Single Barcode

To test processing for a single barcode with detailed output:

```bash
python barcodefetcher.py --test 8902102127123
```

### Input Format

The input Excel file should contain a column named 'barcode' or 'Barcode' with product barcode numbers.

## Data Sources

The system tries the following sources in sequence until valid product information is found:

1. **Open Food Facts**: A free, open database of food products from around the world
2. **DigitEyes API**: A commercial barcode database API
3. **BigBasket**: Web scraping of Indian online grocery delivery service
4. **Google Search**: Used to find relevant product pages when direct lookups fail
5. **AI Enhancement**: OpenAI and DeepSeek used to fill gaps in product information

## Output Format

The script generates a JSON file with product details in the following format:

```json
{
  "Barcode": "8902102127123",
  "Product Name": "Henko Matic Front Load Liquid Detergent, 500 ml",
  "Description": "Henko Matic Front Load Liquid Detergent is a high-quality laundry product...",
  "Category": "Cleaning & Household",
  "ProductLine": "Henko Product Line",
  "Quantity": 500,
  "Unit": "ml",
  "Features": [
    "Removes tough stains",
    "Gentle on hands",
    "Fresh fragrance",
    "Antibacterial properties"
  ],
  "Specification": {
    "Weight": "500 ml",
    "Country of Origin": "India",
    "Form": "Liquid",
    "Packaging Type": "Bottle"
  },
  "Brand": "Henko",
  "Product Image": "https://example.com/product_image.jpg",
  "Product Ingredient Image": "https://example.com/ingredients_image.jpg"
}
```

## Troubleshooting

### Image URL Issues

If you encounter missing or placeholder images in your results, try the following:

1. **Check Image Extraction Function**: Ensure the `extract_bigbasket_info` function has the latest image extraction code that handles multiple image sources and formats.

2. **Fix URL Transformation**: Update the `transform_to_desired_format` function to properly handle image URLs:

   ```python
   # Improved image handling in transform_to_desired_format
   image_url = product_info.get("image_url", "")
   
   if not image_url or "placeholder" in image_url.lower():
       # Try to use OpenFoodFacts URL format if we have a valid barcode
       if len(barcode) >= 13:
           off_url = f"https://images.openfoodfacts.org/images/products/{barcode[:3]}/{barcode[3:6]}/{barcode[6:9]}/{barcode[9:]}/front_en.3.400.jpg"
           result["Product Image"] = off_url
           result["Product Ingredient Image"] = off_url
       else:
           # If not a valid barcode, use a better placeholder
           placeholder = "https://images.openfoodfacts.org/images/products/default.jpg"
           result["Product Image"] = placeholder
           result["Product Ingredient Image"] = placeholder
   else:
       # Use properly extracted image URL
       result["Product Image"] = image_url
       result["Product Ingredient Image"] = image_url
   ```

3. **Image Fallback Strategy**: The system implements a multi-tier fallback for images:
   - First tries to extract from the source website
   - Falls back to OpenFoodFacts URL pattern if barcode is valid
   - Uses a placeholder as last resort

### Common Errors

1. **API Rate Limiting**: If you see "API request limit reached" errors, increase the `API_REQUEST_DELAY` value in your configuration.

2. **'NoneType' object has no attribute 'get'**: This typically occurs when trying to access properties on a `None` value. Check your `enhance_product_info_with_ai` function for proper handling of `None` values.

3. **Missing product information**: If too many products have minimal information, ensure all API keys are correctly set in your `.env` file.

## Error Handling

The script logs all activities and errors to both console and a log file named `barcode_processing.log`. If processing is interrupted, it saves the current state and can resume from the last processed barcode.

## Dependencies

The project requires the following Python packages:

```
requests==2.31.0
pandas==2.0.3
openpyxl==3.1.2
beautifulsoup4==4.12.2
tqdm==4.65.0
python-dotenv==1.0.0
openai==0.28.1
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Author

Developed for the company DatCarts
