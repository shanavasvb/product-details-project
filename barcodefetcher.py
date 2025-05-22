#!/usr/bin/env python3
import os
import json
import pandas as pd
import requests
from dotenv import load_dotenv
import time
import logging
import sys
from tqdm import tqdm
from bs4 import BeautifulSoup
import re
from urllib.parse import quote_plus

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("barcode_processing.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

class BarcodeFetcher:
    def __init__(self):
        """Initialize the BarcodeFetcher with API keys and settings."""
        # API keys
        self.serpapi_key = os.getenv("SERPAPI_KEY")
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.digiteyes_app_key = os.getenv("DIGITEYES_APP_KEY")  # Optional for Digit-Eyes
        self.digiteyes_signature = os.getenv("DIGITEYES_SIGNATURE")  # Optional for Digit-Eyes
        
        # Input/output configuration
        self.input_file = os.getenv("INPUT_FILE")
        self.output_file = os.getenv("OUTPUT_FILE", "barcode_results.json")
        
        # API rate limiting parameters
        self.api_request_delay = float(os.getenv("API_REQUEST_DELAY", "1.0"))  # Default: 1 second between requests
        self.max_retries = int(os.getenv("MAX_RETRIES", "3"))  # Default: 3 retries
        self.max_daily_requests = int(os.getenv("MAX_DAILY_REQUESTS", "10000"))  # Default: 10,000 per day
        self.request_count = 0
        
        # User agent for web scraping
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        
        # Last successful entry
        self.last_successful_entry = None
        
        # Load processed barcodes to avoid reprocessing
        self.processed_barcodes = self.load_processed_barcodes()
        
    def load_processed_barcodes(self):
        """Load set of already processed barcodes to avoid reprocessing."""
        processed = set()
        if os.path.exists(self.output_file):
            try:
                with open(self.output_file, 'r') as f:
                    data = json.load(f)
                    for entry in data:
                        processed.add(entry.get('barcode'))
                logger.info(f"Loaded {len(processed)} previously processed barcodes")
            except json.JSONDecodeError:
                logger.warning(f"Couldn't parse existing results file: {self.output_file}")
        return processed

    def is_valid_barcode(self, barcode):
        """Validate barcode format: must be numeric and minimum 8 digits."""
        if not barcode or not isinstance(barcode, str):
            return False
        
        # Clean the barcode string
        barcode = barcode.strip()
        
        # Check if the barcode is numeric and has at least 8 digits
        if not barcode.isdigit() or len(barcode) < 8:
            return False
            
        return True
        
    def read_barcodes_from_excel(self, file_path):
        """Read barcodes from an Excel file with a single 'barcode' column."""
        try:
            # Read Excel file
            df = pd.read_excel(file_path)
            
            if df.empty:
                logger.error("Excel file is empty")
                return []
            
            # Check if 'barcode' column exists
            if 'barcode' not in df.columns:
                logger.error("No 'barcode' column found in Excel file")
                return []
            
            # Convert barcodes to strings and clean them
            barcodes = df['barcode'].astype(str).str.strip()
            
            # Remove '.0' suffix that can appear when Excel stores numbers
            barcodes = barcodes.str.replace('.0$', '', regex=True)
            
            # Filter out invalid barcodes
            valid_barcodes = []
            invalid_count = 0
            
            for barcode in barcodes:
                if self.is_valid_barcode(barcode):
                    valid_barcodes.append(barcode)
                else:
                    invalid_count += 1
            
            logger.info(f"Read {len(valid_barcodes)} valid barcodes. Found {invalid_count} invalid barcodes.")
            return valid_barcodes
            
        except Exception as e:
            logger.error(f"Error reading Excel file: {e}")
            return []
            
    def search_google_for_barcode(self, barcode):
        """Search Google for barcode information using SerpAPI."""
        if not self.serpapi_key:
            logger.warning("SerpAPI key not provided, skipping Google search")
            return None
            
        try:
            # SerpAPI endpoint
            url = "https://serpapi.com/search"
            
            # Query parameters
            params = {
                "api_key": self.serpapi_key,
                "q": f"{barcode} product bigbasket", # Search for barcode + bigbasket
                "google_domain": "google.co.in",  # Use Google India for BigBasket results
                "gl": "in",  # Geographic location: India
                "hl": "en",  # Language: English
                "num": 10    # Number of results
            }
            
            # Make the request
            response = requests.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                # Extract organic search results
                results = data.get("organic_results", [])
                
                # Check for BigBasket links first
                bigbasket_results = [r for r in results if "bigbasket" in r.get("link", "")]
                
                if bigbasket_results:
                    return bigbasket_results[0].get("link")
                
                # If no BigBasket links, return first result
                if results:
                    return results[0].get("link")
                    
            return None
            
        except Exception as e:
            logger.error(f"Error during Google search for barcode {barcode}: {e}")
            return None
            
    def extract_bigbasket_info(self, url):
        """Extract product information from BigBasket website."""
        try:
            headers = {
                'User-Agent': self.user_agent
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Initialize product info
                product_info = {}
                
                # Extract product name
                product_name_elem = soup.select_one('h1.GrE04')
                if product_name_elem:
                    product_info['name'] = product_name_elem.text.strip()
                
                # Extract brand
                brand_elem = soup.select_one('a.Tq74c')
                if brand_elem:
                    product_info['brand'] = brand_elem.text.strip()
                
                # Extract price
                price_elem = soup.select_one('td.IyLvo')
                if price_elem:
                    product_info['price'] = price_elem.text.strip()
                
                # Extract description
                desc_elem = soup.select_one('div[data-qa="product-about"]')
                if desc_elem:
                    product_info['description'] = desc_elem.text.strip()
                
                # Extract ingredients or specifications
                specs_elems = soup.select('div.h9mIE')
                if specs_elems:
                    specs = {}
                    for elem in specs_elems:
                        key_elem = elem.select_one('div:nth-child(1)')
                        val_elem = elem.select_one('div:nth-child(2)')
                        if key_elem and val_elem:
                            key = key_elem.text.strip()
                            val = val_elem.text.strip()
                            specs[key] = val
                    
                    if specs:
                        product_info['specifications'] = specs
                
                # Extract categories
                breadcrumb_elems = soup.select('a.FY3Oe')
                if breadcrumb_elems:
                    categories = [elem.text.strip() for elem in breadcrumb_elems]
                    if categories:
                        product_info['categories'] = categories
                
                return product_info if product_info else None
                
            return None
            
        except Exception as e:
            logger.error(f"Error extracting info from BigBasket: {e}")
            return None
            
    def get_product_from_digiteyes(self, barcode):
        """Use direct Digit-Eyes API to retrieve product information."""
        try:
            # Digit-Eyes direct API endpoint
            url = "https://www.digit-eyes.com/gtin/v2_0/"
            
            # Parameters for the API call
            params = {
                'upcCode': barcode,
                'language': 'en'
            }
            
            # Add API credentials if available
            app_key = os.getenv('DIGITEYES_APP_KEY')
            signature = os.getenv('DIGITEYES_SIGNATURE')
            
            if app_key and signature:
                params['app_key'] = app_key
                params['signature'] = signature
            
            # Make the request
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    
                    # Check if product was found
                    if data and not data.get('error'):
                        result = {
                            "barcode": barcode,
                            "source": "digiteyes_api"
                        }
                        
                        # Extract available fields from JSON response
                        if data.get('product_name'):
                            result["name"] = data.get('product_name')
                            
                        if data.get('brand_name'):
                            result["brand"] = data.get('brand_name')
                            
                        if data.get('description'):
                            result["description"] = data.get('description')
                            
                        if data.get('ingredients'):
                            result["ingredients"] = data.get('ingredients')
                            
                        if data.get('nutrition_facts'):
                            result["nutrition_facts"] = data.get('nutrition_facts')
                            
                        if data.get('manufacturer'):
                            result["manufacturer"] = data.get('manufacturer')
                            
                        if data.get('category'):
                            result["category"] = data.get('category')
                            
                        # Return result only if it has meaningful data
                        if len(result) > 2:  # More than just barcode and source
                            return result
                            
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse JSON response from Digit-Eyes for barcode {barcode}")
                    return None
                        
            return None
            
        except Exception as e:
            logger.error(f"Error retrieving product from Digit-Eyes API: {e}")
            return None
            
    def get_product_from_openai(self, barcode):
        """Use OpenAI to retrieve product information based on barcode."""
        if not self.openai_api_key:
            return None
            
        try:
            import openai
            openai.api_key = self.openai_api_key
            
            system_prompt = """You are a barcode lookup assistant. 
            Given a barcode number, provide any product information you know about it in JSON format.
            Include only fields you are certain about. If you don't know, return an empty JSON object."""
            
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"What product information do you have about barcode {barcode}?"}
                ],
                temperature=0.3
            )
            
            # Extract the response
            try:
                content = response.choices[0].message.content
                # Attempt to parse JSON from the response
                import re
                json_match = re.search(r'```json\n(.*?)\n```', content, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_str = content
                    
                data = json.loads(json_str)
                
                # If we got meaningful data back
                if data and any(key not in ["barcode", "source"] for key in data.keys()):
                    data["barcode"] = barcode
                    data["source"] = "openai"
                    return data
            except:
                pass
                
            return None
            
        except Exception as e:
            logger.error(f"Error retrieving product from OpenAI: {e}")
            return None
            
    def get_product_from_deepseek(self, barcode):
        """Use DeepSeek to retrieve product information based on barcode."""
        if not self.deepseek_api_key:
            return None
            
        try:
            import requests
            
            url = "https://api.deepseek.com/v1/chat/completions"
            
            headers = {
                "Authorization": f"Bearer {self.deepseek_api_key}",
                "Content-Type": "application/json"
            }
            
            system_prompt = """You are a barcode lookup assistant. 
            Given a barcode number, provide any product information you know about it in JSON format.
            Include only fields you are certain about. If you don't know, return an empty JSON object."""
            
            data = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"What product information do you have about barcode {barcode}?"}
                ],
                "temperature": 0.3
            }
            
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 200:
                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                
                # Attempt to parse JSON from the response
                try:
                    import re
                    json_match = re.search(r'```json\n(.*?)\n```', content, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(1)
                    else:
                        json_str = content
                        
                    data = json.loads(json_str)
                    
                    # If we got meaningful data back
                    if data and any(key not in ["barcode", "source"] for key in data.keys()):
                        data["barcode"] = barcode
                        data["source"] = "deepseek"
                        return data
                except:
                    pass
                    
            return None
            
        except Exception as e:
            logger.error(f"Error retrieving product from DeepSeek: {e}")
            return None

    def get_product_info_from_openfoodfacts(self, barcode):
        """Query the Open Food Facts API for product information."""
        try:
            url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("status") == 1:
                    product = data.get("product", {})
                    
                    # Only include non-null values in the result
                    result = {"barcode": barcode}
                    
                    # Map fields from API response, only including non-empty values
                    fields_mapping = {
                        "name": ["product_name", "product_name_en"],
                        "brand": ["brands"],
                        "description": ["generic_name", "generic_name_en"],
                        "ingredients": ["ingredients_text", "ingredients_text_en"]
                    }
                    
                    # Add basic product info
                    for field, api_fields in fields_mapping.items():
                        for api_field in api_fields:
                            value = product.get(api_field)
                            if value and str(value).strip():
                                result[field] = value
                                break
                    
                    # Add nutrition facts if available
                    nutrition = product.get("nutriments", {})
                    if nutrition:
                        nutrients = {}
                        # Map nutrition data
                        nutrient_mapping = {
                            "serving_size": product.get("serving_size"),
                            "calories": nutrition.get("energy-kcal_100g"),
                            "protein": nutrition.get("proteins_100g"),
                            "carbohydrates": nutrition.get("carbohydrates_100g"),
                            "fat": nutrition.get("fat_100g"),
                            "sugars": nutrition.get("sugars_100g"),
                            "fiber": nutrition.get("fiber_100g"),
                            "salt": nutrition.get("salt_100g")
                        }
                        
                        # Only add non-null nutrition values
                        for nutrient, value in nutrient_mapping.items():
                            if value is not None:
                                nutrients[nutrient] = value
                        
                        if nutrients:
                            result["nutrition_facts"] = nutrients
                    
                    # Add allergens if available
                    allergens = product.get("allergens_tags", [])
                    if allergens:
                        # Clean up allergen format (remove 'en:' prefix)
                        clean_allergens = [a.replace('en:', '') for a in allergens]
                        if clean_allergens:
                            result["allergens"] = clean_allergens
                    
                    # Only return the result if it has data beyond just the barcode
                    if len(result) > 1:  # More than just the barcode
                        result["source"] = "openfoodfacts"
                        return result
                        
            return None
                
        except requests.RequestException as e:
            logger.error(f"Request error for barcode {barcode}: {e}")
            return None
            
        except Exception as e:
            logger.error(f"Unexpected error processing barcode {barcode}: {e}")
            return None

    def get_product_info(self, barcode):
        """Get product information using multiple methods."""
        if self.request_count >= self.max_daily_requests:
            logger.error("Daily API request limit reached")
            return None
            
        # Check if we've already processed this barcode
        if barcode in self.processed_barcodes:
            logger.info(f"Barcode {barcode} already processed, skipping")
            return None
        
        # Increment request counter
        self.request_count += 1
        
        # Try multiple methods in sequence, from fastest/cheapest to most complex
        
        # 1. First try Open Food Facts (free, fast)
        logger.info(f"Trying Open Food Facts for barcode {barcode}")
        product_info = self.get_product_info_from_openfoodfacts(barcode)
        if product_info:
            logger.info(f"Found product info from Open Food Facts")
            self.last_successful_entry = product_info
            return product_info
            
        # Add delay between API calls
        time.sleep(self.api_request_delay)
        
        # 2. Try DigitEyes API (free with RapidAPI)
        logger.info(f"Trying DigitEyes API for barcode {barcode}")
        product_info = self.get_product_from_digiteyes(barcode)
        if product_info:
            logger.info(f"Found product info from DigitEyes API")
            self.last_successful_entry = product_info
            return product_info
            
        # Add delay between API calls
        time.sleep(self.api_request_delay)
        
        # 3. Try Google search + BigBasket scraping
        logger.info(f"Searching Google for barcode {barcode}")
        url = self.search_google_for_barcode(barcode)
        
        if url and "bigbasket" in url:
            logger.info(f"Found BigBasket URL, extracting product info")
            bigbasket_info = self.extract_bigbasket_info(url)
            
            if bigbasket_info:
                bigbasket_info["barcode"] = barcode
                bigbasket_info["source"] = "bigbasket"
                logger.info(f"Successfully extracted product info from BigBasket")
                self.last_successful_entry = bigbasket_info
                return bigbasket_info
        
        # Add delay between API calls
        time.sleep(self.api_request_delay)
        
        # 4. Try DeepSeek (if available)
        if self.deepseek_api_key:
            logger.info(f"Trying DeepSeek for barcode {barcode}")
            product_info = self.get_product_from_deepseek(barcode)
            if product_info:
                logger.info(f"Found product info from DeepSeek")
                self.last_successful_entry = product_info
                return product_info
                
        # Add delay between API calls
        time.sleep(self.api_request_delay)
        
        # 5. Try OpenAI (if available)
        if self.openai_api_key:
            logger.info(f"Trying OpenAI for barcode {barcode}")
            product_info = self.get_product_from_openai(barcode)
            if product_info:
                logger.info(f"Found product info from OpenAI")
                self.last_successful_entry = product_info
                return product_info
                
        logger.warning(f"Could not find product info for barcode {barcode} using any method")
        return None

    def save_results(self, results):
        """Save results to JSON file, only including non-null entries."""
        try:
            # Only save non-empty results
            valid_results = [r for r in results if r and len(r) > 1]  # More than just the barcode
            
            with open(self.output_file, 'w', encoding='utf-8') as f:
                json.dump(valid_results, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved {len(valid_results)} product entries to {self.output_file}")
        except Exception as e:
            logger.error(f"Error saving results: {e}")
            # If save fails, print the last successful entry
            if self.last_successful_entry:
                logger.info(f"Last successfully processed entry: {json.dumps(self.last_successful_entry)}")

    def process_barcodes(self):
        """Process barcodes from Excel file and fetch product information."""
        if not self.input_file:
            self.input_file = input("Enter path to Excel file with barcodes: ")
            
        # Read barcodes from Excel
        barcodes = self.read_barcodes_from_excel(self.input_file)
        
        if not barcodes:
            logger.error("No valid barcodes found to process")
            return
            
        logger.info(f"Starting to process {len(barcodes)} barcodes")
        
        # Initialize results list with existing results
        results = []
        if os.path.exists(self.output_file):
            try:
                with open(self.output_file, 'r') as f:
                    results = json.load(f)
            except json.JSONDecodeError:
                pass
        
        # Track processed barcodes to avoid duplicates
        processed_set = {r.get('barcode') for r in results}
        
        # Process each barcode with progress bar
        try:
            for barcode in tqdm(barcodes, desc="Processing barcodes"):
                # Skip if already processed
                if barcode in processed_set:
                    continue
                    
                # Get product info
                product_info = self.get_product_info(barcode)
                
                # Only add non-null product info to results
                if product_info and len(product_info) > 1:  # Has more than just the barcode
                    results.append(product_info)
                    processed_set.add(barcode)
                    
                    # Save results periodically (every 50 barcodes)
                    if len(results) % 50 == 0:
                        self.save_results(results)
                
        except KeyboardInterrupt:
            logger.warning("Process interrupted by user")
        except Exception as e:
            logger.error(f"Error during processing: {e}")
        finally:
            # Save final results
            self.save_results(results)
            
            # Display last successful entry
            if self.last_successful_entry:
                logger.info("Last successfully processed entry:")
                logger.info(json.dumps(self.last_successful_entry, indent=2))
            else:
                logger.warning("No entries were successfully processed")


def main():
    """Main function to run the barcode fetcher."""
    fetcher = BarcodeFetcher()
    fetcher.process_barcodes()


if __name__ == "__main__":
    main()