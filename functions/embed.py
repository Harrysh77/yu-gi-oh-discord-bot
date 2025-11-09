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
