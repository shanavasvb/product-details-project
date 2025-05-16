#!/usr/bin/env python3
# Barcode Product Data Fetcher - Enhanced Version
# This script fetches product data from the web, then uses AI APIs to refine and structure the data

import os
import json
import time
import re
from typing import Dict, List, Any, Optional, Union
from enum import Enum
import requests
from dotenv import load_dotenv
import pandas as pd
from urllib.parse import quote_plus

# Load environment variables
load_dotenv()

# Define the unit enum
class UnitEnum(str, Enum):
    G100 = '100g'
    G200 = '200g'
    G250 = '250g'
    G500 = '500g'
    KG1 = '1kg'
    ML100 = '100ml'
    ML200 = '200ml'
    ML500 = '500ml'
    L1 = '1L'
    PIECE = 'piece'
    PACK = 'pack'

# Barcode validation functions
def is_valid_ean13(barcode: str) -> bool:
    """Validate if the barcode is a valid EAN-13."""
    if not barcode.isdigit() or len(barcode) != 13:
        return False
    
    # Check digit calculation
    total = 0
    for i in range(12):
        digit = int(barcode[i])
        total += digit if i % 2 == 0 else digit * 3
    
    check_digit = (10 - (total % 10)) % 10
    return check_digit == int(barcode[12])

def is_valid_upc(barcode: str) -> bool:
    """Validate if the barcode is a valid UPC-A."""
    if not barcode.isdigit() or len(barcode) != 12:
        return False
    
    # Check digit calculation
    total = 0
    for i in range(11):
        digit = int(barcode[i])
        total += digit if i % 2 == 1 else digit * 3
    
    check_digit = (10 - (total % 10)) % 10
    return check_digit == int(barcode[11])

def is_valid_isbn13(barcode: str) -> bool:
    """Validate if the barcode is a valid ISBN-13."""
    if not barcode.isdigit() or len(barcode) != 13 or not barcode.startswith('978') and not barcode.startswith('979'):
        return False
    
    # Same check as EAN-13
    return is_valid_ean13(barcode)

def is_valid_barcode(barcode: str) -> bool:
    """Check if a barcode is valid using multiple validation methods."""
    # Clean the barcode
    barcode = re.sub(r'\D', '', barcode)
    
    # Check common barcode formats
    if len(barcode) == 13:
        return is_valid_ean13(barcode)
    elif len(barcode) == 12:
        return is_valid_upc(barcode)
    elif len(barcode) == 8:  # EAN-8
        return True  # Simplified validation for EAN-8
    else:
        return False

# Local file functions
def read_file(file_path: str) -> List[str]:
    """Read barcode data from a local file (Excel, CSV, or TXT)."""
    try:
        file_ext = os.path.splitext(file_path)[1].lower()
        
        # Excel file (.xlsx or .xls)
        if file_ext in ['.xlsx', '.xls']:
            df = pd.read_excel(file_path, header=0)
            # Check if first column header contains 'barcode' (case insensitive)
            if df.columns[0].lower().find('barcode') >= 0:
                return df.iloc[:, 0].dropna().astype(str).tolist()
            else:
                print(f"Warning: First column doesn't seem to contain barcodes. Using it anyway.")
                return df.iloc[:, 0].dropna().astype(str).tolist()
        
        # CSV file
        elif file_ext == '.csv':
            df = pd.read_csv(file_path)
            if df.columns[0].lower().find('barcode') >= 0:
                return df.iloc[:, 0].dropna().astype(str).tolist()
            else:
                print(f"Warning: First column doesn't seem to contain barcodes. Using it anyway.")
                return df.iloc[:, 0].dropna().astype(str).tolist()
        
        # Text file with one barcode per line
        elif file_ext in ['.txt', '.text']:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Strip whitespace and filter out empty lines
            barcodes = [line.strip() for line in lines if line.strip()]
            
            # Check if first line might be a header
            if barcodes and barcodes[0].lower().find('barcode') >= 0:
                return barcodes[1:]
            else:
                return barcodes
        
        else:
            print(f"Unsupported file format: {file_ext}")
            return []
    
    except Exception as e:
        print(f"Error reading file {file_path}: {e}")
        return []

