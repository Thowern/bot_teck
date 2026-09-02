"""
Esegui questo script UNA SOLA VOLTA in locale (dove puoi digitare il codice
di verifica Telegram da tastiera) per generare una StringSession.

Uso:
    python generate_session.py

Al termine ti stampa una lunga stringa: copiala e mettila su Render come
variabile d'ambiente TELETHON_SESSION. Da quel momento il reader (reader.py)
userà quella stringa invece di un file su disco, quindi funzionerà anche
su un filesystem effimero come quello di Render.

NON committare mai questa stringa su Git: equivale alle credenziali di
accesso al tuo account Telegram.
"""
from telethon import TelegramClient
from telethon.sessions import StringSession
from config import API_ID, API_HASH, PHONE_NUMBER

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    client.start(phone=PHONE_NUMBER)
    session_string = client.session.save()
    print("\n" + "=" * 60)
    print("✅ Login riuscito. Copia questa stringa:")
    print("=" * 60)
    print(session_string)
    print("=" * 60)
    print("Mettila su Render come variabile d'ambiente: TELETHON_SESSION")
