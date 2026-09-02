import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession
from config import API_ID, API_HASH
import qrcode

async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    qr_login = await client.qr_login()

    # Crea e salva il QR come immagine
    img = qrcode.make(qr_login.url)
    img.save("qrcode.png")
    print("\n✅ QR salvato come 'qrcode.png' nella cartella corrente.")
    print("📱 Aprilo con un visualizzatore di immagini e scannerizzalo con l'app Telegram.")
    print("   (Apri Telegram → Impostazioni → Dispositivi → Collega dispositivo)\n")

    print("⏳ In attesa della scansione...")
    await qr_login.wait()
    session_string = client.session.save()
    print("\n" + "=" * 60)
    print("✅ Sessione generata. Copia questa stringa:")
    print(session_string)
    print("=" * 60)
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())