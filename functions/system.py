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