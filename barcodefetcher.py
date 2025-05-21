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
        
        # Input/output configuration
        self.input_file = os.getenv("INPUT_FILE")
        self.output_file = os.getenv("OUTPUT_FILE", "barcode_results.json")
        
        # API rate limiting parameters
        self.api_request_delay = float(os.getenv("API_REQUEST_DELAY", "1.0"))  # Default: 1 second between requests
        self.max_retries = int(os.getenv("MAX_RETRIES", "3"))  # Default: 3 retries
        self.max_daily_requests = int(os.getenv("MAX_DAILY_REQUESTS", "10000"))  # Default: 10,000 per day
        self.request_count = 0
        
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

    def get_product_info(self, barcode):
        """Get product information from Open Food Facts API with proper error handling."""
        if self.request_count >= self.max_daily_requests:
            logger.error("Daily API request limit reached")
            return None
            
        # Check if we've already processed this barcode
        if barcode in self.processed_barcodes:
            logger.info(f"Barcode {barcode} already processed, skipping")
            return None
            
        for attempt in range(self.max_retries):
            try:
                # Increment request counter
                self.request_count += 1
                
                # Make the API request
                url = f"https://world.openfoodfacts.org/api/v0/product/{barcode}.json"
                response = requests.get(url, timeout=10)
                
                # Respect API rate limits
                time.sleep(self.api_request_delay)
                
                # Check if the request was successful
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
                            self.last_successful_entry = result
                            return result
                        else:
                            logger.info(f"No meaningful data found for barcode {barcode}")
                            return None
                    else:
                        logger.info(f"Product not found for barcode {barcode}")
                        return None
                        
                elif response.status_code == 429:  # Too Many Requests
                    retry_after = int(response.headers.get('Retry-After', self.api_request_delay * 5))
                    logger.warning(f"Rate limit hit. Waiting {retry_after} seconds before retry.")
                    time.sleep(retry_after)
                else:
                    logger.warning(f"API request failed with status code {response.status_code}")
                    
            except requests.RequestException as e:
                logger.error(f"Request error for barcode {barcode}: {e}")
                time.sleep(self.api_request_delay * (attempt + 1))  # Exponential backoff
                
            except Exception as e:
                logger.error(f"Unexpected error processing barcode {barcode}: {e}")
                return None
                
        logger.error(f"Failed to get product info for barcode {barcode} after {self.max_retries} retries")
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
                    
                    # Save results periodically (every 100 barcodes)
                    if len(results) % 100 == 0:
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