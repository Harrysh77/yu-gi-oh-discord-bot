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