# scraper_app/tasks.py

from celery import shared_task
from django.conf import settings  # To get BASE_DIR for absolute paths

import httpx
from lxml import html
import sqlite3
import time
import logging
import re
import datetime
import pytz
import os
import csv

# --- Configuration ---
# Construct absolute paths using Django's settings.BASE_DIR
# Assumes your DB and log file are in the Django project's root directory
DB_PATH = os.path.join(settings.BASE_DIR, "atomo_django.db")
PRICE_LOG_PATH = os.path.join(settings.BASE_DIR, "price_changes.csv")

REQUEST_TIMEOUT = 25.0
SLEEP_BETWEEN_PAGES = 1.0
ARGENTINA_TZ = pytz.timezone('America/Argentina/Buenos_Aires')

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

CATEGORIES = [
    ("https://atomoconviene.com/atomo-ecommerce/mas-vendidos?page={}", 33),
    ("https://atomoconviene.com/atomo-ecommerce/300-carnes-y-congelados?page={}", 1),
    ("https://atomoconviene.com/atomo-ecommerce/833-ofertas?page={}", 5),
    ("https://atomoconviene.com/atomo-ecommerce/3-almacen?page={}", 14),
    ("https://atomoconviene.com/atomo-ecommerce/81-bebidas?page={}", 5),
    ("https://atomoconviene.com/atomo-ecommerce/226-lacteos-fiambres?page={}", 2),
    ("https://atomoconviene.com/atomo-ecommerce/473-sin-tacc?page={}", 2),
    ("https://atomoconviene.com/atomo-ecommerce/83-perfumeria?page={}", 6),
    ("https://atomoconviene.com/atomo-ecommerce/85-limpieza?page={}", 4),
    ("https://atomoconviene.com/atomo-ecommerce/82-mundo-bebe?page={}", 1),
    ("https://atomoconviene.com/atomo-ecommerce/88-mascotas?page={}", 1),
    ("https://atomoconviene.com/atomo-ecommerce/315-hogar-bazar?page={}", 1),
    ("https://atomoconviene.com/atomo-ecommerce/306-jugueteria-y-libreria?page={}", 3),
]

LISTING_XPATH = "//article[contains(@class,'product-miniature')]"
XPATHS = {
    "PRODUCT_ID": "@data-id-product",
    "PRODUCT_URL": ".//a[contains(@class,'product-thumbnail')]/@href",
    "PRODUCT_NAME": ".//h2[contains(@class,'product-title')]/a/text()",
    "PRODUCT_PRICE_STR": ".//span[contains(@class,'price')]/text()",
    "PRODUCT_IMAGE_URL": ".//a[contains(@class,'product-thumbnail')]//img/@data-full-size-image-url | .//a[contains(@class,'product-thumbnail')]//img/@data-src | .//a[contains(@class,'product-thumbnail')]//img/@src"
}

# --- Logger Setup ---
# Use a named logger for this module. Celery will handle routing its output.
logger = logging.getLogger(__name__)
# Basic configuration if no handlers are already set (e.g., by Celery root logger)
if not logger.handlers:
    # You can customize this handler (e.g., to a file) if Celery's default isn't enough
    # For now, let Celery's default handlers manage output.
    # If you want to force output to console for this logger specifically during development:
    # stream_handler = logging.StreamHandler()
    # formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    # stream_handler.setFormatter(formatter)
    # logger.addHandler(stream_handler)
    logger.setLevel(logging.INFO)  # Set level for this specific logger


# --- Helper Functions ---
# def get_dolar_crypto_rate():
#     """Fetches the 'venta' value for Dolar Cripto from dolarapi.com."""
#     logger.info(f"Attempting to fetch Dolar Cripto rate from {DOLAR_API_URL}")
#     try:
#         with httpx.Client(timeout=15.0) as client:
#              response = client.get(DOLAR_API_URL)
#              response.raise_for_status()
#              data = response.json()
#              venta_rate = data.get('venta')
#              if venta_rate is None:
#                  logger.error("API response missing 'venta' key.")
#                  return None
#              rate = float(venta_rate)
#              logger.info(f"Successfully fetched Dolar Cripto 'venta' rate: {rate}")
#              return rate
#     except Exception as e:
#         logger.error(f"Failed to fetch or parse Dolar Cripto rate: {e}", exc_info=True)
#         return None

def clean_price(price_str):
    """Cleans ARS price string and converts to int if whole number, else float."""
    if not price_str: return None
    try:
        cleaned = re.sub(r'[$\s]', '', price_str)
        if '.' in cleaned and ',' in cleaned:
            cleaned = cleaned.replace('.', '').replace(',', '.')
        elif ',' in cleaned:
            cleaned = cleaned.replace(',', '.')
        num_value = float(cleaned)
        return int(num_value) if num_value.is_integer() else num_value
    except (ValueError, TypeError) as e:
        logger.warning(f"Could not parse price string: '{price_str}'. Error: {e}")
        return None


