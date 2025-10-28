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

# Load environment variables from a .env file
load_dotenv()

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


# --- BOT SETUP ---
# Define the specific permissions (intents) the bot needs
intents = discord.Intents.default()
intents.message_content = True # If you need to read message content

class YuGiOhBot(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        # CommandTree holds all the application commands
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # This is called once when the bot logs in, before it's ready.
        # It's the ideal place to sync application commands.
        await self.tree.sync()
        print('Slash commands have been synchronized.')

    async def on_ready(self):
        if self.user:
            print(f'Logged in as {self.user} (ID: {self.user.id})')

    async def on_interaction(self, interaction: discord.Interaction):
        print(f"Received interaction: {interaction.data}")

class ArtworkView(ui.View):
    def __init__(self, image_urls: list[str], embed: discord.Embed):
        super().__init__(timeout=180)  # View times out after 3 minutes
        self.image_urls = image_urls
        self.current_index = 0
        self.embed = embed

        # Disable buttons if there's only one or zero images
        if len(self.image_urls) <= 1:
            self.prev_button.disabled = True
            self.next_button.disabled = True

    @ui.button(label="< Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: ui.Button):
        self.current_index = (self.current_index - 1) % len(self.image_urls)
        self.embed.set_image(url=self.image_urls[self.current_index])
        await interaction.response.edit_message(embed=self.embed)

    @ui.button(label="> Next", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: ui.Button):
        self.current_index = (self.current_index + 1) % len(self.image_urls)
        self.embed.set_image(url=self.image_urls[self.current_index])
        await interaction.response.edit_message(embed=self.embed)

# Instantiate the bot
client = YuGiOhBot(intents=intents)


# --- SLASH COMMANDS ---

def get_card_suggestions(search_terms: str, max_suggestions: int = 5) -> list[str]:
    """Get card name suggestions based on search terms."""
    search_words = search_terms.lower().split()
    
    # Score each card name based on how well it matches the search terms
    scored_matches = []
    for card_name in card_database.keys():
        card_lower = card_name.lower()
        score = 0
        
        # Check if all search words appear in the card name
        all_words_present = all(word in card_lower for word in search_words)
        if all_words_present:
            # Base score for containing all words
            score += 100
            
            # Bonus for exact matches of individual words
            for word in search_words:
                if word in card_lower.split():
                    score += 50
            
            # Bonus for matching at start of name
            if card_lower.startswith(search_words[0]):
                score += 25
            
            # Penalty based on length difference
            length_diff = abs(len(card_lower) - len(search_terms))
            score -= length_diff
            
            scored_matches.append((score, card_name))
    
    # Sort by score and return top matches
    scored_matches.sort(reverse=True)
    return [name for score, name in scored_matches[:max_suggestions]]

async def card_name_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Provides autocomplete suggestions for card names."""
    if not current:
        # If no input yet, return some popular cards or first few in database
        suggestions = list(card_database.keys())[:25]
    else:
        suggestions = get_card_suggestions(current, max_suggestions=25)
    
    return [
        app_commands.Choice(name=card_name[:100], value=card_name[:100])
        for card_name in suggestions
    ]

@client.tree.command(name="card", description="Search for a Yu-Gi-Oh! card on Master Duel Meta.")
@app_commands.describe(name="The name of the card to search for.")
@app_commands.autocomplete(name=card_name_autocomplete)
async def search_card(interaction: discord.Interaction, name: str):
    """Searches for a card and displays its details, with smart matching and suggestions."""
    print(f"'card' command triggered with name: {name}")

    # Defer the interaction if possible; if the interaction is unknown/expired,
    # catch and continue so we can attempt channel fallbacks later.
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
    except discord.errors.NotFound:
        print("Interaction not found when deferring; will fallback to channel messages where possible")
    except Exception as e:
        print(f"Error while deferring interaction: {e}")

    if not card_database:
        await send_response(interaction, content="Card database is not loaded. Please check the bot's console for errors.")
        return

    # Get suggestions based on the search terms
    suggestions = get_card_suggestions(name)

    if not suggestions:
        await send_response(interaction, content=f"No cards found matching '{name}'. Please check the spelling.")
        return

    # If we have an exact match, use it. Otherwise, show suggestions.
    matched_name = None
    for s in suggestions:
        if s.lower() == name.lower():
            matched_name = s
            break

    if not matched_name:
        if len(suggestions) == 1:
            matched_name = suggestions[0]
        else:
            # Create an embed with suggestions
            suggestion_embed = discord.Embed(
                title="Multiple cards found",
                description="Please choose one of these cards:",
                color=discord.Color.blue()
            )

            # Add numbered suggestions
            suggestion_text = "\n".join(f"{i+1}. {card}" for i, card in enumerate(suggestions))
            suggestion_embed.add_field(name="Suggestions", value=suggestion_text)
            suggestion_embed.set_footer(text="Use /card with the exact name to see card details")

            await send_response(interaction, embed=suggestion_embed)
            return

    print(f"Found match '{matched_name}' for query '{name}'")

    # Get the full card object from our local database
    card_data = card_database.get(matched_name)
    if not card_data:
        await send_response(interaction, content="Could not find card data in the local database. This should not happen.")
        return

    image_urls = [img['art'] for img in card_data.get('images', []) if 'art' in img]

    card_name_formatted = matched_name.replace(' ', '%20')
    url = f"https://www.masterduelmeta.com/cards/{card_name_formatted}"
    
    # --- EMBED CREATION ---
    embed = discord.Embed(
        title=matched_name,
        color=discord.Color.gold(),
        url=url
    )

    # Check if the card is a Pendulum monster
    is_pendulum = 'pendulum' in card_data.get('monsterCardTypes', []) or 'Pendulum' in card_data.get('type', '')

    if is_pendulum:
        pendulum_effect = card_data.get('text', {}).get('en', {}).get('pendulumEffect', "No Pendulum Effect found.")
        embed.add_field(name="Pendulum Effect", value=pendulum_effect, inline=False)
        
        monster_effect = card_data.get('text', {}).get('en', {}).get('effect', "No monster effect.")
        embed.add_field(name="Monster Effect", value=monster_effect, inline=False)
    else:
        description = card_data.get('text', {}).get('en', {}).get('effect', "No description found.")
        embed.description = description

    if image_urls:
        embed.set_thumbnail(url=image_urls[0])
    else:
        # Try to get image from Master Duel Meta as a fallback
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            card_image_element = soup.find('img', class_="card-image")
            if card_image_element:
                embed.set_thumbnail(url=card_image_element['src'])
        except Exception as e:
            print(f"Could not fetch fallback image: {e}")

    # Add more details to the embed
    if 'cardType' in card_data:
        embed.add_field(name="Card Type", value=card_data['cardType'].title(), inline=True)

    if card_data.get('cardType') == 'monster':
        if is_pendulum:
            pendulum_scale = card_data.get('pendulumScale')
            if pendulum_scale is not None:
                embed.add_field(name="Pendulum Scale", value=str(pendulum_scale), inline=True)

        if 'attribute' in card_data:
            embed.add_field(name="Attribute", value=card_data['attribute'].title(), inline=True)
        
        # Check monster types
        is_link = 'monsterCardTypes' in card_data and 'link' in card_data['monsterCardTypes']
        is_xyz = 'monsterCardTypes' in card_data and 'xyz' in card_data['monsterCardTypes']
        
        # Handle Level/Rank/Link with appropriate markers
        if is_link and 'linkArrows' in card_data:
            # Define link marker positions and their emojis
            link_markers = {
                'topleft': '↖️',
                'topcenter': '↑',
                'topright': '↗️',
                'middleleft': '←',
                'middleright': '→',
                'bottomleft': '↙️',
                'bottomcenter': '↓',
                'bottomright': '↘️'
            }
            
            # Convert arrows to a single line
            arrow_symbols = []
            for marker in sorted(card_data['linkArrows']):  # Sort to keep consistent order
                if marker in link_markers:
                    arrow_symbols.append(link_markers[marker])
            
            # Create the link marker display and rating
            link_value = len(card_data['linkArrows'])
            arrows_display = ''.join(arrow_symbols)
            
            # Combine Link Rating and arrows in one field
            embed.add_field(name="Link Rating", value=f"Link-{link_value} [{arrows_display}]", inline=True)
            
            # For Link monsters, ATK is shown differently (no DEF)
            if 'atk' in card_data:
                embed.add_field(name="ATK", value=f"{card_data['atk']}", inline=True)
        
        elif 'rank' in card_data or 'level' in card_data:
            if is_xyz and 'rank' in card_data:
                # XYZ monsters use Ranks with black stars
                rank_value = card_data['rank']
                stars = "★" * rank_value
                if is_pendulum and 'pendulumScale' in card_data:
                    pendulum_scale = card_data.get('pendulumScale')
                    embed.add_field(name="Rank", value=f"{rank_value} {stars} [Scale: {pendulum_scale}]", inline=True)
                else:
                    embed.add_field(name="Rank", value=f"{rank_value} {stars}", inline=True)
            elif 'level' in card_data:
                # Regular monsters use Levels with gold stars
                level_value = card_data['level']
                stars = "⭐" * level_value
                if is_pendulum and 'pendulumScale' in card_data:
                    pendulum_scale = card_data.get('pendulumScale')
                    embed.add_field(name="Level", value=f"{level_value} {stars} [Scale: {pendulum_scale}]", inline=True)
                else:
                    embed.add_field(name="Level", value=f"{level_value} {stars}", inline=True)
            
            # Regular monsters and XYZ monsters show both ATK/DEF
            if 'atk' in card_data and 'def' in card_data:
                embed.add_field(name="ATK/DEF", value=f"{card_data['atk']} / {card_data['def']}", inline=False)
        
        if 'type' in card_data:
            embed.add_field(name="Type", value=card_data['type'], inline=False)

    embed.set_footer(text="Powered by YGOJSON & MasterDuelMeta.com")

    # Create the view with buttons for artwork switching
    view = ArtworkView(image_urls, embed)

    await send_response(interaction, embed=embed, view=view)

def save_deck_to_db(deck_info):
    """Save a deck to the database."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Check if the deck already exists
            cursor.execute("SELECT id FROM decks WHERE url = ?", (deck_info['url'],))
            existing_deck = cursor.fetchone()
            
            if existing_deck:
                deck_id = existing_deck[0]
                # Update existing deck
                cursor.execute("""
                    UPDATE decks 
                    SET name = ?, author = ?, last_updated = CURRENT_TIMESTAMP 
                    WHERE id = ?
                """, (deck_info['name'], deck_info['author'], deck_id))
                
                # Delete existing card associations
                cursor.execute("DELETE FROM deck_cards WHERE deck_id = ?", (deck_id,))
            else:
                # Insert new deck
                cursor.execute("""
                    INSERT INTO decks (name, author, url) 
                    VALUES (?, ?, ?)
                """, (deck_info['name'], deck_info['author'], deck_info['url']))
                deck_id = cursor.lastrowid
            
            # Insert all main deck cards
            for card in deck_info['main_deck']:
                cursor.execute("""
                    INSERT INTO deck_cards (deck_id, card_name, is_extra_deck, quantity)
                    VALUES (?, ?, 0, ?)
                """, (deck_id, card['name'], card['count']))
            
            # Insert all extra deck cards
            for card in deck_info['extra_deck']:
                cursor.execute("""
                    INSERT INTO deck_cards (deck_id, card_name, is_extra_deck, quantity)
                    VALUES (?, ?, 1, ?)
                """, (deck_id, card['name'], card['count']))
            
            conn.commit()
            return True
    except Exception as e:
        print(f"Error saving deck to database: {e}")
        return False
def import_deck_by_id(deck_id, headers=None):
    """Fetch a single deck by API ID and save it to the database.

    Returns the parsed deck_info dict on success, or None on failure.
    """
    try:
        if headers is None:
            headers = {'User-Agent': 'Mozilla/5.0'}

        api_url = f"https://www.masterduelmeta.com/api/v1/decks/{deck_id}"
        resp = requests.get(api_url, headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f"Deck API returned {resp.status_code} for id {deck_id}")
            return None

        data = resp.json()

        deck_info = {
            'name': data.get('name', f'Deck {deck_id}'),
            'author': None,
            'url': data.get('url') or f"https://www.masterduelmeta.com/top-decks/{deck_id}",
            'main_deck': [],
            'extra_deck': []
        }

        # Author may be nested differently depending on API shape
        author = data.get('author') or data.get('owner') or {}
        if isinstance(author, dict):
            deck_info['author'] = author.get('name') or author.get('username')
        else:
            deck_info['author'] = str(author) if author else None

        # Cards can be in data['cards'] or data.get('decklist') depending on endpoint
        cards = data.get('cards') or data.get('decklist') or []
        for c in cards:
            # support multiple possible key names
            name = c.get('name') or c.get('cardName') or (c.get('card') or {}).get('name') or ''
            qty = c.get('quantity') or c.get('qty') or c.get('count') or 1
            is_extra = c.get('isExtra') or c.get('is_extra') or c.get('extra') or False

            if not name:
                continue

            card_info = {'name': name, 'count': int(qty)}
            if is_extra:
                deck_info['extra_deck'].append(card_info)
            else:
                deck_info['main_deck'].append(card_info)

        # Save deck to DB
        saved = save_deck_to_db(deck_info)
        if saved:
            print(f"Imported deck {deck_info['name']} (id={deck_id}) to database")
            return deck_info
        else:
            return None

    except Exception as e:
        print(f"Error importing deck {deck_id} from API: {e}")
        return None


def extract_deck_id_from_href(href: str) -> str | None:
    """Try to extract a numeric deck id from a URL/href.

    Returns the id as a string if found, otherwise None.
    """
    if not href:
        return None
    href = href.strip()
    # Remove query and fragment
    href = re.sub(r'[?#].*$', '', href)
    href = href.rstrip('/')

    # patterns like /decks/123 or /deck/123 or /top-decks/123
    m = re.search(r'/decks?/([0-9]+)(?:$|/)', href)
    if m:
        return m.group(1)

    # last path segment numeric
    last = href.split('/')[-1]
    if last.isdigit():
        return last

    return None


def find_deck_id_on_page(html_text: str) -> str | None:
    """Scan HTML/JS/text for a numeric deck id. Returns id string or None.

    This is a best-effort heuristic that looks for common patterns.
    """
    if not html_text:
        return None

    # Common API link embedded in the page
    m = re.search(r'/api/v1/decks/([0-9]+)', html_text)
    if m:
        return m.group(1)

    # data attributes
    m = re.search(r'data-deck-id=["\\]?(\d+)["\\]?', html_text)
    if m:
        return m.group(1)

    # JSON keys inside scripts (deckId, deck_id)
    m = re.search(r'"deckId"\s*[:=]\s*(\d+)', html_text)
    if m:
        return m.group(1)
    m = re.search(r'"deck_id"\s*[:=]\s*(\d+)', html_text)
    if m:
        return m.group(1)

    # generic /decks/123 pattern anywhere
    m = re.search(r'/decks?/([0-9]+)', html_text)
    if m:
        return m.group(1)

    # fallback: look for javascript variable like deckId = 123
    m = re.search(r'\bdeckId\b\s*[:=]\s*(\d+)', html_text)
    if m:
        return m.group(1)

    return None


def import_deck_types_to_db(limit=None):
    """Import deck types from MasterDuelMeta API and save their representative decks to the DB.

    If `limit` is provided, process at most that many deck types.
    Returns the number of decks successfully imported.
    """
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        api_url = "https://www.masterduelmeta.com/api/v1/deck-types"
        resp = requests.get(api_url, headers=headers, timeout=10)
        resp.raise_for_status()
        types = resp.json()

        imported = 0
        for i, t in enumerate(types):
            if limit is not None and i >= limit:
                break

            # Try to get a deck id from the type entry
            deck_id = t.get('id') or t.get('deck_id') or t.get('slug')
            if not deck_id:
                # Some entries may include an example deck in-place
                # Try to construct a deck_info from the type entry
                name = t.get('name') or t.get('title') or 'Unknown Deck'
                cards = t.get('cards') or []
                if not cards:
                    continue

                deck_info = {
                    'name': name,
                    'author': None,
                    'url': t.get('url') or f"https://www.masterduelmeta.com/top-decks/{name.replace(' ', '-').lower()}",
                    'main_deck': [],
                    'extra_deck': []
                }

                for c in cards:
                    name = c.get('name') or c.get('cardName') or ''
                    qty = c.get('quantity') or c.get('qty') or 1
                    is_extra = c.get('isExtra') or c.get('is_extra') or False
                    if not name:
                        continue
                    entry = {'name': name, 'count': int(qty)}
                    if is_extra:
                        deck_info['extra_deck'].append(entry)
                    else:
                        deck_info['main_deck'].append(entry)

                if save_deck_to_db(deck_info):
                    imported += 1
                continue

            # If we do have a deck id, import that deck via the decks API
            deck = import_deck_by_id(deck_id, headers=headers)
            if deck:
                imported += 1

        print(f"Imported {imported} deck(s) from deck-types API")
        return imported
    except Exception as e:
        print(f"Error importing deck types: {e}")
        return 0


def cleanup_old_decks(days=30):
    """Remove decks that haven't been updated in the specified number of days."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM decks 
                WHERE last_updated < datetime('now', ?)
            """, (f'-{days} days',))
            deleted_count = cursor.rowcount
            conn.commit()
            print(f"Cleaned up {deleted_count} old decks")
            return deleted_count
    except Exception as e:
        print(f"Error cleaning up old decks: {e}")
        return 0


def import_deck_types_from_file(file_path, limit=None):
    """Import deck-types from a local JSON file and save decks to the DB.

    file_path can be a path to a JSON file containing an array of deck-type objects
    matching the structure from the API. Returns the number of decks imported.
    """
    try:
        if not os.path.exists(file_path):
            print(f"Local deck-types file not found: {file_path}")
            return 0

        with open(file_path, 'r', encoding='utf-8') as f:
            types = json.load(f)

        imported = 0
        for i, t in enumerate(types):
            if limit is not None and i >= limit:
                break

            # If the type includes cards, construct deck_info
            cards = t.get('cards') or []
            if not cards:
                continue

            deck_info = {
                'name': t.get('name') or t.get('title') or 'Unknown Deck',
                'author': None,
                'url': t.get('url') or f"https://www.masterduelmeta.com/top-decks/{t.get('id','')}",
                'main_deck': [],
                'extra_deck': []
            }

            for c in cards:
                name = c.get('name') or c.get('cardName') or ''
                qty = c.get('quantity') or c.get('qty') or c.get('count') or 1
                is_extra = c.get('isExtra') or c.get('is_extra') or False
                if not name:
                    continue
                entry = {'name': name, 'count': int(qty)}
                if is_extra:
                    deck_info['extra_deck'].append(entry)
                else:
                    deck_info['main_deck'].append(entry)

            if save_deck_to_db(deck_info):
                imported += 1

        print(f"Imported {imported} deck(s) from local file {file_path}")
        return imported
    except Exception as e:
        print(f"Error importing deck-types from file: {e}")
        return 0


def dry_run_import_from_file(file_path, limit=5):
    """Parse local deck-types JSON and return a preview of deck_info objects without saving.

    Returns (total_entries, preview_list) where preview_list contains up to `limit` parsed deck_info dicts.
    """
    try:
        if not os.path.exists(file_path):
            return 0, []

        with open(file_path, 'r', encoding='utf-8') as f:
            types = json.load(f)

        total = len(types) if isinstance(types, list) else 1
        previews = []
        for i, t in enumerate(types if isinstance(types, list) else [types]):
            if i >= limit:
                break
            cards = t.get('cards') or []
            deck_info = {
                'name': t.get('name') or t.get('title') or f'Entry {i}',
                'author': t.get('author') or None,
                'url': t.get('url') or None,
                'main_deck': [],
                'extra_deck': []
            }
            for c in cards:
                name = c.get('name') or c.get('cardName') or ''
                qty = c.get('quantity') or c.get('qty') or c.get('count') or 1
                is_extra = c.get('isExtra') or c.get('is_extra') or False
                if not name:
                    continue
                entry = {'name': name, 'count': int(qty)}
                if is_extra:
                    deck_info['extra_deck'].append(entry)
                else:
                    deck_info['main_deck'].append(entry)

            previews.append(deck_info)

        return total, previews
    except Exception as e:
        print(f"Error in dry_run_import_from_file: {e}")
        return 0, []


def analyze_deck_types_file(file_path, sample_count=1):
    """Return a short analysis of the deck-types JSON file structure.

    Returns a dict containing top-level keys for the first sample entries and card object keys.
    """
    try:
        if not os.path.exists(file_path):
            return {'error': 'file not found'}

        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        samples = data if isinstance(data, list) else [data]
        analysis = {
            'total_entries': len(samples),
            'samples': []
        }

        for i, s in enumerate(samples[:sample_count]):
            keys = list(s.keys()) if isinstance(s, dict) else []
            card_keys = []
            cards = s.get('cards') if isinstance(s, dict) else None
            if isinstance(cards, list) and cards:
                first_card = cards[0]
                if isinstance(first_card, dict):
                    card_keys = list(first_card.keys())

            analysis['samples'].append({'index': i, 'top_keys': keys, 'card_keys': card_keys})

        return analysis
    except Exception as e:
        print(f"Error analyzing deck-types file: {e}")
        return {'error': str(e)}


def get_metadata(key: str):
    """Retrieve a string value from the metadata table. Returns None if missing."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            # Ensure metadata table exists (safe no-op if created elsewhere)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )""")
            cursor.execute("SELECT value FROM metadata WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception as e:
        print(f"Error reading metadata '{key}': {e}")
        return None


def set_metadata(key: str, value: str):
    """Set or replace a metadata key/value entry."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )""")
            cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()
            return True
    except Exception as e:
        print(f"Error writing metadata '{key}': {e}")
        return False

