from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
from datetime import datetime, timedelta
import hashlib

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Supabase credentials mancanti")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- CATEGORIE ----------
def get_categories():
    res = supabase.table("categories").select("*").execute()
    return res.data

def add_category(name, parent_id=None):
    supabase.table("categories").insert({"name": name, "parent_id": parent_id}).execute()

def delete_category(category_id):
    supabase.table("categories").delete().eq("id", category_id).execute()

def get_category_name(category_id):
    res = supabase.table("categories").select("name").eq("id", category_id).execute()
    return res.data[0]["name"] if res.data else "Sconosciuta"

# ---------- CANALI ----------
def get_channels():
    res = supabase.table("channels").select("*").eq("active", True).execute()
    return res.data

def add_channel(username, category_id=None):
    supabase.table("channels").upsert(
        {"username": username, "category_id": category_id, "active": True},
        on_conflict="username"
    ).execute()

def delete_channel(username):
    supabase.table("channels").delete().eq("username", username).execute()

def reset_channels():
    supabase.table("channels").delete().neq("id", 0).execute()
    print("🧹 Tutti i canali sono stati rimossi.")

# ---------- MESSAGGI ----------
def save_message(raw_text, channel_username, message_id):
    expires_at = (datetime.now() + timedelta(days=7)).isoformat()
    res = supabase.table("messages").insert({
        "raw_text": raw_text,
        "channel_username": channel_username,
        "message_id": message_id,
        "expires_at": expires_at
    }).execute()
    return res.data[0]["id"]

def add_message_hash(message_id, raw_text):
    hash_val = hashlib.md5(raw_text.encode()).hexdigest()
    supabase.table("message_hashes").upsert(
        {"hash": hash_val, "message_id": message_id},
        on_conflict="hash"
    ).execute()

def assign_categories(message_id, category_ids):
    for cat_id in category_ids:
        supabase.table("message_categories").insert({
            "message_id": message_id,
            "category_id": cat_id
        }).execute()
    supabase.table("messages").update({"categorized": True}).eq("id", message_id).execute()

def mark_categorization_failed(message_id):
    """Incrementa il contatore di tentativi falliti e lo restituisce."""
    res = supabase.table("messages").select("categorization_attempts").eq("id", message_id).execute()
    attempts = (res.data[0]["categorization_attempts"] if res.data else 0) or 0
    attempts += 1
    supabase.table("messages").update({"categorization_attempts": attempts}).eq("id", message_id).execute()
    return attempts

def get_uncategorized_messages(limit=20):
    """Messaggi ancora in coda di categorizzazione (falliti per rate-limit/errore tecnico)."""
    res = supabase.table("messages").select("*").eq("categorized", False)\
        .order("received_at", desc=False).limit(limit).execute()
    return res.data

# ---------- RECUPERO MESSAGGI ----------
def get_messages_recent(hours=24):
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    res = supabase.table("messages").select("*").gt("received_at", since).order("received_at", desc=True).execute()
    return res.data

def get_messages_week():
    since = (datetime.now() - timedelta(days=7)).isoformat()
    res = supabase.table("messages").select("*").gt("received_at", since).order("received_at", desc=True).execute()
    return res.data

def get_messages_by_category(category_id, hours=24):
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    res = supabase.table("messages").select(
        "*, message_categories!inner(category_id)"
    ).eq("message_categories.category_id", category_id).gt("received_at", since).order("received_at", desc=True).execute()
    return res.data

def get_messages_by_category_week(category_id):
    since = (datetime.now() - timedelta(days=7)).isoformat()
    res = supabase.table("messages").select(
        "*, message_categories!inner(category_id)"
    ).eq("message_categories.category_id", category_id).gt("received_at", since).order("received_at", desc=True).execute()
    return res.data

def delete_expired_messages():
    now = datetime.now().isoformat()
    supabase.table("messages").delete().lt("expires_at", now).execute()

def delete_all_messages():
    """Cancella TUTTE le offerte (utile per ripulire i test).
    message_categories e message_hashes hanno ON DELETE CASCADE su messages,
    quindi vengono rimosse automaticamente."""
    supabase.table("messages").delete().neq("id", 0).execute()

# ---------- RICERCA ----------
def search_messages(keyword, limit=15):
    res = supabase.table("messages").select("*")\
        .ilike("raw_text", f"%{keyword}%")\
        .order("received_at", desc=True).limit(limit).execute()
    return res.data

# ---------- PREFERITI (notifiche istantanee) ----------
def get_favorite_category_ids(chat_id):
    res = supabase.table("favorites").select("category_id").eq("chat_id", chat_id).execute()
    return [f["category_id"] for f in res.data]

def add_favorite(chat_id, category_id):
    supabase.table("favorites").upsert(
        {"chat_id": chat_id, "category_id": category_id},
        on_conflict="chat_id,category_id"
    ).execute()

def remove_favorite(chat_id, category_id):
    supabase.table("favorites").delete().eq("chat_id", chat_id).eq("category_id", category_id).execute()

def get_chats_favoriting(category_id):
    res = supabase.table("favorites").select("chat_id").eq("category_id", category_id).execute()
    return [f["chat_id"] for f in res.data]