# Product data functions
def determine_unit(quantity_str: str) -> UnitEnum:
    """Determine unit from product quantity string."""
    if not quantity_str:
        return UnitEnum.PIECE
    
    quantity_lower = quantity_str.lower()
    
    if '100g' in quantity_lower:
        return UnitEnum.G100
    elif '200g' in quantity_lower:
        return UnitEnum.G200
    elif '250g' in quantity_lower:
        return UnitEnum.G250
    elif '500g' in quantity_lower:
        return UnitEnum.G500
    elif '1kg' in quantity_lower:
        return UnitEnum.KG1
    elif '100ml' in quantity_lower:
        return UnitEnum.ML100
    elif '200ml' in quantity_lower:
        return UnitEnum.ML200
    elif '500ml' in quantity_lower:
        return UnitEnum.ML500
    elif '1l' in quantity_lower:
        return UnitEnum.L1
    
    return UnitEnum.PIECE

def extract_features(product: Dict[str, Any]) -> List[str]:
    """Extract features from product data."""
    features = []
    
    if product.get('ingredients_text'):
        features.append('Contains detailed ingredients')
    
    if product.get('nutrition_grades'):
        features.append(f"Nutrition grade: {product['nutrition_grades'].upper()}")
    
    if product.get('ecoscore_grade'):
        features.append(f"Eco-score: {product['ecoscore_grade'].upper()}")
    
    if product.get('labels'):
        labels = product['labels'].split(',')
        features.extend([label.strip() for label in labels])
    
    return features

def extract_specifications(product: Dict[str, Any]) -> Dict[str, Any]:
    """Extract specifications from product data."""
    specs = {}
    
    if product.get('nutriments'):
        nutriments = product['nutriments']
        specs['nutrition'] = {
            'energy': nutriments.get('energy_100g', 0),
            'fat': nutriments.get('fat_100g', 0),
            'carbohydrates': nutriments.get('carbohydrates_100g', 0),
            'proteins': nutriments.get('proteins_100g', 0),
            'salt': nutriments.get('salt_100g', 0)
        }
    
    if product.get('ingredients'):
        ingredients_text = ', '.join([i.get('text', '') for i in product['ingredients']])
        specs['ingredients'] = ingredients_text
    
    if product.get('allergens_tags'):
        specs['allergens'] = [a.replace('en:', '') for a in product['allergens_tags']]
    
    return specs

def create_empty_product_template(barcode: str) -> Dict[str, Any]:
    """Create an empty product template."""
    return {
        'barcode': barcode,
        'productName': '',
        'description': '',
        'category': '',
        'productLine': '',
        'quantity': 0,
        'unit': UnitEnum.PIECE,
        'features': [],
        'specification': {},
        'brand': '',
        'productImage': '',
        'productIngredientImage': ''
    }

# Dictionary for known products that aren't found in APIs
KNOWN_PRODUCTS = {
    '8902102300687': {
        'productName': 'Henko Matic Detergent',
        'description': 'Top load detergent powder for washing machines',
        'category': 'Household supplies',
        'productLine': 'Henko Matic',
        'brand': 'Henko',
        'quantity': 500,
        'unit': UnitEnum.G500,
        'features': ['Front load compatible', 'Stain removal', 'Superior cleaning']
    },
    '8902102127574': {
        'productName': 'Jyothy Laboratories Product',
        'description': 'Household product from Jyothy Laboratories',
        'category': 'Household supplies',
        'brand': 'Jyothy Laboratories',
        'features': ['Cleaning product']
    }
    # Add more known products here as needed
}

