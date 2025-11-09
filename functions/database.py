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