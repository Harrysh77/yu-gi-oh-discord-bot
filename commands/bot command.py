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
    