def get_card_usage_stats(card_name=None, limit=10):
    """Get statistics about card usage across all decks."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            if card_name:
                # Get decks using this specific card
                cursor.execute("""
                    SELECT 
                        c.card_name,
                        COUNT(DISTINCT c.deck_id) as deck_count,
                        AVG(c.quantity) as avg_copies,
                        SUM(CASE WHEN c.is_extra_deck = 1 THEN 1 ELSE 0 END) as extra_deck_count,
                        SUM(CASE WHEN c.is_extra_deck = 0 THEN 1 ELSE 0 END) as main_deck_count
                    FROM deck_cards c
                    WHERE c.card_name = ?
                    GROUP BY c.card_name
                """, (card_name,))
            else:
                # Get most used cards
                cursor.execute("""
                    SELECT 
                        c.card_name,
                        COUNT(DISTINCT c.deck_id) as deck_count,
                        AVG(c.quantity) as avg_copies,
                        SUM(CASE WHEN c.is_extra_deck = 1 THEN 1 ELSE 0 END) as extra_deck_count,
                        SUM(CASE WHEN c.is_extra_deck = 0 THEN 1 ELSE 0 END) as main_deck_count
                    FROM deck_cards c
                    GROUP BY c.card_name
                    ORDER BY deck_count DESC
                    LIMIT ?
                """, (limit,))
            
            return cursor.fetchall()
    except Exception as e:
        print(f"Error getting card usage stats: {e}")
        return []

def get_deck_stats():
    """Get general statistics about all decks in the database."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Get total counts
            cursor.execute("""
                SELECT 
                    COUNT(DISTINCT d.id) as total_decks,
                    COUNT(DISTINCT dc.card_name) as unique_cards,
                    COUNT(DISTINCT d.author) as unique_authors,
                    AVG((SELECT COUNT(*) FROM deck_cards dc2 WHERE dc2.deck_id = d.id AND dc2.is_extra_deck = 0)) as avg_main_deck_size,
                    AVG((SELECT COUNT(*) FROM deck_cards dc2 WHERE dc2.deck_id = d.id AND dc2.is_extra_deck = 1)) as avg_extra_deck_size,
                    MAX(d.created_at) as latest_deck_date
                FROM decks d
                LEFT JOIN deck_cards dc ON d.id = dc.deck_id
            """)
            
            return cursor.fetchone()
    except Exception as e:
        print(f"Error getting deck stats: {e}")
        return None

