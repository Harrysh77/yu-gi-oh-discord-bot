import discord
from discord import app_commands, ui
import os
from typing import Optional
import re
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import difflib
import json
import sqlite3
from datetime import datetime, timedelta


# --- DATABASE ---
card_database = {}
DB_PATH = "cards.db"
CACHE_DURATION_DAYS = 7  # Update database weekly
LOCAL_DECK_TYPES_PATH = os.getenv('LOCAL_DECK_TYPES_PATH', 'deck-types.json')
deck_types_local_imported = False

def init_database():
    """Initialize the SQLite database with the required schema."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Create tables if they don't exist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cards (
                    name TEXT PRIMARY KEY,
                    card_data JSON NOT NULL,
                    last_updated TIMESTAMP NOT NULL
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_cards_name 
                ON cards(name COLLATE NOCASE)
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS decks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    author TEXT,
                    url TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS deck_cards (
                    deck_id INTEGER,
                    card_name TEXT,
                    is_extra_deck BOOLEAN NOT NULL DEFAULT 0,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY (deck_id) REFERENCES decks(id) ON DELETE CASCADE,
                    FOREIGN KEY (card_name) REFERENCES cards(name),
                    PRIMARY KEY (deck_id, card_name)
                )
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_deck_cards_card
                ON deck_cards(card_name)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_decks_url
                ON decks(url)
            """)
            
            conn.commit()
            print("Database initialized successfully.")
    except sqlite3.Error as e:
        print(f"Error initializing database: {e}")
        # If there's an error, it might be corrupted. Try removing and recreating.
        try:
            os.remove(DB_PATH)
            print("Removed potentially corrupted database. It will be recreated on the next run.")
            init_database() # Retry initialization
        except OSError as e2:
            print(f"Could not remove database file: {e2}")
    except Exception as e:
        print(f"An unexpected error occurred during database initialization: {e}")

def should_update_database():
    """Check if the database needs to be updated based on age."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Check if the database exists and has data
            cursor.execute("SELECT last_updated FROM cards LIMIT 1")
            result = cursor.fetchone()
            
            if not result:
                return True
                
            last_updated = datetime.fromisoformat(result[0])
            return datetime.now() - last_updated > timedelta(days=CACHE_DURATION_DAYS)
    except:
        return True

def load_card_data():
    """Loads card data from local SQLite database or downloads from YGOJSON if needed."""
    global card_database
    
    try:
        init_database()
        
        # Check if we need to update the database
        if should_update_database():
            print("Downloading fresh card database...")
            url = "https://raw.githubusercontent.com/iconmaster5326/YGOJSON/v1/aggregate/cards.json"
            response = requests.get(url)
            response.raise_for_status()
            cards = response.json()
            
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                current_time = datetime.now().isoformat()
                
                # Begin transaction
                cursor.execute("BEGIN TRANSACTION")
                try:
                    # Clear existing data
                    cursor.execute("DELETE FROM cards")
                    
                    # Create temporary table for new data
                    cursor.execute("""
                        CREATE TEMPORARY TABLE temp_cards (
                            name TEXT PRIMARY KEY,
                            card_data JSON,
                            last_updated TIMESTAMP
                        )
                    """)
                    
                    # Insert new data into temporary table
                    for card in cards:
                        try:
                            name = card['text']['en']['name']
                            cursor.execute(
                                "INSERT OR REPLACE INTO temp_cards (name, card_data, last_updated) VALUES (?, ?, ?)",
                                (name, json.dumps(card), current_time)
                            )
                        except KeyError:
                            # Skip cards without English names
                            continue
                    
                    # Move data from temporary table to main table
                    cursor.execute("""
                        INSERT OR REPLACE INTO cards (name, card_data, last_updated)
                        SELECT name, card_data, last_updated FROM temp_cards
                    """)
                    
                    # Drop temporary table
                    cursor.execute("DROP TABLE temp_cards")
                    
                    # Commit transaction
                    conn.commit()
                    print("Card database updated successfully.")
                except Exception as e:
                    # If anything goes wrong, roll back
                    conn.rollback()
                    raise e
        
        # Load cards from database into memory
        print("Loading cards from local database...")
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name, card_data FROM cards")
            rows = cursor.fetchall()
            
            card_database = {
                row[0]: json.loads(row[1])
                for row in rows
            }
            
            print(f"Successfully loaded {len(card_database)} cards.")
    
    except requests.exceptions.RequestException as e:
        print(f"Error downloading card database: {e}")
        # Try to load from existing database even if download failed
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name, card_data FROM cards")
                rows = cursor.fetchall()
                card_database = {row[0]: json.loads(row[1]) for row in rows}
                print(f"Loaded {len(card_database)} cards from existing database.")
        except Exception as db_e:
            print(f"Error loading from local database: {db_e}")
    
    except Exception as e:
        print(f"An unexpected error occurred: {e}")