import asyncio
import threading
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from config import BOT_TOKEN
from handlers import register_handlers, start
from reader import start_reader, retry_pending_categorizations
from database import delete_expired_messages
from ping import app as ping_app

DAILY_CLEANUP_SECONDS = 24 * 3600

def run_ping():
    from config import PORT
    ping_app.run(host="0.0.0.0", port=PORT)

async def daily_cleanup():
    """Elimina automaticamente ogni giorno le offerte più vecchie di 7 giorni
    (expires_at è impostato a received_at + 7 giorni in save_message)."""
    while True:
        try:
            delete_expired_messages()
            print("🧹 Pulizia automatica: offerte più vecchie di 7 giorni rimosse.")
        except Exception as e:
            print(f"❌ Errore pulizia automatica: {e}")
        await asyncio.sleep(DAILY_CLEANUP_SECONDS)

async def main():
    threading.Thread(target=run_ping, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    register_handlers(app)
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    print("🤖 Hub Offerte avviato!")
    asyncio.create_task(start_reader())
    asyncio.create_task(retry_pending_categorizations())
    asyncio.create_task(daily_cleanup())
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())