def get_decks_with_card(card_name):
    """Get all decks that contain a specific card."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Get all decks containing the card
            cursor.execute("""
                SELECT DISTINCT d.id, d.name, d.author, d.url, d.created_at
                FROM decks d
                JOIN deck_cards dc ON d.id = dc.deck_id
                WHERE dc.card_name = ?
                ORDER BY d.created_at DESC
            """, (card_name,))
            
            decks = []
            for deck_row in cursor.fetchall():
                deck_id, name, author, url, created_at = deck_row
                
                # Get main deck cards
                cursor.execute("""
                    SELECT card_name, quantity
                    FROM deck_cards
                    WHERE deck_id = ? AND is_extra_deck = 0
                """, (deck_id,))
                main_deck = [{'name': row[0], 'count': row[1]} for row in cursor.fetchall()]
                
                # Get extra deck cards
                cursor.execute("""
                    SELECT card_name, quantity
                    FROM deck_cards
                    WHERE deck_id = ? AND is_extra_deck = 1
                """, (deck_id,))
                extra_deck = [{'name': row[0], 'count': row[1]} for row in cursor.fetchall()]
                
                decks.append({
                    'name': name,
                    'author': author,
                    'url': url,
                    'main_deck': main_deck,
                    'extra_deck': extra_deck,
                    'created_at': created_at
                })
            
            return decks
    except Exception as e:
        print(f"Error retrieving decks from database: {e}")
        return []

def parse_deck_list(soup, url):
    """Parse a deck page and extract deck information."""
    deck_info = {
        'name': '',
        'author': '',
        'main_deck': [],
        'extra_deck': [],
        'url': url
    }

    try:
        # Method 1: Try to find deck name from various header elements
        for element in [
            soup.find('h1', class_='deck-title'),
            soup.find('h1', class_='title'),
            soup.find('div', class_='deck-name'),
            soup.find('h1'),
            soup.find('title')
        ]:
            if element:
                name_text = element.get_text(strip=True)
                if name_text and not name_text.lower() in ['master duel', 'deck builder', 'deck list']:
                    deck_info['name'] = name_text
                    break

        # Method 2: Try multiple author selectors
        for element in [
            soup.find('span', class_='username'),
            soup.find('div', class_='author'),
            soup.find('div', class_='player-name'),
            soup.find('a', class_='author-link')
        ]:
            if element:
                author_text = element.get_text(strip=True)
                if author_text and not author_text.lower() in ['unknown', 'anonymous']:
                    deck_info['author'] = author_text
                    break

        # Method 3: Multiple parsing strategies for deck sections
        parsed_cards = False

        # Strategy 1: Look for standard deck parts
        deck_parts = soup.find_all(['div', 'section'], class_=re.compile(r'deck.*part|deck-section', re.I))
        for part in deck_parts:
            header = part.find(['div', 'h3', 'h4'], class_='header') or part.find(['div', 'h3', 'h4'])
            if header:
                section_name = header.get_text(strip=True).lower()
                cards = part.find_all(['div', 'span'], class_=re.compile(r'card|card-item'))

                if cards:
                    parsed_cards = True
                    for card in cards:
                        try:
                            name_element = (
                                card.find(['span', 'div'], class_='name') or
                                card.find(['span', 'div'], class_='card-name') or
                                card.find('a')
                            )

                            count_element = (
                                card.find(['span', 'div'], class_='quantity') or
                                card.find(['span', 'div'], class_='count') or
                                card.find(string=re.compile(r'^\d+x?$'))
                            )

                            if name_element:
                                card_name = name_element.get_text(strip=True)
                                card_count = 1

                                if count_element:
                                    if hasattr(count_element, "get_text"):
                                        count_text = count_element.get_text(strip=True)
                                    else:
                                        count_text = str(count_element).strip()
                                    try:
                                        match = re.search(r'\d+', count_text)
                                        if match:
                                            card_count = int(match.group(0))
                                    except (ValueError, AttributeError):
                                        pass

                                target_list = deck_info['extra_deck'] if 'extra' in section_name else deck_info['main_deck']
                                target_list.append({'name': card_name, 'count': card_count})
                        except Exception as e:
                            print(f"Error parsing card in first strategy: {e}")

        # Strategy 2: Parse table layout
        if not parsed_cards:
            tables = soup.find_all('table', class_=re.compile(r'deck.*table|card.*table'))
            for table in tables:
                try:
                    is_extra = bool(table.find(string=re.compile(r'Extra Deck', re.I)))
                    rows = table.find_all('tr')

                    for row in rows:
                        try:
                            name_cell = row.find(['td', 'th'], class_=re.compile(r'name|card'))
                            count_cell = row.find(['td', 'th'], class_=re.compile(r'count|quantity'))

                            if name_cell:
                                card_name = name_cell.get_text(strip=True)
                                card_count = 1

                                if count_cell:
                                    count_text = count_cell.get_text(strip=True)
                                    try:
                                        match = re.search(r'\d+', count_text)
                                        if match:
                                            card_count = int(match.group())
                                    except (ValueError, AttributeError):
                                        pass

                                target_list = deck_info['extra_deck'] if is_extra else deck_info['main_deck']
                                target_list.append({'name': card_name, 'count': card_count})
                                parsed_cards = True
                        except Exception as e:
                            print(f"Error parsing table row: {e}")
                except Exception as e:
                    print(f"Error parsing table: {e}")

        # Strategy 3: Parse plain text format
        if not parsed_cards:
            text_containers = soup.find_all(['div', 'pre', 'code'], class_=re.compile(r'deck.*list|card.*list'))
            for container in text_containers:
                text_content = container.get_text(separator='\n').strip()
                is_extra = bool(re.search(r'Extra Deck|Extra:', text_content, re.I))
                for line in text_content.splitlines():
                    try:
                        m = re.match(r'^\s*(\d+)x?\s+(.+)$', line)
                        if m:
                            count = int(m.group(1))
                            name = m.group(2).strip()
                            target_list = deck_info['extra_deck'] if is_extra else deck_info['main_deck']
                            target_list.append({'name': name, 'count': count})
                            parsed_cards = True
                    except Exception:
                        pass

        # Clean up the results (remove duplicate names, preserve first occurrence)
        for section in ['main_deck', 'extra_deck']:
            seen = set()
            cleaned = []
            for card in deck_info[section]:
                if card['name'] not in seen:
                    seen.add(card['name'])
                    cleaned.append(card)
            deck_info[section] = cleaned

    except Exception as e:
        print(f"Error parsing deck: {e}")

    return deck_info


async def send_response(interaction: discord.Interaction, content: Optional[str] = None, embed: Optional[discord.Embed] = None, view: Optional[ui.View] = None, ephemeral: bool = False):
    """Safely send a response for an interaction.

    Tries in order:
    - interaction.response.send_message (if not already done)
    - interaction.followup.send (if response already created)
    - interaction.channel.send as a last-resort fallback
    """
    send_kwargs = {
        'content': content,
        'embed': embed,
        'view': view,
    }
    # Filter out None values
    send_kwargs = {k: v for k, v in send_kwargs.items() if v is not None}

    try:
        if not interaction.response.is_done():
            if ephemeral:
                send_kwargs['ephemeral'] = True
            await interaction.response.send_message(**send_kwargs)
        else:
            # ephemeral is not supported in followup.send
            await interaction.followup.send(**send_kwargs)
    except (discord.errors.NotFound, discord.errors.InteractionResponded):
        try:
            if isinstance(interaction.channel, (discord.TextChannel, discord.Thread, discord.DMChannel, discord.GroupChannel, discord.VoiceChannel)):
                await interaction.channel.send(**send_kwargs)
            else:
                print("Cannot send message: channel does not support sending messages or is missing.")
        except Exception as e:
            print(f"Fallback channel send also failed: {e}")
    except Exception as e:
        print(f"An unexpected error occurred in send_response: {e}")

def format_deck_section(deck_list, title=None):
    """Format a deck section (main/extra) into a string suitable for an embed field."""
    try:
        if not deck_list:
            return ""
        # Normalize entries and sort by count descending then name
        normalized = [
            {'name': c.get('name', '').strip(), 'count': int(c.get('count', 1))}
            for c in deck_list
            if c and c.get('name')
        ]
        normalized.sort(key=lambda x: (-x['count'], x['name'].lower()))
        lines = [f"{entry['count']}x {entry['name']}" for entry in normalized]
        return "\n".join(lines)
    except Exception:
        # On any error, fall back to a simple safe representation
        try:
            return "\n".join(f"{c.get('count',1)}x {c.get('name','')}" for c in deck_list if c and c.get('name'))
        except Exception:
            return ""

@client.tree.command(name="decks", description="Find decks that use a specific card on Master Duel Meta.")
@app_commands.describe(card_name="The name of the card to find decks for.")
@app_commands.autocomplete(card_name=card_name_autocomplete)
async def search_decks(interaction: discord.Interaction, card_name: str):
    """Finds and lists decks that include the specified card with their complete decklists."""
    await interaction.response.defer()

    if not card_database:
        await interaction.followup.send("Card database is not loaded. Please check the bot's console for errors.")
        return

    # Use our fuzzy matching to find the card
    matches = []
    search_name = card_name.lower()
    if search_name.startswith("number"):
        matches = sorted([card for card in card_database.keys() if card.lower().startswith(search_name)])
    else:
        matches = get_card_suggestions(card_name, max_suggestions=1)
    
    if not matches:
        await send_response(interaction, content=f"Card '{card_name}' not found. Please check the spelling.")
        return
    
    # Use the best match
    matched_card_name = matches[0]
    print(f"Found card match: {matched_card_name}")
    
    try:
        # First, check the local database for decks
        decks = get_decks_with_card(matched_card_name)
        
        # If no decks are in the DB, try to fetch from the API and populate the DB
        if not decks:
            print(f"No cached decks found for {matched_card_name}. Fetching from API...")
            imported_count = import_deck_types_to_db(limit=50) # Limit to 50 to avoid long waits
            if imported_count > 0:
                # Retry getting decks from the database
                decks = get_decks_with_card(matched_card_name)

        if not decks:
            await send_response(interaction, content=f"No public decks found for **{matched_card_name}**.")
            return

        # Create an embed for each deck
        for deck in decks[:5]: # Limit to 5 decks
            embed = discord.Embed(
                title=deck['name'] or "Unnamed Deck",
                url=deck['url'],
                color=discord.Color.blue()
            )
            
            if deck['author']:
                embed.set_author(name=f"by {deck['author']}")

            # Format and add Main Deck
            main_deck_text = format_deck_section(deck['main_deck'])
            if main_deck_text:
                if len(main_deck_text) > 1024:
                    main_deck_text = main_deck_text[:1021] + "..."
                embed.add_field(name="Main Deck", value=main_deck_text, inline=False)

            # Format and add Extra Deck
            extra_deck_text = format_deck_section(deck['extra_deck'])
            if extra_deck_text:
                if len(extra_deck_text) > 1024:
                    extra_deck_text = extra_deck_text[:1021] + "..."
                embed.add_field(name="Extra Deck", value=extra_deck_text, inline=False)

            embed.set_footer(text="Powered by MasterDuelMeta.com")
            
            await send_response(interaction, embed=embed)

    except Exception as e:
        await send_response(interaction, content=f"An unexpected error occurred: {e}")


@client.tree.command(name="banlist", description="Check the banlist status of a card.")
@app_commands.describe(card_name="The name of the card to check.")
async def search_banlist(interaction: discord.Interaction, card_name: str):
    """Checks the banlist status of a card on Master Duel Meta."""
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
    except discord.errors.NotFound:
        print("Interaction not found when deferring banlist command; will fallback to channel messages where possible")
    except Exception as e:
        print(f"Error while deferring interaction in banlist: {e}")

    url = "https://www.masterduelmeta.com/forbidden-limited-list"

    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # Find all card images with an alt text
        card_images = soup.find_all('img', alt=True)

        found_card = None
        for img in card_images:
            alt_text = img.get('alt', "")
            if isinstance(alt_text, list):
                alt_text = " ".join(alt_text)
            if str(card_name).lower() in str(alt_text).lower():
                found_card = img
                break

        if not found_card:
            await send_response(interaction, content=f"**{card_name.title()}** is not on the Forbidden/Limited list.")
            return

        # Find the status (Forbidden, Limited, Semi-Limited)
        status_header = found_card.find_previous('h2')
        if status_header:
            status = status_header.get_text(strip=True)
        else:
            status = "Unknown Status"

        card_name_official = found_card['alt']
        card_image_url = found_card['src']

        # --- EMBED CREATION ---
        embed = discord.Embed(
            title=f"{card_name_official} - {status}",
            color=discord.Color.dark_red()
        )
        embed.set_thumbnail(url=card_image_url)
        embed.set_footer(text="Powered by MasterDuelMeta.com")

        await send_response(interaction, embed=embed)

    except requests.exceptions.RequestException as e:
        await send_response(interaction, content=f"An error occurred while trying to fetch data: {e}")
    except Exception as e:
        await send_response(interaction, content=f"An unexpected error occurred: {e}")



@client.tree.command(name="latest_pack", description="Get the latest selection or secret pack from the shop.")
async def latest_pack(interaction: discord.Interaction):
    """Retrieves the latest selection or secret pack from Master Duel Meta."""
    await interaction.response.defer()

    pack_type = "Selection"
    url = "https://www.masterduelmeta.com/selection-packs"
    latest_pack = None

    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        # If selection packs not found, try secret packs
        if response.status_code == 404:
            pack_type = "Secret"
            url = "https://www.masterduelmeta.com/secret-packs"
            response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        latest_date = None

        for pack_div in soup.find_all('div', class_='pack'):
            name_element = pack_div.find('h2')
            date_element = pack_div.find('time')
            image_element = pack_div.find('img')

            if name_element and date_element and image_element:
                pack_name = name_element.get_text(strip=True)
                pack_date_str = str(date_element.get('datetime', ''))
                pack_image_url = image_element.get('src')
                pack_url = ""
                link = pack_div.find('a')
                href = str(link.get('href', '')) if link else ''
                if href.startswith('/'):
                    pack_url = "https://www.masterduelmeta.com" + href

                if pack_date_str:
                    pack_date = datetime.fromisoformat(pack_date_str.replace('Z', '+00:00'))
                    if latest_date is None or pack_date > latest_date:
                        latest_date = pack_date
                        latest_pack = {
                            "name": pack_name,
                            "image_url": pack_image_url,
                            "url": pack_url,
                            "date": pack_date
                        }

        if not latest_pack:
            await send_response(interaction, content=f"Could not find the latest {pack_type.lower()} pack. The website structure might have changed.")
            return

        # --- EMBED CREATION ---
        embed = discord.Embed(
            title=f"Latest {pack_type} Pack: {latest_pack['name']}",
            color=discord.Color.dark_blue(),
            url=latest_pack['url']
        )
        embed.set_image(url=latest_pack['image_url'])
        embed.set_footer(text=f"Released on {latest_pack['date'].strftime('%Y-%m-%d')}")

        await send_response(interaction, embed=embed)

    except requests.exceptions.RequestException as e:
        await send_response(interaction, content=f"An error occurred while trying to fetch data: {e}")
    except Exception as e:
        await send_response(interaction, content=f"An unexpected error occurred: {e}")



@client.tree.command(name="cardstats", description="Get usage statistics for a card or view most used cards.")
@app_commands.describe(card_name="The name of the card to get statistics for. Leave empty to see most used cards.")
@app_commands.autocomplete(card_name=card_name_autocomplete)
async def card_stats(interaction: discord.Interaction, card_name: str = ""):
    """Get statistics about how a card is used across all stored decks."""
    await interaction.response.defer()
    
    try:
        if card_name:
            stats = get_card_usage_stats(card_name)
            if not stats:
                await interaction.followup.send(f"No data found for card: {card_name}")
                return
            
            stat = stats[0]  # We only have one card's stats
            embed = discord.Embed(
                title=f"Card Statistics: {stat[0]}",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="Usage Stats",
                value=f"""
                • Used in {stat[1]} decks
                • Average copies per deck: {stat[2]:.1f}
                • Main Deck appearances: {stat[4]}
                • Extra Deck appearances: {stat[3]}
                """,
                inline=False
            )
        else:
            # Show most used cards
            stats = get_card_usage_stats(limit=10)
            if not stats:
                await interaction.followup.send("No deck data available.")
                return
            
            embed = discord.Embed(
                title="Most Used Cards",
                color=discord.Color.blue()
            )
            
            for stat in stats:
                card_name = stat[0]
                deck_count = stat[1]
                avg_copies = stat[2]
                embed.add_field(
                    name=card_name,
                    value=f"Used in {deck_count} decks (avg. {avg_copies:.1f} copies)",
                    inline=False
                )
        
        embed.set_footer(text="Based on stored deck data")
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}")

@client.tree.command(name="deckstats", description="Get statistics about all stored decks.")
async def deck_stats_command(interaction: discord.Interaction):
    """Display general statistics about all stored decks."""
    await interaction.response.defer()
    
    try:
        stats = get_deck_stats()
        if not stats:
            await interaction.followup.send("No deck data available.")
            return
        
        total_decks, unique_cards, unique_authors, avg_main, avg_extra, latest = stats
        
        embed = discord.Embed(
            title="Deck Database Statistics",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="Overall Stats",
            value=f"""
            • Total Decks: {total_decks}
            • Unique Cards Used: {unique_cards}
            • Unique Authors: {unique_authors}
            • Average Main Deck Size: {avg_main:.1f}
            • Average Extra Deck Size: {avg_extra:.1f}
            • Latest Deck Added: {latest}
            """,
            inline=False
        )
        
        # Also get top 5 most used cards
        top_cards = get_card_usage_stats(limit=5)
        if top_cards:
            top_cards_text = "\n".join(
                f"• {card[0]}: {card[1]} decks"
                for card in top_cards
            )
            embed.add_field(
                name="Most Used Cards",
                value=top_cards_text,
                inline=False
            )
        
        embed.set_footer(text="Based on stored deck data")
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}")

@client.tree.command(name="cleanup", description="Remove old deck data from the database.")
@app_commands.describe(days="Number of days of deck data to keep (default: 30)")
@app_commands.default_permissions(administrator=True)
async def cleanup_decks_command(interaction: discord.Interaction, days: int = 30):
    """Clean up old deck data from the database."""
    
    await interaction.response.defer()
    
    try:
        deleted_count = cleanup_old_decks(days)
        await interaction.followup.send(
            f"Successfully cleaned up {deleted_count} decks older than {days} days."
        )
    except Exception as e:
        await interaction.followup.send(f"An error occurred during cleanup: {e}")


@client.tree.command(name="import_decktypes", description="Import deck-types and their decks from MasterDuelMeta API into the database.")
@app_commands.describe(limit="Maximum number of deck-types to import (use 0 for no limit)")
@app_commands.default_permissions(administrator=True)
async def import_decktypes_command(interaction: discord.Interaction, limit: int = 100):
    """Import deck-types from MasterDuelMeta and save decks to the local DB (admin only)."""
    await interaction.response.defer()
    try:
        # Convert 0 to None for unlimited
        api_limit = None if limit == 0 else limit
        imported = import_deck_types_to_db(limit=api_limit)
        await interaction.followup.send(f"Imported {imported} deck(s) from the MasterDuelMeta API.")
    except Exception as e:
        await interaction.followup.send(f"Failed to import deck-types: {e}")


@client.tree.command(name="import_decktypes_local", description="Import deck-types from a local JSON file into the database.")
@app_commands.describe(path="Path to local JSON file (absolute or relative)", limit="Maximum number of entries to import (0 = no limit)")
@app_commands.default_permissions(administrator=True)
async def import_decktypes_local_command(interaction: discord.Interaction, path: str, limit: int = 100):
    """Admin command to import deck-types from a local JSON file."""
    await interaction.response.defer()
    try:
        api_limit = None if limit == 0 else limit
        imported = import_deck_types_from_file(path, limit=api_limit)
        await interaction.followup.send(f"Imported {imported} deck(s) from local file: {path}")
    except Exception as e:
        await interaction.followup.send(f"Failed to import from local file: {e}")

@client.tree.command(name="top_decks", description="Get the top tournament decks from the tier list.")
async def top_decks(interaction: discord.Interaction):
    """Retrieves the top tournament decks from Master Duel Meta."""
    await interaction.response.defer()

    url = "https://www.masterduelmeta.com/tier-list"

    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        embed = discord.Embed(
            title="Top Tournament Decks",
            color=discord.Color.dark_purple(),
            url=url
        )

        # Find all tier sections (e.g., Tier 1, Tier 2)
        tier_sections = soup.find_all('div', class_=re.compile(r'Tier.*?'))

        if not tier_sections:
            await interaction.followup.send("Could not find any tier sections on the page. The website structure might have changed.")
            return

        for section in tier_sections:
            tier_name_header = section.find('h2')
            if not tier_name_header:
                continue
            tier_name = tier_name_header.get_text(strip=True)
            deck_items = section.find_all('div', class_='deck')

            if not deck_items:
                continue

            deck_links = []
            for item in deck_items:
                deck_name_span = item.find('span', class_='deck-name')
                deck_link_a = item.find('a', href=True)

                if deck_name_span and deck_link_a:
                    deck_name = deck_name_span.get_text(strip=True)
                    deck_url = "https://www.masterduelmeta.com" + str(deck_link_a['href'])
                    deck_links.append(f"[{deck_name}]({deck_url})")
            
            if deck_links:
                embed.add_field(name=tier_name, value='\n'.join(deck_links), inline=False)

        if not embed.fields:
            await interaction.followup.send("No decks found on the tier list page.")
            return

        embed.set_footer(text="Powered by MasterDuelMeta.com")

        await interaction.followup.send(embed=embed)

    except requests.exceptions.RequestException as e:
        await interaction.followup.send(f"An error occurred while trying to fetch data: {e}")
    except Exception as e:
        await interaction.followup.send(f"An unexpected error occurred: {e}")




@client.tree.command(name="packs", description="Show all packs in Master Duel and new ones.")
async def packs(interaction: discord.Interaction):
    """Shows all packs in Master Duel and new ones."""
    await interaction.response.defer()

    try:
        # Step 1: Fetch all cards for the "Master Duel" format
        response = requests.get("https://db.ygoprodeck.com/api/v7/cardinfo.php?format=master%20duel")
        response.raise_for_status()
        card_data = response.json()

        # Step 2: Extract unique set names
        pack_names = set()
        for card in card_data.get("data", []):
            if "card_sets" in card:
                for card_set in card["card_sets"]:
                    pack_names.add(card_set["set_name"])

        # Step 3: Fetch new packs from Master Duel Meta
        secret_packs_url = "https://www.masterduelmeta.com/secret-packs"
        response = requests.get(secret_packs_url, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        new_packs = set()
        thirty_days_ago = datetime.now() - timedelta(days=30)

        for pack_div in soup.find_all('div', class_='pack'):
            date_element = pack_div.find('time')
            if date_element:
                pack_date_str = str(date_element.get('datetime', ''))
                if pack_date_str:
                    pack_date = datetime.fromisoformat(pack_date_str.replace('Z', '+00:00'))
                    if pack_date > thirty_days_ago:
                        name_element = pack_div.find('h2')
                        if name_element:
                            new_packs.add(name_element.get_text(strip=True))

        # Step 4: Format the output
        all_packs = sorted(list(pack_names))
        
        embed = discord.Embed(
            title="Yu-Gi-Oh! Master Duel Packs",
            color=discord.Color.purple()
        )

        if new_packs:
            new_packs_text = "\n".join(f"🔥 {pack}" for pack in new_packs)
            embed.add_field(name="New & Upcoming Packs", value=new_packs_text, inline=False)

        if all_packs:
            # Paginate the packs list
            packs_per_page = 10
            pages = [all_packs[i:i + packs_per_page] for i in range(0, len(all_packs), packs_per_page)]
            
            for i, page in enumerate(pages):
                if i > 2: # Limit to 3 pages to avoid huge messages
                    embed.add_field(name=f"And {len(all_packs) - (i * packs_per_page)} more...", value="...", inline=False)
                    break
                embed.add_field(name=f"Packs (Page {i+1})", value="\n".join(page), inline=True)


        embed.set_footer(text="Powered by YGOPRODeck and Master Duel Meta")

        await send_response(interaction, embed=embed)

    except requests.exceptions.RequestException as e:
        await send_response(interaction, content=f"An error occurred while trying to fetch data: {e}")
    except Exception as e:
        await send_response(interaction, content=f"An unexpected error occurred: {e}")



# --- RUN THE BOT ---
# It's a best practice to load the token from an environment variable.
# Create a file named .env and add the line: DISCORD_TOKEN="YOUR_TOKEN_HERE"
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN is None:
    print("ERROR: DISCORD_TOKEN environment variable not found.")
    print("Please create a .env file and add your Discord bot token.")
else:
    load_card_data()
    client.run(TOKEN)