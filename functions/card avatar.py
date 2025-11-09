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