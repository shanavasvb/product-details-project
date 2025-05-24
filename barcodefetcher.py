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
import argparse
import pickle


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
    
        # Progress tracking
        self.last_processed_index = 0
        self.attempted_barcodes = set()
    
        # Load processed barcodes to avoid reprocessing
        self.processed_barcodes = self.load_processed_barcodes()
    
        # Load progress state
        self.load_progress_state()
    
        # Starting barcode (will be set by command-line argument if provided)
        self.start_barcode = None

        
        # Define unit conversion mapping
        self.unit_mapping = {
            "kg": "kg",
            "g": "gm",
            "gm": "gm",
            "gram": "gm",
            "grams": "gm",
            "ml": "ml",
            "l": "ltr",
            "liter": "ltr",
            "litre": "ltr",
            "ltr": "ltr",
            "piece": "pc",
            "pieces": "pc",
            "pcs": "pc",
            "pc": "pc",
            "pack": "pack"
        }
        
    def load_processed_barcodes(self):
        """Load set of already processed barcodes to avoid reprocessing."""
        processed = set()
        if os.path.exists(self.output_file):
            try:
                with open(self.output_file, 'r') as f:
                    data = json.load(f)
                    for entry in data:
                        processed.add(entry.get('Barcode'))
                logger.info(f"Loaded {len(processed)} previously processed barcodes")
            except json.JSONDecodeError:
                logger.warning(f"Couldn't parse existing results file: {self.output_file}")
        return processed
    def load_progress_state(self):
     """Load the last processed barcode and attempted barcodes from a pickle file."""
     progress_file = "barcode_progress.pkl"
     if os.path.exists(progress_file):
        try:
            with open(progress_file, 'rb') as f:
                progress_data = pickle.load(f)
                self.last_processed_index = progress_data.get('last_index', 0)
                self.attempted_barcodes = progress_data.get('attempted_barcodes', set())
                logger.info(f"Loaded progress state: last index {self.last_processed_index}, {len(self.attempted_barcodes)} attempted barcodes")
                return True
        except Exception as e:
            logger.error(f"Error loading progress state: {e}")
    
     # Initialize with default values if no file found or error occurred
     self.last_processed_index = 0
     self.attempted_barcodes = set()
     return False

    def save_progress_state(self, current_index, attempted_barcodes):
     """Save the current progress state to a pickle file."""
     progress_file = "barcode_progress.pkl"
     try:
        progress_data = {
            'last_index': current_index,
            'attempted_barcodes': attempted_barcodes
        }
        with open(progress_file, 'wb') as f:
            pickle.dump(progress_data, f)
        logger.info(f"Saved progress state: index {current_index}")
     except Exception as e:
        logger.error(f"Error saving progress state: {e}")
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
            
            # Find barcode column (case-insensitive)
            barcode_column = None
            possible_columns = ['barcode', 'Barcode', 'BARCODE', 'code', 'Code', 'upc', 'UPC', 'ean', 'EAN']
            
            for col in possible_columns:
                if col in df.columns:
                    barcode_column = col
                    break
            
            if barcode_column is None:
                logger.error(f"No barcode column found in Excel file. Available columns: {list(df.columns)}")
                return []
            
            logger.info(f"Using column '{barcode_column}' for barcodes")
            
            # Convert barcodes to strings and clean them
            barcodes = df[barcode_column].astype(str).str.strip()
            
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
     """Search Google for barcode information using SerpAPI and return search results."""
     if not self.serpapi_key:
        logger.warning("SerpAPI key not provided, skipping Google search")
        return None, None
        
     try:
        # SerpAPI endpoint
        url = "https://serpapi.com/search"
        
        # Query parameters - search for multiple sites to increase chances of finding the product
        sites = ["bigbasket.com", "amazon.in", "flipkart.com", "jiomart.com"]
        sites_query = " OR ".join([f"site:{site}" for site in sites])
        
        params = {
            "api_key": self.serpapi_key,
            "q": f"{barcode} product ({sites_query})",
            "google_domain": "google.co.in",
            "gl": "in",
            "hl": "en",
            "num": 15
        }
        
        # Make the request
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            
            # Extract organic search results
            results = data.get("organic_results", [])
            
            # Store search results information
            search_results_info = {}
            
            if results:
                # Extract search information
                search_results_info = {
                    "titles": [result.get("title", "") for result in results if result.get("title")],
                    "snippets": [result.get("snippet", "") for result in results if result.get("snippet")],
                    "links": [result.get("link", "") for result in results if result.get("link")]
                }
                
                # Check for e-commerce site links
                for site in sites:
                    site_results = [r for r in results if site in r.get("link", "")]
                    if site_results:
                        return site_results[0].get("link"), search_results_info
                
                # If no specific e-commerce site links found, return first result
                if results:
                    return results[0].get("link"), search_results_info
                
        return None, None
        
     except Exception as e:
        logger.error(f"Error during Google search for barcode {barcode}: {e}")
        return None, None
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
        # Transform to the desired format before returning
        transformed_info = self.transform_to_desired_format(product_info, barcode)
        self.last_successful_entry = transformed_info
        return transformed_info
        
     # Add delay between API calls
     time.sleep(self.api_request_delay)
    
     # 2. Try DigitEyes API
     logger.info(f"Trying DigitEyes API for barcode {barcode}")
     product_info = self.get_product_from_digiteyes(barcode)
     if product_info:
        logger.info(f"Found product info from DigitEyes API")
        # Transform to the desired format before returning
        transformed_info = self.transform_to_desired_format(product_info, barcode)
        self.last_successful_entry = transformed_info
        return transformed_info
        
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
            # Transform to the desired format before returning
            transformed_info = self.transform_to_desired_format(bigbasket_info, barcode)
            self.last_successful_entry = transformed_info
            return transformed_info
    
     # Add delay between API calls
     time.sleep(self.api_request_delay)
    
     # 4. Try DeepSeek (if available)
     if self.deepseek_api_key:
        logger.info(f"Trying DeepSeek for barcode {barcode}")
        product_info = self.get_product_from_deepseek(barcode)
        if product_info:
            logger.info(f"Found product info from DeepSeek")
            # Transform to the desired format before returning
            transformed_info = self.transform_to_desired_format(product_info, barcode)
            self.last_successful_entry = transformed_info
            return transformed_info
            
     # Add delay between API calls
     time.sleep(self.api_request_delay)
    
     # 5. Try OpenAI (if available)
     if self.openai_api_key:
        logger.info(f"Trying OpenAI for barcode {barcode}")
        product_info = self.get_product_from_openai(barcode)
        if product_info:
            logger.info(f"Found product info from OpenAI")
            # Transform to the desired format before returning
            transformed_info = self.transform_to_desired_format(product_info, barcode)
            self.last_successful_entry = transformed_info
            return transformed_info
            
     logger.warning(f"Could not find product info for barcode {barcode} using any method")
     return None
    def extract_product_name_from_search_results(self, search_results_info):
        """Extract potential product name and brand from search results."""
        if not search_results_info:
            return None, None
        
        # Look for patterns in titles that might indicate product names
        product_name = None
        brand = None
        
        # Common brand names to look for
        common_brands = ["Exo", "Ujala", "Surf", "Ariel", "Vim", "Harpic", "Dettol", "Lifebuoy", 
                        "Amul", "Nestle", "Colgate", "Pepsodent", "Patanjali", "Dabur"]
        
        # Check titles first
        for title in search_results_info.get("titles", []):
            # Try to extract brand name
            for potential_brand in common_brands:
                if potential_brand in title:
                    brand = potential_brand
                    break
            
            # Look for typical product listing pattern: Brand Product Name - Website
            parts = title.split(' - ')
            if len(parts) >= 2:
                product_name = parts[0].strip()
                break
            
            # Or just use the full title if it's not too long
            if not product_name and len(title) < 80:
                product_name = title
                break
        
        # Fall back to snippets if no product name found
        if not product_name:
            for snippet in search_results_info.get("snippets", []):
                # Look for product mentions
                if "product" in snippet.lower() or any(b in snippet for b in common_brands):
                    lines = snippet.split('. ')
                    if lines:
                        product_name = lines[0].strip()
                        break
        
        return product_name, brand

    def standardize_unit(self, unit):
     """Standardize unit names."""
     unit = unit.lower().strip()
    
     if unit in ['g', 'gm', 'gram', 'grams']:
        return 'g'
     elif unit in ['kg', 'kilo', 'kilos', 'kilogram', 'kilograms']:
        return 'kg'
     elif unit in ['ml', 'milliliter', 'millilitre', 'milliliters', 'millilitres']:
        return 'ml'
     elif unit in ['l', 'ltr', 'lt', 'litre', 'liter', 'litres', 'liters']:
        return 'l'
     elif unit in ['pc', 'pcs', 'piece', 'pieces', 'unit', 'units']:
        return 'pc'
     elif unit in ['pack', 'pkt', 'packet']:
        return 'pack'
     else:
        return unit

    
            
    def extract_product_info_from_url(self, url):
        """Extract product information from a website URL."""
        try:
            headers = {
                'User-Agent': self.user_agent
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Initialize product info
                product_info = {}
                
                # Try to find product name - this is a broader selector
                product_name_candidates = [
                    soup.select_one('h1'),  # Generic h1
                    soup.select_one('h1.product-name'),  # Common class name
                    soup.select_one('h1.product-title'),
                    soup.select_one('h1.product_title'),
                    soup.select_one('h1.GrE04'),  # BigBasket specific
                    soup.select_one('.product-name'),
                    soup.select_one('.product-title'),
                    soup.select_one('[data-testid="product-name"]')
                ]
                
                for candidate in product_name_candidates:
                    if candidate and candidate.text.strip():
                        product_info['name'] = candidate.text.strip()
                        break
                
                # Try to find product brand
                brand_candidates = [
                    soup.select_one('.brand'),
                    soup.select_one('.product-brand'),
                    soup.select_one('a.Tq74c'),  # BigBasket specific
                    soup.select_one('[data-testid="product-brand"]')
                ]
                
                for candidate in brand_candidates:
                    if candidate and candidate.text.strip():
                        product_info['brand'] = candidate.text.strip()
                        break
                
                # Try to find price
                price_candidates = [
                    soup.select_one('.price'),
                    soup.select_one('.product-price'),
                    soup.select_one('td.IyLvo')  # BigBasket specific
                ]
                
                for candidate in price_candidates:
                    if candidate and candidate.text.strip():
                        product_info['price'] = candidate.text.strip()
                        break
                
                # Try to find description
                desc_candidates = [
                    soup.select_one('.description'),
                    soup.select_one('.product-description'),
                    soup.select_one('div[data-qa="product-about"]'),  # BigBasket specific
                    soup.select_one('[data-testid="product-description"]')
                ]
                
                for candidate in desc_candidates:
                    if candidate and candidate.text.strip():
                        product_info['description'] = candidate.text.strip()
                        break
                
                # Try to find product image
                img_candidates = [
                    soup.select_one('img.product-image'),
                    soup.select_one('.product-image img'),
                    soup.select_one('img.JRgbI'),  # BigBasket specific
                    soup.select_one('[data-testid="product-image"] img')
                ]
                
                for candidate in img_candidates:
                    if candidate and candidate.has_attr('src'):
                        product_info['image_url'] = candidate['src']
                        break
                
                # Extract quantity and unit from product name or page
                if product_info.get('name'):
                    qty_match = re.search(r'(\d+\.?\d*)\s*(kg|g|gm|ml|l|ltr|litre|pieces|pcs|pc|pack)', 
                                         product_info['name'], re.IGNORECASE)
                    
                    if qty_match:
                        product_info['quantity'] = qty_match.group(1)
                        product_info['unit'] = qty_match.group(2).lower()
                
                # If we found at least some information, return it
                if product_info.get('name') or product_info.get('description'):
                    return product_info
                    
            return None
                
        except Exception as e:
            logger.error(f"Error extracting info from URL {url}: {e}")
            return None
            
    def extract_bigbasket_info(self, url):
     """Extract product information from BigBasket website."""
     try:
        headers = {
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml',
            'Accept-Language': 'en-US,en;q=0.9'
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Check if it's a BigBasket homepage or search page and not an actual product page
            homepage_indicators = ['online grocery store', 'grocery delivery', 'online supermarket']
            page_title = soup.title.text.lower() if soup.title else ""
            
            if any(indicator in page_title for indicator in homepage_indicators) and "product details" not in page_title:
                logger.warning(f"URL appears to be BigBasket homepage/search page, not a product page: {url}")
                return None
            
            # Initialize product info
            product_info = {}
            
            # Extract product name
            product_name_selectors = [
                'h1.GrE04',           # Newer BB design
                'h1.prod-name',       # Older BB design 
                '.prod-name h1',      # Alternative older selector
                'h1[qa="prod-name"]', # Alternative with data attributes
                'h1'                  # Generic fallback
            ]
            for selector in product_name_selectors:
                product_name_elem = soup.select_one(selector)
                if product_name_elem and product_name_elem.text.strip():
                    name = product_name_elem.text.strip()
                    # Ensure we're not getting the site name instead of a product
                    if name != "bigbasket – online grocery store":
                        product_info['name'] = name
                        break
            
            # If we didn't find a valid product name, return None
            if not product_info.get('name'):
                logger.warning(f"Could not find product name on page: {url}")
                return None
            
            # Extract brand
            brand_selectors = [
                'a.Tq74c',  # Newer BB design
                '.brand-name', 
                'a[qa="prod-brand"]',
                'span.brand'
            ]
            for selector in brand_selectors:
                brand_elem = soup.select_one(selector)
                if brand_elem and brand_elem.text.strip():
                    product_info['brand'] = brand_elem.text.strip()
                    break
            
            # Extract price
            price_selectors = [
                'td.IyLvo', 
                '.actual-price',
                'span.discnt-price',
                'span[qa="price"]'
            ]
            for selector in price_selectors:
                price_elem = soup.select_one(selector)
                if price_elem and price_elem.text.strip():
                    product_info['price'] = price_elem.text.strip()
                    break
            
            # Extract description
            desc_selectors = [
                'div[data-qa="product-about"]',
                '.about-brand p', 
                '.prod-description',
                'div[qa="prod-description"]'
            ]
            for selector in desc_selectors:
                desc_elem = soup.select_one(selector)
                if desc_elem and desc_elem.text.strip():
                    product_info['description'] = desc_elem.text.strip()
                    break
            
            # Extract all specifications
            specs_selectors = [
                'div.h9mIE', 
                '.product-info-tbl tr', 
                'table.product-info-table tr',
                'li.attr-desc'
            ]
            
            specifications = {}
            for selector in specs_selectors:
                elems = soup.select(selector)
                if elems:
                    for elem in elems:
                        # Different ways BigBasket structures spec data
                        if elem.select_one('div:nth-child(1)') and elem.select_one('div:nth-child(2)'):
                            key = elem.select_one('div:nth-child(1)').text.strip()
                            val = elem.select_one('div:nth-child(2)').text.strip()
                            specifications[key] = val
                        elif elem.select_one('td:nth-child(1)') and elem.select_one('td:nth-child(2)'):
                            key = elem.select_one('td:nth-child(1)').text.strip()
                            val = elem.select_one('td:nth-child(2)').text.strip()
                            specifications[key] = val
                        elif elem.select_one('.attr-name') and elem.select_one('.attr-value'):
                            key = elem.select_one('.attr-name').text.strip()
                            val = elem.select_one('.attr-value').text.strip()
                            specifications[key] = val
            
            if specifications:
                product_info['specifications'] = specifications
            
            # Extract categories
            breadcrumb_selectors = [
                'a.FY3Oe', 
                '.breadcrumb a', 
                'ol.breadcrumb li a',
                '.breadcrumb-item'
            ]
            
            categories = []
            for selector in breadcrumb_selectors:
                elems = soup.select(selector)
                if elems:
                    categories = [elem.text.strip() for elem in elems if elem.text.strip()]
                    categories = [cat for cat in categories if cat.lower() not in ['home', 'all categories']]
                    break
                    
            if categories:
                product_info['categories'] = categories
            
            # IMPROVED: Extract product image with better handling
            img_selectors = [
                'img.JRgbI', 
                '.img-responsive', 
                '.prod-img img',
                'img[qa="prod-img"]',
                '.product-img img',
                '.product-image img',
                '#bigimage',
                '.product-images img',
                'img[data-qa="product-image"]',
                '.bb-item img',  # Common BigBasket carousel image
                '.prod-slider img'  # Another BigBasket product slider
            ]

            for selector in img_selectors:
                img_elements = soup.select(selector)
                for img_elem in img_elements:
                    if img_elem and img_elem.has_attr('src'):
                        src = img_elem['src']
                        # Skip tiny images (likely icons)
                        if 'icon' in src.lower() or 'logo' in src.lower() or 'placeholder' in src.lower():
                            continue
                            
                        # Clean up the URL
                        img_url = src
                        # Ensure URL is absolute
                        if img_url.startswith('//'):
                            img_url = 'https:' + img_url
                        elif img_url.startswith('/'):
                            # Convert relative URL to absolute
                            base_url = '/'.join(url.split('/')[:3])  # Get domain
                            img_url = base_url + img_url
                            
                        # Some sites use data-src attribute for lazy loading
                        if not img_url or img_url.endswith('.gif'):
                            for attr in ['data-src', 'data-original', 'data-lazy']:
                                if img_elem.has_attr(attr):
                                    potential_url = img_elem[attr]
                                    if potential_url and not potential_url.endswith('.gif'):
                                        img_url = potential_url
                                        if img_url.startswith('//'):
                                            img_url = 'https:' + img_url
                                        elif img_url.startswith('/'):
                                            base_url = '/'.join(url.split('/')[:3])
                                            img_url = base_url + img_url
                                        break
                                        
                        # Check for srcset attribute which might have higher resolution images
                        if img_elem.has_attr('srcset'):
                            srcset = img_elem['srcset']
                            highest_res_url = ''
                            highest_width = 0
                            
                            # Parse srcset format: "url 1x, url 2x, ..." or "url 100w, url 200w, ..."
                            srcset_parts = srcset.split(',')
                            for part in srcset_parts:
                                part = part.strip()
                                if not part:
                                    continue
                                
                                # Extract URL and descriptor
                                url_parts = part.split(' ')
                                if len(url_parts) >= 2:
                                    src_url = url_parts[0].strip()
                                    descriptor = url_parts[1].strip()
                                    
                                    # Convert descriptor to width
                                    width = 0
                                    if descriptor.endswith('x'):
                                        try:
                                            width = int(float(descriptor[:-1]) * 100)  # Rough estimate
                                        except ValueError:
                                            pass
                                    elif descriptor.endswith('w'):
                                        try:
                                            width = int(descriptor[:-1])
                                        except ValueError:
                                            pass
                                            
                                    if width > highest_width:
                                        highest_width = width
                                        highest_res_url = src_url
                            
                            if highest_res_url:
                                img_url = highest_res_url
                                if img_url.startswith('//'):
                                    img_url = 'https:' + img_url
                                elif img_url.startswith('/'):
                                    base_url = '/'.join(url.split('/')[:3])
                                    img_url = base_url + img_url
                        
                        # If we found a valid image URL
                        if img_url and len(img_url) > 10:
                            product_info['image_url'] = img_url
                            logger.debug(f"Found product image: {img_url}")
                            break
                
                # Stop trying selectors if we found an image
                if 'image_url' in product_info:
                    break
            
            # Extract quantity and unit
            qty_selectors = [
                '.qty', 
                '.product-qty',
                'span[qa="prod-qty"]',
                '.prod-vol' 
            ]
            
            for selector in qty_selectors:
                qty_elem = soup.select_one(selector)
                if qty_elem and qty_elem.text.strip():
                    qty_text = qty_elem.text.strip()
                    qty_match = re.search(r'(\d+\.?\d*)\s*(kg|g|gm|ml|l|ltr|litre|pieces|pcs|pc|pack)', 
                                        qty_text, re.IGNORECASE)
                    if qty_match:
                        product_info['quantity'] = qty_match.group(1)
                        product_info['unit'] = qty_match.group(2).lower()
                        break
            
            # If quantity not found in dedicated fields, try product name
            if not product_info.get('quantity') and product_info.get('name'):
                qty_match = re.search(r'(\d+\.?\d*)\s*(kg|g|gm|ml|l|ltr|litre|pieces|pcs|pc|pack)', 
                                     product_info['name'], re.IGNORECASE)
                
                if qty_match:
                    product_info['quantity'] = qty_match.group(1)
                    product_info['unit'] = qty_match.group(2).lower()
            
            return product_info
            
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
                        
                        # Extract image URL
                        if data.get('image'):
                            result["image_url"] = data.get('image')
                            
                        # Extract quantity and unit
                        qty_match = None
                        if result.get('name'):
                            qty_match = re.search(r'(\d+\.?\d*)\s*(kg|g|gm|ml|l|ltr|litre|pieces|pcs|pc|pack)', 
                                               result['name'], re.IGNORECASE)
                        
                        if qty_match:
                            result['quantity'] = qty_match.group(1)
                            result['unit'] = self.standardize_unit(qty_match.group(2))
                            
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
            
    def get_product_from_openai(self, barcode, search_results_info=None):
        """Use OpenAI to retrieve product information based on barcode and search results."""
        if not self.openai_api_key:
            return None
            
        try:
            # Use requests instead of openai library
            url = "https://api.openai.com/v1/chat/completions"
            
            headers = {
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json"
            }
            
            # Construct a prompt based on available search results
            additional_context = ""
            if search_results_info:
                # Add titles and snippets from search results as context
                if search_results_info.get('titles'):
                    additional_context += "Search result titles:\n"
                    for i, title in enumerate(search_results_info['titles'][:5], 1):  # Limit to first 5 results
                        additional_context += f"{i}. {title}\n"
                
                if search_results_info.get('snippets'):
                    additional_context += "\nSearch result snippets:\n"
                    for i, snippet in enumerate(search_results_info['snippets'][:5], 1):  # Limit to first 5 results
                        additional_context += f"{i}. {snippet}\n"
            
            system_prompt = """You are a barcode lookup assistant specialized in Indian products. 
            Given a barcode number and any additional context, create a detailed product information record.
            Return a JSON object with these fields: name, brand, description, category, quantity, unit, features, 
            specifications, and image_url if you can determine this information.
            For unit values, use standardized units: "gm" for grams, "kg" for kilograms, "ml" for milliliters, 
            "ltr" for liters, "pc" for pieces/units.
            Include only factual information from the context provided. Do NOT invent or hallucinate details.
            If you can't determine certain fields, leave them empty or omit them."""
            
            user_prompt = f"Barcode: {barcode}\n\n"
            if additional_context:
                user_prompt += f"Additional context from search results:\n{additional_context}\n\n"
            user_prompt += "Please provide any product information you can determine in JSON format:"
            
            data = {
                "model": "gpt-3.5-turbo",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.3
            }
            
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 200:
                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                
                # Attempt to parse JSON from the response
                try:
                    json_match = re.search(r'```json\n(.*?)\n```', content, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(1)
                    else:
                        json_match = re.search(r'```\n(.*?)\n```', content, re.DOTALL)
                        if json_match:
                            json_str = json_match.group(1)
                        else:
                            json_str = content
                        
                    parsed_data = json.loads(json_str)
                    
                    # If we got meaningful data back
                    if parsed_data and any(key not in ["barcode", "source"] for key in parsed_data.keys()):
                        parsed_data["barcode"] = barcode
                        parsed_data["source"] = "openai"
                        return parsed_data
                except Exception as e:
                    logger.error(f"Error parsing OpenAI response: {e}")
                    
            return None
            
        except Exception as e:
            logger.error(f"Error retrieving product from OpenAI: {e}")
            return None
            
    def get_product_from_deepseek(self, barcode, search_results_info=None):
        """Use DeepSeek to retrieve product information based on barcode and search results."""
        if not self.deepseek_api_key:
            return None
            
        try:
            url = "https://api.deepseek.com/v1/chat/completions"
            
            headers = {
                "Authorization": f"Bearer {self.deepseek_api_key}",
                "Content-Type": "application/json"
            }
            
            # Construct a prompt based on available search results
            additional_context = ""
            if search_results_info:
                # Add titles and snippets from search results as context
                if search_results_info.get('titles'):
                    additional_context += "Search result titles:\n"
                    for i, title in enumerate(search_results_info['titles'][:5], 1):  # Limit to first 5 results
                        additional_context += f"{i}. {title}\n"
                
                if search_results_info.get('snippets'):
                    additional_context += "\nSearch result snippets:\n"
                    for i, snippet in enumerate(search_results_info['snippets'][:5], 1):  # Limit to first 5 results
                        additional_context += f"{i}. {snippet}\n"
            
            system_prompt = """You are a barcode lookup assistant specialized in Indian products. 
            Given a barcode number and any additional context, create a detailed product information record.
            Return a JSON object with these fields: name, brand, description, category, quantity, unit, features, 
            specifications, and image_url if you can determine this information.
            For unit values, use standardized units: "gm" for grams, "kg" for kilograms, "ml" for milliliters, 
            "ltr" for liters, "pc" for pieces/units.
            Include only factual information from the context provided. Do NOT invent or hallucinate details.
            If you can't determine certain fields, leave them empty or omit them."""
            
            user_prompt = f"Barcode: {barcode}\n\n"
            if additional_context:
                user_prompt += f"Additional context from search results:\n{additional_context}\n\n"
            user_prompt += "Please provide any product information you can determine in JSON format:"
            
            data = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.3
            }
            
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 200:
                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                
                # Attempt to parse JSON from the response
                try:
                    json_match = re.search(r'```json\n(.*?)\n```', content, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(1)
                    else:
                        json_match = re.search(r'```\n(.*?)\n```', content, re.DOTALL)
                        if json_match:
                            json_str = json_match.group(1)
                        else:
                            json_str = content
                        
                    parsed_data = json.loads(json_str)
                    
                    # If we got meaningful data back
                    if parsed_data and any(key not in ["barcode", "source"] for key in parsed_data.keys()):
                        parsed_data["barcode"] = barcode
                        parsed_data["source"] = "deepseek"
                        return parsed_data
                except Exception as e:
                    logger.error(f"Error parsing DeepSeek response: {e}")
                    
            return None
            
        except Exception as e:
            logger.error(f"Error retrieving product from DeepSeek: {e}")
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
    
     # Variable to store search results information
     search_results_info = None
    
     # Try multiple methods in sequence, from fastest/cheapest to most complex
    
     # 1. First try Open Food Facts (free, fast)
     logger.info(f"Trying Open Food Facts for barcode {barcode}")
     product_info = self.get_product_info_from_openfoodfacts(barcode)
     if product_info:
        logger.info(f"Found product info from Open Food Facts")
        self.processed_barcodes.add(barcode)
        self.last_successful_entry = product_info
        return product_info
    
     # 2. Try Google search to get context
     # Add delay between API calls
     time.sleep(self.api_request_delay)
    
     logger.info(f"Searching Google for barcode {barcode}")
     url, search_results = self.search_google_for_barcode(barcode)
    
     if search_results:
        search_results_info = search_results
        
        # Try to extract info directly from search results
        search_product_info = self.get_product_info_from_search_results(barcode, search_results_info)
        if search_product_info:
            logger.info(f"Found product info from search results")
            self.processed_barcodes.add(barcode)
            self.last_successful_entry = search_product_info
            return search_product_info
    
     # 3. If we have a URL, try to extract from it
     if url:
        if "bigbasket" in url:
            logger.info(f"Found BigBasket URL, extracting product info")
            bigbasket_info = self.extract_bigbasket_info(url)
            
            if bigbasket_info:
                bigbasket_info["barcode"] = barcode
                bigbasket_info["source"] = "bigbasket"
                logger.info(f"Successfully extracted product info from BigBasket")
                self.processed_barcodes.add(barcode)
                self.last_successful_entry = bigbasket_info
                return bigbasket_info
        else:
            # Try generic extraction for other sites
            logger.info(f"Extracting product info from URL: {url}")
            # If you have extraction methods for other sites, call them here
    
     # 4. Try DigitEyes API
     # Add delay between API calls
     time.sleep(self.api_request_delay)
    
     logger.info(f"Trying DigitEyes API for barcode {barcode}")
     product_info = self.get_product_from_digiteyes(barcode)
     if product_info:
        logger.info(f"Found product info from DigitEyes API")
        self.processed_barcodes.add(barcode)
        self.last_successful_entry = product_info
        return product_info
    
     # 5. Try DeepSeek (if available)
     if self.deepseek_api_key:
        # Add delay between API calls
        time.sleep(self.api_request_delay)
        
        logger.info(f"Trying DeepSeek for barcode {barcode}")
        product_info = self.get_product_from_deepseek(barcode)
        if product_info:
            logger.info(f"Found product info from DeepSeek")
            self.processed_barcodes.add(barcode)
            self.last_successful_entry = product_info
            return product_info
    
     # 6. Try OpenAI (if available)
     if self.openai_api_key:
        # Add delay between API calls
        time.sleep(self.api_request_delay)
        
        logger.info(f"Trying OpenAI for barcode {barcode}")
        product_info = self.get_product_from_openai(barcode)
        if product_info:
            logger.info(f"Found product info from OpenAI")
            self.processed_barcodes.add(barcode)
            self.last_successful_entry = product_info
            return product_info
            
     logger.warning(f"Could not find product info for barcode {barcode} using any method")
     return None

    def enhance_product_info_with_ai(self, barcode, product_info=None, search_results_info=None):
     """Use AI to create or enhance product information to match the desired schema."""
     # First check if we have access to OpenAI or DeepSeek for enhancement
     if not (self.openai_api_key or self.deepseek_api_key):
        logger.warning("No AI API keys available for product info enhancement")
        return product_info
    
     # Extract a basic product name and brand from search results if available
     product_name_from_search = ""
     brand_from_search = ""
    
     if search_results_info:  # Add this check to ensure search_results_info is not None
        product_name_from_search, brand_from_search = self.extract_product_name_from_search_results(search_results_info)
    
     # Default image URL if none is available
     default_image_url = f"https://external-content.duckduckgo.com/iu/?u=https%3A%2F%2Ftse3.mm.bing.net%2Fth%3Fid%3DOIP.DvQs_zJG5Bo35yCJ-eiWIQHaHa%26pid%3DApi&f=1&ipt=96dc7d84b243cf6611078549dfce916df145c74eb02c3a5a3ab46a8491f92ff9&ipo=images"
    
     # Create a template of the desired output format with existing information
     template = {
        "Barcode": barcode,
        "Product Name": (product_info.get("name") if product_info else product_name_from_search) or "",
        "Description": (product_info.get("description") if product_info else "") or "",
        "Category": (product_info.get("category") if product_info else "") or "",
        "ProductLine": "",
        "Quantity": (product_info.get("quantity") if product_info else "") or "",
        "Unit": (product_info.get("unit") if product_info else "") or "",
        "Features": (product_info.get("features", []) if product_info and "features" in product_info else []),
        "Specification": {},
        "Brand": (product_info.get("brand") if product_info else brand_from_search) or "",
        "Product Image": (product_info.get("image_url") if product_info and product_info.get("image_url") else default_image_url),
        "Product Ingredient Image": (product_info.get("image_url") if product_info and product_info.get("image_url") else default_image_url)
     }
    
     # Add specifications from existing product info
     if product_info and "specifications" in product_info:
        template["Specification"] = product_info["specifications"]
     elif product_info:
        # Try to construct specifications from other fields
        specs = {}
        
        # Add manufacturer if available
        if product_info.get("manufacturer"):
            specs["Manufacturer"] = product_info["manufacturer"]
        
        # Add nutrition facts if available
        if product_info.get("nutrition_facts"):
            specs["Nutrition Facts"] = product_info["nutrition_facts"]
        
        # Add ingredients if available
        if product_info.get("ingredients"):
            specs["Ingredients"] = product_info["ingredients"]
            
        # Add other potential specifications
        if product_info.get("price"):
            specs["Price"] = product_info["price"]
            
        # Add source info
        if product_info.get("source"):
            specs["Data Source"] = product_info["source"]
            
        template["Specification"] = specs
    
     # Try using OpenAI first if available
     if self.openai_api_key:
        try:
            url = "https://api.openai.com/v1/chat/completions"
            
            headers = {
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json"
            }
            
            # Create a prompt that includes the product info and the desired output format
            system_prompt = """You are a product information enhancer for an Indian e-commerce platform. 
            Given a barcode and any available product details, create or enhance the information to match the desired output schema.
            You MUST provide information for ALL fields in the output schema using EXACTLY the field names provided.
            EVERY field must be populated with meaningful data - do not leave any fields empty or with placeholder text.
            
            Follow these specific requirements:
            - Use "Product Name" with a space, not "ProductName" - follow the exact field name format from the template.
            - For the Description field, write a comprehensive and engaging product description.
            - For Features, include at least 3-5 key features or benefits of the product as an array of strings.
            - For the Specification object, include at least Weight, Form, and Packaging Type.
            - For ProductLine, derive it from the product name and brand.
            - For Quantity, provide a numeric value (without units) - convert to number.
            - For Unit, use common units like "L", "ml", "kg", "gm", etc.
            - Do NOT change the Product Image and Product Ingredient Image URLs provided in the template.
            
            Important: Base your information on the facts provided in the input data and search results. When data is missing,
            make educated guesses based on similar products. NEVER leave any field empty or with minimal information.
            """
            
            # Build prompt content based on available information
            user_prompt = f"Barcode: {barcode}\n\n"
            
            if product_info:
                user_prompt += f"Available product information:\n"
                for key, value in product_info.items():
                    if key != 'barcode' and value:
                        user_prompt += f"{key}: {value}\n"
                user_prompt += "\n"
            
            if search_results_info:
                user_prompt += "Search results information:\n"
                if search_results_info.get('titles'):
                    user_prompt += "Titles:\n"
                    for title in search_results_info['titles'][:5]:  # Limit to first 5
                        user_prompt += f"- {title}\n"
                
                if search_results_info.get('snippets'):
                    user_prompt += "\nSnippets:\n"
                    for snippet in search_results_info['snippets'][:5]:  # Limit to first 5
                        user_prompt += f"- {snippet}\n"
            
            user_prompt += f"\nCreate a complete product information record following EXACTLY this format and field names:\n"
            user_prompt += json.dumps(template, indent=2)
            user_prompt += "\n\nYour response MUST follow this exact format with spaces in field names. Make sure ALL fields have meaningful content - don't leave any empty."
            
            data = {
                "model": "gpt-3.5-turbo",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.7
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                
                # Attempt to parse JSON from the response
                try:
                    # Clean up the response to isolate JSON
                    content = content.strip()
                    if content.startswith("```json"):
                        content = content.replace("```json", "", 1).strip()
                    if content.startswith("```"):
                        content = content.replace("```", "", 1).strip()
                    if content.endswith("```"):
                        content = content.rsplit("```", 1)[0].strip()
                    
                    enhanced_data = json.loads(content)
                    logger.info("Successfully enhanced product info using OpenAI")
                    
                    # Ensure quantity is a number
                    if "Quantity" in enhanced_data and enhanced_data["Quantity"]:
                        try:
                            enhanced_data["Quantity"] = float(enhanced_data["Quantity"])
                            if enhanced_data["Quantity"].is_integer():
                                enhanced_data["Quantity"] = int(enhanced_data["Quantity"])
                        except:
                            pass
                    
                    # Make sure we keep the image URL from the template
                    if not enhanced_data.get("Product Image") or enhanced_data.get("Product Image") == "":
                        enhanced_data["Product Image"] = default_image_url
                        
                    if not enhanced_data.get("Product Ingredient Image") or enhanced_data.get("Product Ingredient Image") == "":
                        enhanced_data["Product Ingredient Image"] = default_image_url
                    
                    # Check for any empty fields and fill them with reasonable values
                    if not enhanced_data.get("Description") or enhanced_data.get("Description") == "":
                        if enhanced_data.get("Product Name"):
                            enhanced_data["Description"] = f"{enhanced_data.get('Product Name')} is a high-quality product manufactured by {enhanced_data.get('Brand', 'a reputable brand')}. It offers excellent performance and reliability."
                        
                    if not enhanced_data.get("Features") or len(enhanced_data.get("Features", [])) == 0:
                        if "dish" in enhanced_data.get("Product Name", "").lower() or "wash" in enhanced_data.get("Product Name", "").lower():
                            enhanced_data["Features"] = ["Removes tough stains", "Gentle on hands", "Fresh fragrance", "Antibacterial properties"]
                        else:
                            enhanced_data["Features"] = ["High quality product", "Excellent performance", "Long lasting", "Great value"]
                            
                    if not enhanced_data.get("Category") or enhanced_data.get("Category") == "":
                        if "dish" in enhanced_data.get("Product Name", "").lower() or "wash" in enhanced_data.get("Product Name", "").lower():
                            enhanced_data["Category"] = "Cleaning & Household"
                        else:
                            enhanced_data["Category"] = "General Merchandise"
                            
                    if not enhanced_data.get("ProductLine") or enhanced_data.get("ProductLine") == "":
                        brand = enhanced_data.get("Brand", "")
                        if brand:
                            name_parts = enhanced_data.get("Product Name", "").split()
                            if name_parts:
                                enhanced_data["ProductLine"] = f"{brand} {name_parts[0]}"
                            else:
                                enhanced_data["ProductLine"] = f"{brand} Product Line"
                        else:
                            enhanced_data["ProductLine"] = "Premium Product Line"
                            
                    if not enhanced_data.get("Brand") or enhanced_data.get("Brand") == "":
                        name = enhanced_data.get("Product Name", "")
                        if name:
                            name_parts = name.split()
                            if name_parts:
                                enhanced_data["Brand"] = name_parts[0]
                            else:
                                enhanced_data["Brand"] = "Quality Brand"
                        else:
                            enhanced_data["Brand"] = "Quality Brand"
                            
                    # Add minimum specs if not already present
                    spec = enhanced_data.get("Specification", {})
                    if not spec.get("Weight") and enhanced_data.get("Quantity") and enhanced_data.get("Unit"):
                        spec["Weight"] = f"{enhanced_data.get('Quantity')} {enhanced_data.get('Unit')}"
                    
                    if not spec.get("Form"):
                        if "liquid" in enhanced_data.get("Product Name", "").lower():
                            spec["Form"] = "Liquid"
                        elif "powder" in enhanced_data.get("Product Name", "").lower():
                            spec["Form"] = "Powder"
                        elif "bar" in enhanced_data.get("Product Name", "").lower() or "soap" in enhanced_data.get("Product Name", "").lower():
                            spec["Form"] = "Bar"
                        else:
                            spec["Form"] = "Solid"
                            
                    if not spec.get("Packaging Type"):
                        if "liquid" in enhanced_data.get("Product Name", "").lower():
                            spec["Packaging Type"] = "Bottle"
                        elif "bar" in enhanced_data.get("Product Name", "").lower() or "soap" in enhanced_data.get("Product Name", "").lower():
                            spec["Packaging Type"] = "Wrapper"
                        else:
                            spec["Packaging Type"] = "Box"
                            
                    enhanced_data["Specification"] = spec
                    
                    return enhanced_data
                except Exception as e:
                    logger.error(f"Error parsing enhanced product data from OpenAI: {e}")
            
        except Exception as e:
            logger.error(f"Error enhancing product info with OpenAI: {e}")
    
     # If OpenAI failed or is not available, try DeepSeek
     if self.deepseek_api_key:
        try:
            url = "https://api.deepseek.com/v1/chat/completions"
            
            headers = {
                "Authorization": f"Bearer {self.deepseek_api_key}",
                "Content-Type": "application/json"
            }
            
            # Same prompts as OpenAI
            system_prompt = """You are a product information enhancer for an Indian e-commerce platform. 
            Given a barcode and any available product details, create or enhance the information to match the desired output schema.
            You MUST provide information for ALL fields in the output schema using EXACTLY the field names provided.
            EVERY field must be populated with meaningful data - do not leave any fields empty or with placeholder text.
            
            Follow these specific requirements:
            - Use "Product Name" with a space, not "ProductName" - follow the exact field name format from the template.
            - For the Description field, write a comprehensive and engaging product description.
            - For Features, include at least 3-5 key features or benefits of the product as an array of strings.
            - For the Specification object, include at least Weight, Form, and Packaging Type.
            - For ProductLine, derive it from the product name and brand.
            - For Quantity, provide a numeric value (without units) - convert to number.
            - For Unit, use common units like "L", "ml", "kg", "gm", etc.
            - Do NOT change the Product Image and Product Ingredient Image URLs provided in the template.
            
            Important: Base your information on the facts provided in the input data and search results. When data is missing,
            make educated guesses based on similar products. NEVER leave any field empty or with minimal information.
            """
            
            # Build prompt content based on available information
            user_prompt = f"Barcode: {barcode}\n\n"
            
            if product_info:
                user_prompt += f"Available product information:\n"
                for key, value in product_info.items():
                    if key != 'barcode' and value:
                        user_prompt += f"{key}: {value}\n"
                user_prompt += "\n"
            
            if search_results_info:
                user_prompt += "Search results information:\n"
                if search_results_info.get('titles'):
                    user_prompt += "Titles:\n"
                    for title in search_results_info['titles'][:5]:  # Limit to first 5
                        user_prompt += f"- {title}\n"
                
                if search_results_info.get('snippets'):
                    user_prompt += "\nSnippets:\n"
                    for snippet in search_results_info['snippets'][:5]:  # Limit to first 5
                        user_prompt += f"- {snippet}\n"
            
            user_prompt += f"\nCreate a complete product information record following EXACTLY this format and field names:\n"
            user_prompt += json.dumps(template, indent=2)
            user_prompt += "\n\nYour response MUST follow this exact format with spaces in field names. Make sure ALL fields have meaningful content - don't leave any empty."
            
            data = {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.7
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                
                # Attempt to parse JSON from the response
                try:
                    # Clean up the response to isolate JSON
                    content = content.strip()
                    if content.startswith("```json"):
                        content = content.replace("```json", "", 1).strip()
                    if content.startswith("```"):
                        content = content.replace("```", "", 1).strip()
                    if content.endswith("```"):
                        content = content.rsplit("```", 1)[0].strip()
                    
                    enhanced_data = json.loads(content)
                    logger.info("Successfully enhanced product info using DeepSeek")
                    
                    # Ensure quantity is a number
                    if "Quantity" in enhanced_data and enhanced_data["Quantity"]:
                        try:
                            enhanced_data["Quantity"] = float(enhanced_data["Quantity"])
                            if enhanced_data["Quantity"].is_integer():
                                enhanced_data["Quantity"] = int(enhanced_data["Quantity"])
                        except:
                            pass
                    
                    # Make sure we keep the image URL from the template
                    if not enhanced_data.get("Product Image") or enhanced_data.get("Product Image") == "":
                        enhanced_data["Product Image"] = default_image_url
                        
                    if not enhanced_data.get("Product Ingredient Image") or enhanced_data.get("Product Ingredient Image") == "":
                        enhanced_data["Product Ingredient Image"] = default_image_url
                        
                    # Check for any empty fields and fill them with reasonable values
                    if not enhanced_data.get("Description") or enhanced_data.get("Description") == "":
                        if enhanced_data.get("Product Name"):
                            enhanced_data["Description"] = f"{enhanced_data.get('Product Name')} is a high-quality product manufactured by {enhanced_data.get('Brand', 'a reputable brand')}. It offers excellent performance and reliability."
                        
                    if not enhanced_data.get("Features") or len(enhanced_data.get("Features", [])) == 0:
                        if "dish" in enhanced_data.get("Product Name", "").lower() or "wash" in enhanced_data.get("Product Name", "").lower():
                            enhanced_data["Features"] = ["Removes tough stains", "Gentle on hands", "Fresh fragrance", "Antibacterial properties"]
                        else:
                            enhanced_data["Features"] = ["High quality product", "Excellent performance", "Long lasting", "Great value"]
                            
                    if not enhanced_data.get("Category") or enhanced_data.get("Category") == "":
                        if "dish" in enhanced_data.get("Product Name", "").lower() or "wash" in enhanced_data.get("Product Name", "").lower():
                            enhanced_data["Category"] = "Cleaning & Household"
                        else:
                            enhanced_data["Category"] = "General Merchandise"
                            
                    if not enhanced_data.get("ProductLine") or enhanced_data.get("ProductLine") == "":
                        brand = enhanced_data.get("Brand", "")
                        if brand:
                            name_parts = enhanced_data.get("Product Name", "").split()
                            if name_parts:
                                enhanced_data["ProductLine"] = f"{brand} {name_parts[0]}"
                            else:
                                enhanced_data["ProductLine"] = f"{brand} Product Line"
                        else:
                            enhanced_data["ProductLine"] = "Premium Product Line"
                            
                    if not enhanced_data.get("Brand") or enhanced_data.get("Brand") == "":
                        name = enhanced_data.get("Product Name", "")
                        if name:
                            name_parts = name.split()
                            if name_parts:
                                enhanced_data["Brand"] = name_parts[0]
                            else:
                                enhanced_data["Brand"] = "Quality Brand"
                        else:
                            enhanced_data["Brand"] = "Quality Brand"
                            
                    # Add minimum specs if not already present
                    spec = enhanced_data.get("Specification", {})
                    if not spec.get("Weight") and enhanced_data.get("Quantity") and enhanced_data.get("Unit"):
                        spec["Weight"] = f"{enhanced_data.get('Quantity')} {enhanced_data.get('Unit')}"
                    
                    if not spec.get("Form"):
                        if "liquid" in enhanced_data.get("Product Name", "").lower():
                            spec["Form"] = "Liquid"
                        elif "powder" in enhanced_data.get("Product Name", "").lower():
                            spec["Form"] = "Powder"
                        elif "bar" in enhanced_data.get("Product Name", "").lower() or "soap" in enhanced_data.get("Product Name", "").lower():
                            spec["Form"] = "Bar"
                        else:
                            spec["Form"] = "Solid"
                            
                    if not spec.get("Packaging Type"):
                        if "liquid" in enhanced_data.get("Product Name", "").lower():
                            spec["Packaging Type"] = "Bottle"
                        elif "bar" in enhanced_data.get("Product Name", "").lower() or "soap" in enhanced_data.get("Product Name", "").lower():
                            spec["Packaging Type"] = "Wrapper"
                        else:
                            spec["Packaging Type"] = "Box"
                            
                    enhanced_data["Specification"] = spec
                        
                    return enhanced_data
                except Exception as e:
                    logger.error(f"Error parsing enhanced product data from DeepSeek: {e}")
        
        except Exception as e:
            logger.error(f"Error enhancing product info with DeepSeek: {e}")
    
     # If both enhancement methods fail, fall back to the basic transformation
     if product_info:
        return self.transform_to_desired_format(product_info, barcode)
     return None
    def get_image_url_from_google(self, query):
     """Get an image URL for a product from Google Image Search."""
     if not self.serpapi_key:
        return None
        
     try:
        # SerpAPI endpoint
        url = "https://serpapi.com/search"
        
        # Query parameters
        params = {
            "api_key": self.serpapi_key,
            "q": query,
            "tbm": "isch",  # Image search
            "ijn": "0",     # First page
            "num": "1",     # Just need one image
            "safe": "active"  # Safe search
        }
        
        # Make the request
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            data = response.json()
            
            # Extract image results
            images = data.get("images_results", [])
            
            if images and len(images) > 0:
                return images[0].get("original")
        
        return None
        
     except Exception as e:
        logger.error(f"Error during Google image search: {e}")
        return None
    def transform_to_desired_format(self, product_info, barcode):
     """Transform raw product info to the desired output format."""
     result = {
        "Barcode": barcode,
        "Product Name": product_info.get("name", "Unknown Product"),
        "Description": product_info.get("description", f"{product_info.get('name', 'Unknown Product')} is a high-quality item that offers excellent value and performance."),
        "Category": "General Merchandise",
        "ProductLine": f"{product_info.get('brand', 'Unknown')} Product Line",
        "Brand": product_info.get("brand", "Unknown")
     }
    
     # Set category based on product info
     if product_info.get("categories"):
        categories = product_info.get("categories")
        for category in categories:
            if any(keyword in category.lower() for keyword in ['cleaning', 'household', 'laundry', 'dishwash']):
                result["Category"] = "Cleaning & Household"
                break
     elif product_info.get("category"):
        category = product_info.get("category")
        if any(keyword in category.lower() for keyword in ['cleaning', 'household', 'laundry', 'dishwash']):
            result["Category"] = "Cleaning & Household"
    
     # Handle quantity and unit
     quantity = product_info.get("quantity", 1)
     unit = product_info.get("unit", "pc")
    
     # Convert quantity to float if it's a string that represents a number
     if isinstance(quantity, str) and quantity.replace(".", "", 1).isdigit():
        result["Quantity"] = float(quantity)
     else:
        result["Quantity"] = quantity
        
     result["Unit"] = unit
    
     # Handle features - use specific features if available, otherwise use generic ones
     if product_info.get("features") and isinstance(product_info.get("features"), list):
        result["Features"] = product_info.get("features")
     else:
        if "Cleaning" in result["Category"] or "Household" in result["Category"]:
            result["Features"] = [
                "Removes tough stains",
                "Gentle on hands",
                "Fresh fragrance",
                "Antibacterial properties"
            ]
        else:
            result["Features"] = [
                "High quality product",
                "Excellent performance",
                "Long lasting",
                "Great value"
            ]
    
     # Handle specifications
     specs = {"Country of Origin": "India"}
    
     if product_info.get("specifications") and isinstance(product_info.get("specifications"), dict):
        specs.update(product_info.get("specifications"))
    
     # Add weight to specifications if available
     if result["Quantity"] and result["Unit"]:
        specs["Weight"] = f"{result['Quantity']} {result['Unit']}"
    
     # Add form based on category or unit
     if "Liquid" in product_info.get("name", "") or unit in ["ml", "l", "ltr", "litre"]:
        specs["Form"] = "Liquid"
     elif "Powder" in product_info.get("name", ""):
        specs["Form"] = "Powder"
     elif "Bar" in product_info.get("name", ""):
        specs["Form"] = "Bar"
     else:
        specs["Form"] = "Solid"
    
     # Add packaging type
     if unit in ["ml", "l", "ltr", "litre"]:
        specs["Packaging Type"] = "Bottle"
     elif "Box" in product_info.get("name", ""):
        specs["Packaging Type"] = "Box"
     elif "Bar" in product_info.get("name", ""):
        specs["Packaging Type"] = "Box"
     elif "Powder" in product_info.get("name", ""):
        specs["Packaging Type"] = "Box"
     else:
        specs["Packaging Type"] = "Pack"
    
     result["Specification"] = specs
    
     # Handle product images properly
     image_url = product_info.get("image_url", "")
    
     # Use OpenFoodFacts URL format if no image available
     if not image_url:
        # Format: https://images.openfoodfacts.org/images/products/890/210/216/3831/front_en.3.400.jpg
        barcode_formatted = barcode
        if len(barcode) >= 13:
            off_url = f"https://images.openfoodfacts.org/images/products/{barcode[:3]}/{barcode[3:6]}/{barcode[6:9]}/{barcode[9:]}/front_en.3.400.jpg"
            result["Product Image"] = off_url
            result["Product Ingredient Image"] = off_url
        else:
            # If not a valid barcode, use a placeholder
            placeholder = "https://images.openfoodfacts.org/images/products/default.jpg"
            result["Product Image"] = placeholder
            result["Product Ingredient Image"] = placeholder
     else:
        # Use extracted image URL
        result["Product Image"] = image_url
        result["Product Ingredient Image"] = image_url
    
     return result
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
                
                # Add image URL if available
                image_url = product.get("image_url", "")
                if image_url:
                    result["image_url"] = image_url
                
                # Extract category
                categories = product.get("categories", "")
                if categories:
                    result["category"] = categories
                
                # Extract quantity and unit
                quantity = product.get("quantity", "")
                if quantity:
                    qty_match = re.search(r'(\d+\.?\d*)\s*(kg|g|gm|ml|l|ltr|litre|pieces|pcs|pc|pack)', 
                                         quantity, re.IGNORECASE)
                    if qty_match:
                        result["quantity"] = qty_match.group(1)
                        result["unit"] = self.standardize_unit(qty_match.group(2))
                
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
    def save_noresult_json(self):
        """Save information about barcodes that couldn't be processed."""
        noresults = []
        
        # Read barcodes from Excel
        barcodes = self.read_barcodes_from_excel(self.input_file)
        
        # Get list of processed barcodes
        processed_barcodes = set()
        if os.path.exists(self.output_file):
            try:
                with open(self.output_file, 'r') as f:
                    data = json.load(f)
                    for entry in data:
                        processed_barcodes.add(entry.get('Barcode'))
            except json.JSONDecodeError:
                pass
                
        # Find barcodes with no results
        for barcode in barcodes:
            if barcode not in processed_barcodes:
                noresults.append({
                    "Barcode": barcode,
                    "Status": "No product information found",
                    "Timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                })
        
        # Save to noresult.json if there are any items
        if noresults:
            with open("noresult.json", 'w') as f:
                json.dump(noresults, f, indent=2)
            logger.info(f"Saved {len(noresults)} barcodes with no results to noresult.json")
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
        
        # Variable to store search results information
        search_results_info = None
        raw_product_info = None
        
        # 1. First try Open Food Facts (free, fast)
        logger.info(f"Trying Open Food Facts for barcode {barcode}")
        product_info = self.get_product_info_from_openfoodfacts(barcode)
        if product_info:
            logger.info(f"Found product info from Open Food Facts")
            raw_product_info = product_info
        
        # 2. Search with Google to get context and potential URLs
        time.sleep(self.api_request_delay)
        logger.info(f"Searching Google for barcode {barcode}")
        url, search_results = self.search_google_for_barcode(barcode)
        if search_results:
            search_results_info = search_results
        
        # 3. If still no product info, try DigitEyes
        if not raw_product_info:
            # Add delay between API calls
            time.sleep(self.api_request_delay)
            
            # Try DigitEyes API
            logger.info(f"Trying DigitEyes API for barcode {barcode}")
            product_info = self.get_product_from_digiteyes(barcode)
            if product_info:
                logger.info(f"Found product info from DigitEyes API")
                raw_product_info = product_info
        
        # 4. If we have a URL (especially BigBasket), try to extract info
        if url and not raw_product_info:
            logger.info(f"Found URL, extracting product info: {url}")
            if "bigbasket" in url:
                logger.info(f"Found BigBasket URL, extracting product info")
                product_info = self.extract_bigbasket_info(url)
            else:
                product_info = self.extract_product_info_from_url(url)
                
            if product_info:
                product_info["barcode"] = barcode
                product_info["source"] = "web_scraping"
                logger.info(f"Successfully extracted product info from website")
                raw_product_info = product_info
            else:
                logger.info(f"Failed to extract product info from URL")
        
        # 5. Try DeepSeek with search results context if available
        if not raw_product_info and self.deepseek_api_key:
            # Add delay between API calls
            time.sleep(self.api_request_delay)
            
            logger.info(f"Trying DeepSeek for barcode {barcode}")
            product_info = self.get_product_from_deepseek(barcode, search_results_info)
            if product_info:
                logger.info(f"Found product info from DeepSeek")
                raw_product_info = product_info
        
        # 6. Try OpenAI with search results context if available
        if not raw_product_info and self.openai_api_key:
            # Add delay between API calls
            time.sleep(self.api_request_delay)
            logger.info(f"Trying OpenAI for barcode {barcode}")
            product_info = self.get_product_from_openai(barcode, search_results_info)
            if product_info:
                logger.info(f"Found product info from OpenAI")
                raw_product_info = product_info
        
        # Now, even if we have no raw product info but have search results,
        # we can still try to enhance with AI
        if raw_product_info or search_results_info:
            # Enhance the product info with AI using both raw data and search results
            logger.info(f"Enhancing product info for barcode {barcode}")
            enhanced_product_info = self.enhance_product_info_with_ai(barcode, raw_product_info, search_results_info)
            
            if enhanced_product_info:
                self.last_successful_entry = enhanced_product_info
                return enhanced_product_info
            elif raw_product_info:
                # If enhancement failed but we have raw data, use basic transformation
                basic_transform = self.transform_to_desired_format(raw_product_info, barcode)
                self.last_successful_entry = basic_transform
                return basic_transform
                
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

    def process_barcodes(self, start_barcode=None):
     """Process barcodes from Excel file and fetch product information.
    
     Args:
        start_barcode: Optional barcode to start processing from.
     """
     if not self.input_file:
        self.input_file = input("Enter path to Excel file with barcodes: ")
        
     # Read barcodes from Excel
     barcodes = self.read_barcodes_from_excel(self.input_file)
    
     if not barcodes:
        logger.error("No valid barcodes found to process")
        return
        
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
     
     # Determine starting index
     start_index = 0
    
     # If a specific start barcode is provided, find its index
     if start_barcode:
        try:
            start_index = barcodes.index(start_barcode)
            logger.info(f"Starting from specified barcode {start_barcode} at index {start_index}")
        except ValueError:
            logger.warning(f"Specified start barcode {start_barcode} not found in input file. Starting from beginning.")
     # Otherwise use the last processed index from our saved state
     elif self.last_processed_index > 0:
        # Make sure we don't go beyond the list bounds
        if self.last_processed_index < len(barcodes):
            start_index = self.last_processed_index
            logger.info(f"Resuming from index {start_index} (barcode {barcodes[start_index]})")
        else:
            logger.warning("Saved index exceeds current barcode count. Starting from beginning.")
    
     logger.info(f"Processing {len(barcodes) - start_index} barcodes starting from index {start_index}")
    
     # Process each barcode with progress bar
     try:
        total_to_process = len(barcodes) - start_index
        with tqdm(total=total_to_process, desc="Processing barcodes") as pbar:
            for i in range(start_index, len(barcodes)):
                barcode = barcodes[i]
                
                # Skip if already processed
                if barcode in processed_set or barcode in self.attempted_barcodes:
                    logger.info(f"Barcode {barcode} already processed or attempted, skipping")
                    pbar.update(1)
                    continue
                
                # Mark as attempted
                self.attempted_barcodes.add(barcode)
                
                # Get product info
                product_info = self.get_product_info(barcode)
                
                # Update progress after each barcode
                self.last_processed_index = i + 1
                self.save_progress_state(self.last_processed_index, self.attempted_barcodes)
                
                # Only add non-null product info to results
                if product_info and len(product_info) > 1:  # Has more than just the barcode
                    results.append(product_info)
                    processed_set.add(barcode)
                    
                    # Save results periodically (every 10 barcodes)
                    if len(results) % 10 == 0:
                        self.save_results(results)
                
                # Update progress bar
                pbar.update(1)
                
                # Check if we've reached our daily request limit
                if self.request_count >= self.max_daily_requests:
                    logger.warning("Daily API request limit reached. Stopping processing.")
                    break
                
     except KeyboardInterrupt:
        logger.warning("Process interrupted by user")
     except Exception as e:
        logger.error(f"Error during processing: {e}")
     finally:
        # Save final results
        self.save_results(results)
        
        # Save progress state
        self.save_progress_state(self.last_processed_index, self.attempted_barcodes)
        
        # Display last successful entry
        if self.last_successful_entry:
            logger.info("Last successfully processed entry:")
            logger.info(json.dumps(self.last_successful_entry, indent=2))
        else:
            logger.warning("No entries were successfully processed")

def main():
    """Main function to run the barcode fetcher."""
    # Setup command-line arguments
    parser = argparse.ArgumentParser(description='Fetch product information for barcodes.')
    parser.add_argument('--start', type=str, help='Barcode to start processing from')
    args = parser.parse_args()
    

    fetcher = BarcodeFetcher()
    fetcher.process_barcodes()


if __name__ == "__main__":
    main()