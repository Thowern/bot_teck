import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH")
PHONE_NUMBER = os.getenv("PHONE_NUMBER")
TELETHON_SESSION = os.getenv("TELETHON_SESSION")  # generata con generate_session.py, usata su Render
PORT = int(os.getenv("PORT", 8080))  # Render assegna la porta dinamicamente
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN non trovato")
if not API_ID or not API_HASH:
    print("⚠️ API_ID/API_HASH mancanti, il reader non funzionerà")