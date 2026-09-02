import asyncio
import html as html_lib
import logging
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.errors import UserAlreadyParticipantError, ChannelPrivateError, FloodWaitError
from config import API_ID, API_HASH, PHONE_NUMBER, TELETHON_SESSION
from database import (
    save_message, assign_categories, add_message_hash,
    mark_categorization_failed, get_uncategorized_messages,
    get_chats_favoriting, get_category_name
)
from categorizer import categorize_message, CategorizationError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = None
_bot = None

def set_bot(bot_instance):
    global _bot
    _bot = bot_instance

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

            session = StringSession(TELETHON_SESSION) if TELETHON_SESSION else "session"
            client = TelegramClient(session, API_ID, API_HASH)
            await client.start(phone=PHONE_NUMBER)
            print("📡 Client connesso!")

            chat_entities = []
            for username in channel_usernames:
                try:
                    entity = await client.get_entity(username)
                    print(f"✅ Risolto @{username} → ID {entity.id}")

                    try:
                        await client(JoinChannelRequest(username))
                        print(f"✅ Iscritto/già iscritto a @{username}")
                    except UserAlreadyParticipantError:
                        print(f"✅ Già iscritto a @{username}")
                    except ChannelPrivateError:
                        print(f"❌ @{username} è privato o non accessibile: saltato")
                        continue
                    except FloodWaitError as e:
                        print(f"⏳ Flood wait: aspetto {e.seconds}s")
                        await asyncio.sleep(e.seconds)
                        print(f"⚠️ @{username} saltato per flood")
                        continue
                    except Exception as e:
                        print(f"⚠️ Impossibile iscriversi a @{username}: {e}")
                        continue

                    chat_entities.append(entity)
                    print(f"✅ @{username} aggiunto all'ascolto")

                except Exception as e:
                    print(f"❌ Errore risoluzione @{username}: {e}")
                    continue

            if not chat_entities:
                print("❌ Nessun canale valido. Aspetto...")
                await asyncio.sleep(60)
                continue

            # Handler principale per i canali monitorati
            @client.on(events.NewMessage(chats=chat_entities))
            async def handler(event):
                # LOG DI DEBUG: stampa ogni messaggio ricevuto da canali monitorati
                chat = await event.get_chat()
                username = chat.username if chat.username else str(chat.id)
                text = event.message.text or "[nessun testo]"
                logger.info(f"📨 DEBUG - Messaggio ricevuto da @{username}: {text[:100]}...")
                await process_message(event.message)

            # Handler di debug OPZIONALE: stampa TUTTI i messaggi (anche da canali non monitorati)
            # Decommenta le due righe seguenti per abilitare
            # @client.on(events.NewMessage)
            # async def debug_all(event):
            #     chat = await event.get_chat()
            #     username = chat.username if chat.username else str(chat.id)
            #     text = event.message.text or "[nessun testo]"
            #     logger.info(f"🐞 DEBUG ALL - Messaggio da {username}: {text[:50]}...")

            print(f"👂 In ascolto attivo su {len(chat_entities)} canali.")

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
            logger.info("📭 Messaggio senza testo, ignorato.")
            return

        channel = message.chat.username or str(message.chat.id)
        logger.info(f"📩 Messaggio da @{channel}: {text[:100]}... (lunghezza {len(text)})")

        msg_id = save_message(text, channel, message.id)
        add_message_hash(msg_id, text)
        await try_categorize(msg_id, text, channel, message.id)

    except Exception as e:
        logger.error(f"❌ Errore processamento: {e}", exc_info=True)

async def try_categorize(msg_id, text, channel, tg_message_id):
    try:
        logger.info(f"🔄 Tentativo categorizzazione per messaggio {msg_id}")
        category_ids = categorize_message(text)
        assign_categories(msg_id, category_ids)
        logger.info(f"🏷️ Categorie assegnate: {category_ids}")
        await notify_favorites(category_ids, channel, tg_message_id, text)
    except CategorizationError as e:
        attempts = mark_categorization_failed(msg_id)
        logger.warning(f"⏳ Categorizzazione fallita (tentativo {attempts}/{MAX_CATEGORIZATION_ATTEMPTS}): {e}")
        if attempts >= MAX_CATEGORIZATION_ATTEMPTS:
            logger.warning(f"⚠️ Troppi tentativi falliti per il messaggio {msg_id} ({attempts}), assegno categoria di fallback (ID 2)")
            assign_categories(msg_id, [2])
            await notify_favorites([2], channel, tg_message_id, text)

async def retry_pending_categorizations():
    while True:
        await asyncio.sleep(RETRY_INTERVAL_SECONDS)
        try:
            pending = get_uncategorized_messages(limit=20)
            if pending:
                logger.info(f"🔁 Ricategorizzazione in coda: {len(pending)} messaggi da riprovare")
            for m in pending:
                await try_categorize(m["id"], m["raw_text"], m["channel_username"], m["message_id"])
        except Exception as e:
            logger.error(f"❌ Errore nel worker di retry categorizzazione: {e}", exc_info=True)

async def notify_favorites(category_ids, channel, tg_message_id, text):
    if _bot is None:
        logger.warning("⚠️ Notifiche preferiti saltate: bot non ancora pronto")
        return
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
                logger.error(f"❌ Notifica preferiti fallita per chat {chat_id}: {e}")

async def restart_reader():
    global client
    if client:
        await client.disconnect()
        print("🔄 Reader in riavvio...")