def get_argentina_time_str():
    """Gets the current time adjusted to Argentina time (UTC-3) as string."""
    utc_now = datetime.datetime.now(pytz.utc)
    argentina_now = utc_now.astimezone(ARGENTINA_TZ)
    return argentina_now.strftime('%Y-%m-%d %H:%M:%S')


# --- Database and History Setup ---
def setup_database(db_file_path):
    """Connects to the SQLite database and ensures the table exists."""
    try:
        conn = sqlite3.connect(db_file_path)
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            url TEXT PRIMARY KEY,
            name TEXT,
            price_ars REAL,
            image_url TEXT,
            scraped_at TEXT
        )
        ''')
        conn.commit()
        logger.info(f"Database connection established/verified at {db_file_path}")
        return conn, cursor
    except sqlite3.Error as e:
        logger.error(f"Database error during setup at {db_file_path}: {e}", exc_info=True)
        raise


def load_old_prices(conn):
    """Loads existing product URLs and ARS prices from the DB into a dictionary."""
    old_prices = {}
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT url, price_ars FROM products")
        for row in cursor.fetchall():
            price = row[1] if row[1] is not None else None
            old_prices[row[0]] = price
        logger.info(f"Loaded {len(old_prices)} existing product prices from database.")
    except sqlite3.Error as e:
        logger.warning(f"Could not load old prices from DB (maybe first run?): {e}")
    return old_prices


def log_price_change(price_log_file_path, change_details):
    """Appends a price change event to the CSV log file."""
    file_exists = os.path.isfile(price_log_file_path)
    try:
        with open(price_log_file_path, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['timestamp', 'product_id', 'product_name',
                          'old_price_ars', 'new_price_ars', 'change_percentage', 'product_url']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            if not file_exists or os.path.getsize(price_log_file_path) == 0:
                writer.writeheader()

            writer.writerow(change_details)
    except IOError as e:
        logger.error(f"Failed to write to price change log {price_log_file_path}: {e}", exc_info=True)


# --- Main Scraping Logic ---
def scrape_products_data(conn, cursor, categories_to_scrape, old_prices_dict, current_price_log_path):
    """Scrapes product data, compares prices, logs changes, and prepares data for DB update."""
    all_products_for_db = []
    price_change_detected_flag = False
    total_processed_pages = 0
    total_products_found_listings = 0

    with httpx.Client(headers=HEADERS, timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        for base_url_template, max_pages in categories_to_scrape:
            category_name = base_url_template.split('/')[-1].split('?')[0]
            logger.info(f"--- Starting category: {category_name} (Max pages: {max_pages}) ---")
            category_products_found_on_page = 0

            for page_num in range(1, max_pages + 1):
                current_page_url = base_url_template.format(page_num)
                logger.info(f"Attempting to scrape page: {current_page_url}")
                try:
                    response = client.get(current_page_url)
                    if response.status_code == 404:
                        logger.warning(f"Page {current_page_url} returned 404, stopping for this category.")
                        break
                    response.raise_for_status()
                except Exception as list_err:
                    logger.error(f"Error fetching list page {current_page_url}: {list_err}", exc_info=True)
                    time.sleep(SLEEP_BETWEEN_PAGES * 2)  # Longer sleep on error
                    continue

                try:
                    tree = html.fromstring(response.content)
                    product_elements = tree.xpath(LISTING_XPATH)
                    if not product_elements:
                        logger.info(
                            f"No products found on page {page_num} for {category_name}. Moving to next or finishing category.")
                        break

                    total_processed_pages += 1
                    page_products_count = len(product_elements)
                    category_products_found_on_page += page_products_count
                    logger.info(f"Found {page_products_count} products on page {page_num} of {category_name}...")

                    current_scraped_at_ts = get_argentina_time_str()

                    for product_el in product_elements:
                        product_data = {}
                        for key, xp in XPATHS.items():
                            result = product_el.xpath(xp)
                            raw_value = result[0] if isinstance(result, list) and result else (
                                result if not isinstance(result, list) else None)
                            product_data[key] = raw_value.strip() if isinstance(raw_value, str) else raw_value

                        product_id_from_site = product_data.get("PRODUCT_ID")
                        product_url = product_data.get("PRODUCT_URL")
                        product_name = product_data.get("PRODUCT_NAME")
                        product_image_url = product_data.get("PRODUCT_IMAGE_URL")

                        if not product_url:
                            logger.warning(
                                f"Skipping product on page {page_num} due to missing PRODUCT_URL. Site Product ID: {product_id_from_site}. Page URL: {current_page_url}")
                            continue

                        if not product_id_from_site:
                            logger.warning(
                                f"Product with URL {product_url} is missing PRODUCT_ID (data-id-product). Price change log might be affected if this ID is primary for it.")

                        new_price_ars = clean_price(product_data.get("PRODUCT_PRICE_STR"))
                        old_price_ars = old_prices_dict.get(product_url)

                        is_change = False
                        percentage_change = 0.0
                        if new_price_ars is not None and old_price_ars is not None:
                            if not abs(new_price_ars - old_price_ars) < 0.01:
                                is_change = True
                                if old_price_ars > 0:
                                    percentage_change = round(((new_price_ars - old_price_ars) / old_price_ars) * 100,
                                                              2)
                                else:
                                    percentage_change = float(
                                        'inf')  # New price for a previously zero/non-existent price
                        elif new_price_ars is not None and old_price_ars is None:
                            logger.debug(
                                f"Product {product_url} (SiteID: {product_id_from_site}) appeared with price {new_price_ars}")
                            # Optionally treat as a change: is_change = True; percentage_change = 100.0
                        elif new_price_ars is None and old_price_ars is not None:
                            logger.debug(
                                f"Product {product_url} (SiteID: {product_id_from_site}) price disappeared (was {old_price_ars})")
                            # Optionally treat as a change: is_change = True; percentage_change = -100.0

                        if is_change:
                            price_change_detected_flag = True
                            change_details = {
                                'timestamp': current_scraped_at_ts,
                                'product_id': product_id_from_site or "N/A",
                                'product_name': product_name or "N/A",
                                'old_price_ars': old_price_ars,
                                'new_price_ars': new_price_ars,
                                'change_percentage': percentage_change,
                                'product_url': product_url
                            }
                            log_price_change(current_price_log_path, change_details)
                            logger.info(
                                f"PRICE CHANGE: URL {product_url} (SiteID: {product_id_from_site}) | Old: {old_price_ars} | New: {new_price_ars} | %: {percentage_change}%")

                        product_tuple_for_db = (
                            product_url,
                            product_name,
                            new_price_ars,
                            product_image_url,
                            current_scraped_at_ts
                        )
                        all_products_for_db.append(product_tuple_for_db)
                        total_products_found_listings += 1

                    time.sleep(SLEEP_BETWEEN_PAGES)

                except html.LxmlError as e:
                    logger.error(f"Parsing error on page {current_page_url}: {e}", exc_info=True)
                    continue
                except Exception as e:
                    logger.error(f"Unexpected error processing page {current_page_url}: {e}", exc_info=True)
                    continue

            logger.info(
                f"--- Finished category '{category_name}'. Found {category_products_found_on_page} product listings in this category run. ---")

    if all_products_for_db:
        logger.info(f"Processed {total_products_found_listings} product listings across {total_processed_pages} pages.")
        unique_products_to_insert = {item[0]: item for item in all_products_for_db}
        logger.info(
            f"Attempting to insert/update {len(unique_products_to_insert)} unique product records into the database.")
        try:
            cursor.executemany('''
            INSERT OR REPLACE INTO products
            (url, name, price_ars, image_url, scraped_at)
            VALUES (?, ?, ?, ?, ?)
            ''', list(unique_products_to_insert.values()))
            conn.commit()
            cursor.execute("SELECT COUNT(*) FROM products")
            final_db_count = cursor.fetchone()[0]
            logger.info(f"Database update complete. Final unique product count in DB: {final_db_count}")
        except sqlite3.Error as e:
            logger.error(f"Database error during bulk insert: {e}", exc_info=True)
            conn.rollback()
    else:
        logger.info("No product data collected to update database.")

    return price_change_detected_flag


# --- Celery Task Definition ---
@shared_task(name="run_atomo_scraper")
def run_atomo_scraper_task():
    logger.info("Starting Atomo scraper task via Celery...")
    conn = None
    changes_found = False

    # current_dolar_rate = get_dolar_crypto_rate() # Uncomment if needed for other purposes

    try:
        # DB_PATH and PRICE_LOG_PATH are module-level constants using absolute paths
        conn, cursor = setup_database(DB_PATH)
        old_prices_data = load_old_prices(conn)
        changes_found = scrape_products_data(conn, cursor, CATEGORIES, old_prices_data, PRICE_LOG_PATH)
    except sqlite3.Error as db_err:
        logger.error(f"A database error occurred in scraper task: {db_err}", exc_info=True)
    except Exception as e:
        logger.error(f"A critical unexpected error occurred in scraper task: {e}", exc_info=True)
    finally:
        if conn:
            logger.info("Closing database connection for scraper task.")
            conn.close()

    if changes_found:
        logger.info("Scraper task finished. Price changes were detected and logged.")
        # You could add custom logic here, e.g., sending a notification
    else:
        logger.info("Scraper task finished. No price changes detected.")

    logger.info(f"Database used by scraper: {DB_PATH}")
    logger.info(f"Price change log used by scraper: {PRICE_LOG_PATH}")
    return f"Scraping finished. Changes found: {changes_found}"