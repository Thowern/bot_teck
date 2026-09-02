import asyncio
import html as html_lib
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telegram import Bot
from config import API_ID, API_HASH, PHONE_NUMBER, BOT_TOKEN, TELETHON_SESSION
from database import (
    save_message, assign_categories, add_message_hash,
    mark_categorization_failed, get_uncategorized_messages,
    get_chats_favoriting, get_category_name
)
from categorizer import categorize_message, CategorizationError

client = None
reader_task = None
_bot = Bot(BOT_TOKEN)

# Dopo questo numero di tentativi falliti, il messaggio viene comunque
# etichettato con la categoria di fallback per non restare in coda per sempre
# (es. se il messaggio stesso è malformato, non un problema di Groq).
MAX_CATEGORIZATION_ATTEMPTS = 15
RETRY_INTERVAL_SECONDS = 120

def _esc(t):
    return html_lib.escape(str(t)) if t else ""

async def start_reader():
    global client

    while True:
        try:
            from database import get_channels
            channels = get_channels()
            channel_usernames = [ch["username"] for ch in channels]

            if not channel_usernames:
                print("📡 Nessun canale. In attesa...")
                await asyncio.sleep(60)
                continue

            print(f"📡 Monitoraggio: {', '.join(channel_usernames)}")

            # In locale (senza TELETHON_SESSION nel .env) usa un file su disco
            # e la prima volta chiede il codice via input() sulla console.
            # Su Render (o altro host con filesystem effimero) imposta invece
            # TELETHON_SESSION con la stringa generata da generate_session.py:
            # in quel caso non serve alcun login interattivo.
            session = StringSession(TELETHON_SESSION) if TELETHON_SESSION else "session"
            client = TelegramClient(session, API_ID, API_HASH)
            await client.start(phone=PHONE_NUMBER)
            print("📡 Client connesso!")

            @client.on(events.NewMessage(chats=channel_usernames))
            async def handler(event):
                await process_message(event.message)

            try:
                await asyncio.wait_for(client.run_until_disconnected(), timeout=3600)
            except asyncio.TimeoutError:
                print("⏰ Timeout, riavvio reader...")
                continue

        except Exception as e:
            print(f"❌ Reader error: {e}")
            await asyncio.sleep(10)

async def process_message(message):
    try:
        text = message.text
        if not text:
            return

        channel = message.chat.username or str(message.chat.id)
        print(f"📩 Messaggio da @{channel}: {text[:50]}...")

        msg_id = save_message(text, channel, message.id)
        add_message_hash(msg_id, text)
        await try_categorize(msg_id, text, channel, message.id)

    except Exception as e:
        print(f"❌ Errore processamento: {e}")

async def try_categorize(msg_id, text, channel, tg_message_id):
    """Prova a categorizzare un messaggio. Se Groq fallisce (rate limit,
    modello giù, ecc.) NON assegna un fallback subito: il messaggio resta
    'non categorizzato' e verrà ritentato dal worker di coda."""
    try:
        category_ids = categorize_message(text)
        assign_categories(msg_id, category_ids)
        print(f"🏷️ Categorie assegnate: {category_ids}")
        await notify_favorites(category_ids, channel, tg_message_id, text)
    except CategorizationError as e:
        attempts = mark_categorization_failed(msg_id)
        if attempts >= MAX_CATEGORIZATION_ATTEMPTS:
            print(f"⚠️ Troppi tentativi falliti per il messaggio {msg_id} ({attempts}), assegno categoria di fallback")
            assign_categories(msg_id, [2])
            await notify_favorites([2], channel, tg_message_id, text)
        else:
            print(f"⏳ Categorizzazione in coda (tentativo {attempts}/{MAX_CATEGORIZATION_ATTEMPTS}): {e}")

async def retry_pending_categorizations():
    """Worker in background: ogni RETRY_INTERVAL_SECONDS riprova a
    categorizzare i messaggi rimasti in coda per un fallimento tecnico
    (es. rate limit Groq) invece di scaricarli su 'Tech Generale'."""
    while True:
        await asyncio.sleep(RETRY_INTERVAL_SECONDS)
        try:
            pending = get_uncategorized_messages(limit=20)
            if pending:
                print(f"🔁 Ricategorizzazione in coda: {len(pending)} messaggi da riprovare")
            for m in pending:
                await try_categorize(m["id"], m["raw_text"], m["channel_username"], m["message_id"])
        except Exception as e:
            print(f"❌ Errore nel worker di retry categorizzazione: {e}")

async def notify_favorites(category_ids, channel, tg_message_id, text):
    """Invia una notifica istantanea a chi ha messo tra i preferiti una
    delle categorie appena assegnate a questo messaggio."""
    notified_chats = set()
    link = f"https://t.me/{channel}/{tg_message_id}"
    for cat_id in category_ids:
        for chat_id in get_chats_favoriting(cat_id):
            if chat_id in notified_chats:
                continue
            notified_chats.add(chat_id)
            cat_name = get_category_name(cat_id)
            msg = (
                f"⭐ Nuova offerta in <b>{_esc(cat_name)}</b>\n\n"
                f"{_esc(text[:500])}\n\n"
                f"🔗 <a href=\"{link}\">Vedi messaggio originale</a>"
            )
            try:
                await _bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
            except Exception as e:
                print(f"❌ Notifica preferiti fallita per chat {chat_id}: {e}")

async def restart_reader():
    global client
    if client:
        await client.disconnect()
        print("🔄 Reader in riavvio...")