# NEW FUNCTION: Web Search for Barcode
def search_web_for_barcode(barcode: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Search the web for information about a barcode and return structured results.
    
    Args:
        barcode: The barcode to search for
        max_results: Maximum number of search results to return
        
    Returns:
        List of dictionaries containing search results
    """
    try:
        # Use SerpAPI if API key is available
        serp_api_key = os.getenv('SERPAPI_KEY')
        if serp_api_key:
            print(f"Searching web for barcode {barcode} using SerpAPI...")
            
            search_query = f"barcode {barcode} product information"
            url = f"https://serpapi.com/search.json?q={quote_plus(search_query)}&api_key={serp_api_key}"
            
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                search_results = response.json()
                
                # Extract relevant information from search results
                results = []
                if 'organic_results' in search_results:
                    for result in search_results['organic_results'][:max_results]:
                        results.append({
                            'title': result.get('title', ''),
                            'link': result.get('link', ''),
                            'snippet': result.get('snippet', '')
                        })
                return results
            else:
                print(f"SerpAPI error: {response.status_code}")
        
        # Fall back to a simulated search if SerpAPI is not available
        print(f"Simulating web search for barcode {barcode}...")
        
        # Simulate search results based on barcode patterns
        results = []
        
        # Check if it's a book (ISBN)
        if barcode.startswith('978') or barcode.startswith('979'):
            results.append({
                'title': f"Book with ISBN {barcode}",
                'link': f"https://isbnsearch.org/isbn/{barcode}",
                'snippet': f"Information about book with ISBN {barcode}. Published books usually have publisher details, author information and publication date."
            })
        
        # Check if it's a product from certain regions based on GS1 prefixes
        elif barcode.startswith('00') or barcode.startswith('01'):  # USA/Canada
            results.append({
                'title': f"US/Canada Product {barcode}",
                'link': f"https://www.upcitemdb.com/upc/{barcode}",
                'snippet': f"Product information for UPC {barcode}. Manufactured in USA or Canada."
            })
        elif barcode.startswith('890'):  # India
            results.append({
                'title': f"Indian Product {barcode}",
                'link': f"https://www.barcodelookup.com/{barcode}",
                'snippet': f"Product manufactured in India with barcode {barcode}. FMCG or consumer goods."
            })
        elif barcode.startswith('50'):  # UK
            results.append({
                'title': f"UK Product {barcode}",
                'link': f"https://www.barcodelookup.com/{barcode}",
                'snippet': f"Product manufactured in UK with barcode {barcode}."
            })
        
        # Add general barcode lookup results
        results.append({
            'title': f"Barcode Lookup: {barcode}",
            'link': f"https://www.barcodelookup.com/{barcode}",
            'snippet': f"Find product details, specifications, and manufacturer information for item with barcode {barcode}."
        })
        
        results.append({
            'title': f"UPC Database: {barcode}",
            'link': f"https://www.upcdatabase.com/item/{barcode}",
            'snippet': f"UPC {barcode} lookup in universal product database. Find product name, category, and merchant information."
        })
        
        return results[:max_results]
        
    except Exception as e:
        print(f"Error during web search for barcode {barcode}: {e}")
        return []

def fetch_from_open_food_facts(barcode: str) -> Optional[Dict[str, Any]]:
    """Fetch product data from Open Food Facts API."""
    try:
        response = requests.get(f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json", timeout=10)
        data = response.json()
        
        if data.get('status') == 1:
            product = data['product']
            quantity_match = re.search(r'\d+', product.get('quantity', '0') or '0')
            quantity = int(quantity_match.group(0)) if quantity_match else 0
            
            return {
                'barcode': barcode,
                'productName': product.get('product_name', ''),
                'description': product.get('generic_name', ''),
                'category': product.get('categories_tags', [''])[0].replace('en:', '') if product.get('categories_tags') else '',
                'productLine': product.get('brands', ''),
                'quantity': quantity,
                'unit': determine_unit(product.get('quantity', '')),
                'features': extract_features(product),
                'specification': extract_specifications(product),
                'brand': product.get('brands', ''),
                'productImage': product.get('image_url', ''),
                'productIngredientImage': product.get('image_ingredients_url', '')
            }
        
        return None
    
    except Exception as e:
        print(f"Error fetching from Open Food Facts for barcode {barcode}: {e}")
        return None

# MODIFIED: Send web search results to AI APIs for processing
def fetch_from_ai_with_web_context(barcode: str, web_results: List[Dict[str, str]], 
                                  api_type: str = 'openai') -> Optional[Dict[str, Any]]:
    """Fetch product data using AI API with web search context.
    
    Args:
        barcode: The barcode to search for
        web_results: Web search results to provide as context
        api_type: Type of AI API to use ('openai' or 'deepseek')
        
    Returns:
        Dictionary containing product information or None
    """
    # Format web results as context
    context = "\n\n".join([
        f"Title: {result['title']}\nURL: {result['link']}\nDescription: {result['snippet']}"
        for result in web_results
    ])
    
    prompt = f"""Based on the barcode {barcode} and the following web search results, 
provide information about this product in a structured JSON format:

WEB SEARCH RESULTS:
{context}

Extract as much information as possible from these search results and format your response as a JSON
with these fields: productName, description, category, productLine, quantity, unit, features (as array), 
specification (as object), brand, productImage (URL if available), productIngredientImage (URL if available).

If information is not available or uncertain, use empty strings or default values but maintain the structure.
"""
    
    if api_type == 'deepseek':
        return fetch_from_deepseek_api(barcode, prompt)
    else:  # Default to OpenAI
        return fetch_from_openai_api(barcode, prompt)

# MODIFIED: DeepSeek API with custom prompt
def fetch_from_deepseek_api(barcode: str, custom_prompt: str = None) -> Optional[Dict[str, Any]]:
    """Fetch product data using DeepSeek API with optional custom prompt."""
    api_key = os.getenv('DEEPSEEK_API_KEY')
    if not api_key:
        print("No DeepSeek API key found in environment variables")
        return None
    
    # Check if DeepSeek API is disabled due to previous errors
    if hasattr(fetch_from_deepseek_api, 'disabled') and fetch_from_deepseek_api.disabled:
        print("DeepSeek API calls are disabled due to previous errors")
        return None
    
    try:
        # Use custom prompt if provided, otherwise use default
        if custom_prompt is None:
            prompt = f"I need product information for a barcode: {barcode}. Please provide all known details about this product in JSON format with these fields: productName, description, category, productLine, quantity, unit, features (as array), specification (as object), brand, productImage (URL if available), productIngredientImage (URL if available)."
        else:
            prompt = custom_prompt
            
        response = requests.post(
            'https://api.deepseek.com/v1/chat/completions',
            json={
                'model': 'deepseek-chat',
                'messages': [
                    {
                        'role': 'user',
                        'content': prompt
                    }
                ],
                'response_format': {'type': 'json_object'}
            },
            headers={
                'Content-Type': 'application/json',
                'Authorization': f"Bearer {api_key}"
            },
            timeout=30
        )
        
        if response.status_code != 200:
            print(f"DeepSeek API error: Status code {response.status_code}")
            print(f"Response: {response.text}")
            
            # If error indicates insufficient balance, disable further API calls
            if response.status_code == 402 or "Insufficient Balance" in response.text:
                print("DeepSeek API calls will be disabled for this session due to insufficient balance")
                fetch_from_deepseek_api.disabled = True
                
            return None
            
        data = response.json()
        if 'choices' not in data or not data['choices'] or 'message' not in data['choices'][0]:
            print(f"Unexpected DeepSeek API response format: {data}")
            return None
            
        try:
            result = json.loads(data['choices'][0]['message']['content'])
            result['barcode'] = barcode
            return result
        except json.JSONDecodeError as e:
            print(f"Error parsing DeepSeek response JSON: {e}")
            print(f"Raw content: {data['choices'][0]['message']['content']}")
            return None
    
    except Exception as e:
        print(f"Error fetching from DeepSeek for barcode {barcode}: {str(e)}")
        return None

# MODIFIED: OpenAI API with custom prompt
def fetch_from_openai_api(barcode: str, custom_prompt: str = None) -> Optional[Dict[str, Any]]:
    """Fetch product data using OpenAI API with optional custom prompt."""
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("No OpenAI API key found in environment variables")
        return None
    
    # Check if OpenAI API is disabled due to previous errors
    if hasattr(fetch_from_openai_api, 'disabled') and fetch_from_openai_api.disabled:
        print("OpenAI API calls are disabled due to previous errors")
        return None
    
    try:
        # Use custom prompt if provided, otherwise use default
        if custom_prompt is None:
            prompt = f"I need product information for a barcode: {barcode}. Please provide all known details about this product in JSON format with these fields: productName, description, category, productLine, quantity, unit, features (as array), specification (as object), brand, productImage (URL if available), productIngredientImage (URL if available)."
        else:
            prompt = custom_prompt
        
        # Try with GPT-3.5-turbo first, which is more widely available than GPT-4
        model = "gpt-3.5-turbo"
        print(f"Trying OpenAI API with model: {model}")
        
        response = requests.post(
            'https://api.openai.com/v1/chat/completions',
            json={
                'model': model,
                'messages': [
                    {
                        'role': 'user',
                        'content': prompt
                    }
                ],
                'response_format': {'type': 'json_object'}
            },
            headers={
                'Content-Type': 'application/json',
                'Authorization': f"Bearer {api_key}"
            },
            timeout=30
        )
        
        if response.status_code != 200:
            print(f"OpenAI API error with {model}: Status code {response.status_code}")
            print(f"Response: {response.text}")
            
            # If error indicates model not found or permission issues, disable API calls
            if "does not exist" in response.text or "access" in response.text:
                print("OpenAI API calls will be disabled for this session due to model access issues")
                fetch_from_openai_api.disabled = True
                
            return None
            
        data = response.json()
        if 'choices' not in data or not data['choices'] or 'message' not in data['choices'][0]:
            print(f"Unexpected OpenAI API response format: {data}")
            return None
            
        try:
            result = json.loads(data['choices'][0]['message']['content'])
            result['barcode'] = barcode
            return result
        except json.JSONDecodeError as e:
            print(f"Error parsing OpenAI response JSON: {e}")
            print(f"Raw content: {data['choices'][0]['message']['content']}")
            return None
    
    except Exception as e:
        print(f"Error fetching from OpenAI for barcode {barcode}: {str(e)}")
        return None

def fetch_from_known_products_db(barcode: str) -> Optional[Dict[str, Any]]:
    """Fetch product data from local known products database."""
    if barcode in KNOWN_PRODUCTS:
        # Create a complete product entry from our known product data
        product_template = create_empty_product_template(barcode)
        product_template.update(KNOWN_PRODUCTS[barcode])
        return product_template
    return None

# MODIFIED: Enhanced product data fetching workflow
def fetch_product_data(barcode: str, batch_mode: bool = False) -> Dict[str, Any]:
    """Fetch product data from external APIs based on barcode with web search first."""
    # Validate barcode before making API calls
    if not is_valid_barcode(barcode):
        print(f"Invalid barcode format: {barcode}")
        return create_empty_product_template(barcode)
    
    # First check our local database of known products
    product_data = fetch_from_known_products_db(barcode)
    if product_data:
        print(f"Found product data in local database for barcode {barcode}")
        return product_data
    
    # Try Open Food Facts API next
    product_data = fetch_from_open_food_facts(barcode)
    if product_data:
        print(f"Found product data in Open Food Facts for barcode {barcode}")
        return product_data
    
    # NEW WORKFLOW: Search the web for barcode information
    print(f"Searching the web for information on barcode {barcode}...")
    web_results = search_web_for_barcode(barcode)
    
    if web_results:
        print(f"Found {len(web_results)} web search results for barcode {barcode}")
        
        # Don't try AI APIs in batch mode with a lot of barcodes to avoid excessive costs
        if batch_mode and len(barcode) > 10000:
            print(f"Skipping AI API calls in batch mode for barcode {barcode}")
            return create_empty_product_template(barcode)
        
        # Send web search results to AI for processing
        # Try DeepSeek first
        print(f"Sending web search results to DeepSeek API for processing...")
        product_data = fetch_from_ai_with_web_context(barcode, web_results, api_type='deepseek')
        if product_data:
            print(f"Successfully processed web search results via DeepSeek for barcode {barcode}")
            return product_data
        
        # Try OpenAI as fallback
        print(f"Sending web search results to OpenAI API for processing...")
        product_data = fetch_from_ai_with_web_context(barcode, web_results, api_type='openai')
        if product_data:
            print(f"Successfully processed web search results via OpenAI for barcode {barcode}")
            return product_data
    
    # Web search fallback for Indian products (if no AI processing was successful)
    if barcode.startswith('890'):  # Indian product barcode prefix
        # Create a fallback product for Indian barcodes
        if '8902102' in barcode:  # Jyothy Labs prefix
            fallback_product = create_empty_product_template(barcode)
            fallback_product.update({
                'productName': 'Jyothy Laboratories Product',
                'description': 'Product from Jyothy Laboratories Limited',
                'category': 'Household/FMCG',
                'brand': 'Jyothy Laboratories',
                'features': ['Indian FMCG product']
            })
            print(f"Created fallback product info for barcode {barcode}")
            return fallback_product
    
    # Try traditional AI approaches as last resort if no web results or processing failed
    if not web_results or not product_data:
        # As a last resort, try AI APIs with default prompts
        # Try DeepSeek API if available
        product_data = fetch_from_deepseek_api(barcode)
        if product_data:
            print(f"Found product data via DeepSeek for barcode {barcode}")
            return product_data
        
        # Try OpenAI API if available
        product_data = fetch_from_openai_api(barcode)
        if product_data:
            print(f"Found product data via OpenAI for barcode {barcode}")
            return product_data
    
    # Return empty template if no data found
    print(f"No product data found for barcode {barcode}, using empty template")
    return create_empty_product_template(barcode)

def process_barcodes_in_batches(barcodes: List[str], batch_size: int = 100) -> List[Dict[str, Any]]:
    """Process barcodes in batches to handle large datasets."""
    results = []
    total_barcodes = len(barcodes)
    
    for i in range(0, total_barcodes, batch_size):
        batch = barcodes[i:i+batch_size]
        print(f"Processing batch {i//batch_size + 1}/{(total_barcodes-1)//batch_size + 1} ({len(batch)} barcodes)")
        
        for j, barcode in enumerate(batch):
            print(f"  Processing barcode {barcode} ({j+1}/{len(batch)})...")
            product_data = fetch_product_data(barcode, batch_mode=True)
            results.append(product_data)
            
            # Add a small delay to avoid hitting API rate limits
            time.sleep(0.5)
        
        # Save intermediate results after each batch
        with open(f'product_data_batch_{i//batch_size + 1}.json', 'w', encoding='utf-8') as f:
            json.dump(results[-len(batch):], f, ensure_ascii=False, indent=2)
    
    return results

def main():
    """Main function to run the script."""
    try:
        # Check if required environment variables are set
        input_file = os.getenv('INPUT_FILE')
        if not input_file:
            # If not set in env, ask user for file
            input_file = input("Enter path to the file containing barcodes: ").strip()
            if not input_file or not os.path.exists(input_file):
                raise ValueError(f"Input file not found: {input_file}")
        
        print(f'Reading barcodes from {input_file}...')
        barcodes = read_file(input_file)
        
        if not barcodes:
            print('No barcodes found in the file')
            return
        
        print(f'Found {len(barcodes)} barcodes. Validating barcodes...')
        
        # Validate barcodes before processing
        valid_barcodes = []
        invalid_barcodes = []
        
        for barcode in barcodes:
            if is_valid_barcode(barcode):
                valid_barcodes.append(barcode)
            else:
                invalid_barcodes.append(barcode)
        
        print(f'Validation complete: {len(valid_barcodes)} valid barcodes, {len(invalid_barcodes)} invalid barcodes')
        
        if invalid_barcodes:
            print('Saving list of invalid barcodes...')
            with open('invalid_barcodes.json', 'w', encoding='utf-8') as f:
                json.dump(invalid_barcodes, f, indent=2)
        
        if not valid_barcodes:
            print('No valid barcodes to process')
            return
        
        print(f'Fetching product data for {len(valid_barcodes)} valid barcodes...')
        
        # Process barcodes in batches
        batch_size = 100  # Adjust based on your needs
        results = process_barcodes_in_batches(valid_barcodes, batch_size)
        
        # Save final results
        with open('product_data.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        print(f'Product data saved to product_data.json')
        
        # Save results as CSV for easier viewing
        df = pd.DataFrame(results)
        df.to_csv('product_data.csv', index=False)
        print(f'Product data also saved to product_data.csv')
        
    except Exception as e:
        print(f'Error running the script: {e}')

# Function to test a single barcode lookup (useful for debugging)
def test_single_barcode(barcode: str) -> None:
    """Test the barcode lookup process with a single barcode."""
    print(f"Testing barcode lookup for: {barcode}")
    
    if not is_valid_barcode(barcode):
        print(f"Invalid barcode format: {barcode}")
        return
    
    print("Step 1: Checking local database...")
    product = fetch_from_known_products_db(barcode)
    if product:
        print("Found in local database!")
        print(json.dumps(product, indent=2))
        return
    
    print("Step 2: Checking Open Food Facts...")
    product = fetch_from_open_food_facts(barcode)
    if product:
        print("Found in Open Food Facts!")
        print(json.dumps(product, indent=2))
        return
    
    print("Step 3: Searching the web...")
    web_results = search_web_for_barcode(barcode)
    if web_results:
        print(f"Found {len(web_results)} web search results:")
        for i, result in enumerate(web_results):
            print(f"\nResult {i+1}:")
            print(f"Title: {result['title']}")
            print(f"Link: {result['link']}")
            print(f"Snippet: {result['snippet']}")
        
        print("\nStep 4: Processing web search results with DeepSeek API...")
        product = fetch_from_ai_with_web_context(barcode, web_results, api_type='deepseek')
        if product:
            print("Successfully processed web results with DeepSeek!")
            print(json.dumps(product, indent=2))
            return
        
        print("\nStep 5: Processing web search results with OpenAI API...")
        product = fetch_from_ai_with_web_context(barcode, web_results, api_type='openai')
        if product:
            print("Successfully processed web results with OpenAI!")
            print(json.dumps(product, indent=2))
            return
    
    print("\nStep 6: Trying direct AI lookup without web context...")
    product = fetch_from_deepseek_api(barcode)
    if product:
        print("Found with DeepSeek API!")
        print(json.dumps(product, indent=2))
        return
    
    product = fetch_from_openai_api(barcode)
    if product:
        print("Found with OpenAI API!")
        print(json.dumps(product, indent=2))
        return
    
    print("\nNo product data found. Using empty template.")
    print(json.dumps(create_empty_product_template(barcode), indent=2))

if __name__ == '__main__':
    # Check if in test mode
    if os.getenv('TEST_MODE') == 'true':
        test_barcode = os.getenv('TEST_BARCODE')
        if test_barcode:
            test_single_barcode(test_barcode)
        else:
            print("TEST_MODE enabled but no TEST_BARCODE provided.")
            print("Please set TEST_BARCODE environment variable.")
    else:
        main()