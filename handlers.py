import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from database import (
    get_categories, add_category, delete_category,
    get_channels, add_channel, delete_channel,
    get_messages_recent, get_messages_week,
    get_messages_by_category, get_messages_by_category_week,
    get_category_name, delete_expired_messages, delete_all_messages,
    search_messages, get_favorite_category_ids, add_favorite, remove_favorite
)
from reader import restart_reader
from categorizer import build_category_tree

MAX_MSG = 4000
OFFERS_PER_PAGE = 5

def esc(t):
    return html.escape(str(t)) if t else ""

def truncate(text, limit=4000):
    return text[:limit-3] + "..." if len(text) > limit else text

def format_offer(m, max_len=1000):
    link = f"https://t.me/{m['channel_username']}/{m['message_id']}"
    text = m['raw_text'] if m.get('raw_text') else ""
    if max_len and len(text) > max_len:
        text = text[:max_len] + "...\n\n(continua nel messaggio originale)"
    timestamp = m['received_at'][:16] if m.get('received_at') else "Data sconosciuta"
    return (
        f"📩 <b>{timestamp}</b> - @{m['channel_username']}\n"
        f"{text}\n\n"
        f"🔗 <a href=\"{link}\">Vedi messaggio originale</a>\n"
        f"——————————————————\n\n"
    )

def main_menu():
    keyboard = [
        [InlineKeyboardButton("📂 Categorie", callback_data="cat_menu")],
        [InlineKeyboardButton("🔥 Offerte", callback_data="offers_menu")],
        [InlineKeyboardButton("📢 Canali", callback_data="channels_menu")],
        [InlineKeyboardButton("⚙️ Impostazioni", callback_data="settings_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ---------- FUNZIONE DI PAGINAZIONE CORRETTA ----------
def build_offers_text(msgs, page, title, context):
    """Costruisce il testo e la tastiera per una pagina di offerte."""
    total = len(msgs)
    start = page * OFFERS_PER_PAGE
    end = min(start + OFFERS_PER_PAGE, total)
    page_msgs = msgs[start:end]
    
    text = f"{title}\n\n"
    if not page_msgs:
        text += "📭 Nessuna offerta in questa pagina."
    else:
        for m in page_msgs:
            text += format_offer(m, max_len=1000)
        total_pages = (total + OFFERS_PER_PAGE - 1) // OFFERS_PER_PAGE
        text += f"\n📄 Pagina {page + 1} di {total_pages} ({total} offerte totali)"
    
    keyboard = []
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Precedente", callback_data=f"offers_page_{page - 1}"))
    if end < total:
        nav_buttons.append(InlineKeyboardButton("▶️ Successiva", callback_data=f"offers_page_{page + 1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # Pulsante per tornare indietro (usa il contesto salvato)
    back_callback = context.user_data.get("offers_back_callback", "offers_menu")
    keyboard.append([InlineKeyboardButton("↩️ Indietro", callback_data=back_callback)])
    
    return text, InlineKeyboardMarkup(keyboard)

# ---------- HANDLER ----------
async def start(update, context):
    await update.message.reply_text(
        "🤖 Hub Offerte\n\n"
        "Raccoglie offerte dai canali e le organizza per categorie.\n"
        "I messaggi originali sono conservati integralmente.\n\n"
        "Usa il menu qui sotto per navigare.",
        reply_markup=main_menu()
    )

async def menu_callback(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🤖 Hub Offerte\n\n"
        "Raccoglie offerte dai canali e le organizza per categorie.",
        reply_markup=main_menu()
    )

# ---------- CATEGORIE ----------
async def cat_menu(update, context):
    query = update.callback_query
    await query.answer()
    cats = get_categories()
    text = "📂 Categorie\n\n"
    if cats:
        for line in build_category_tree(cats):
            text += f"{esc(line)}\n"
    else:
        text += "Nessuna categoria presente.\n"
    keyboard = [
        [InlineKeyboardButton("➕ Aggiungi", callback_data="cat_add")],
        [InlineKeyboardButton("🗑️ Rimuovi", callback_data="cat_del")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu")]
    ]
    await query.edit_message_text(truncate(text), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def cat_add(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["waiting_ch"] = False
    context.user_data["waiting_cat"] = True
    await query.edit_message_text(
        "Inserisci il nome della nuova categoria.\n"
        "Per sottocategoria, usa: Nome|IDpadre\n"
        "Esempio: SSD|1 (sottocategoria di PC Building)\n\n"
        "Invia /cancel per annullare.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Annulla", callback_data="cat_menu")]])
    )

async def cat_add_input(update, context):
    if context.user_data.get("waiting_cat"):
        text = update.message.text.strip()
        parts = text.split("|")
        if len(parts) == 2:
            name, parent = parts[0].strip(), parts[1].strip()
            add_category(name, int(parent) if parent.isdigit() else None)
            await update.message.reply_text(f"✅ Categoria '{name}' aggiunta!")
        else:
            add_category(text)
            await update.message.reply_text(f"✅ Categoria '{text}' aggiunta!")
        context.user_data["waiting_cat"] = False
        return True
    return False

async def cat_del(update, context):
    query = update.callback_query
    await query.answer()
    cats = get_categories()
    keyboard = [[InlineKeyboardButton(f"🗑️ {c['name']}", callback_data=f"cat_del_{c['id']}")] for c in cats]
    keyboard.append([InlineKeyboardButton("↩️ Indietro", callback_data="cat_menu")])
    await query.edit_message_text("Seleziona categoria da rimuovere:", reply_markup=InlineKeyboardMarkup(keyboard))

async def cat_del_confirm(update, context):
    query = update.callback_query
    await query.answer()
    cat_id = int(query.data.split("_")[2])
    delete_category(cat_id)
    await query.edit_message_text("🗑️ Categoria rimossa.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Indietro", callback_data="cat_menu")]]))

# ---------- OFFERTE CON PAGINAZIONE ----------
async def offers_menu(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["offers_back_callback"] = "offers_menu"
    
    cats = get_categories()
    keyboard = []
    for c in cats:
        if not c["parent_id"]:
            keyboard.append([InlineKeyboardButton(f"📂 {c['name']}", callback_data=f"offers_cat_{c['id']}")])
            for sub in cats:
                if sub["parent_id"] == c["id"]:
                    keyboard.append([InlineKeyboardButton(f"　└ {sub['name']}", callback_data=f"offers_cat_{sub['id']}")])

    keyboard.append([InlineKeyboardButton("🆕 Tutte (ultime 24h)", callback_data="offers_24h_all")])
    keyboard.append([InlineKeyboardButton("📆 Tutte (questa settimana)", callback_data="offers_week_all")])
    keyboard.append([InlineKeyboardButton("🏠 Menu", callback_data="menu")])
    
    await query.edit_message_text(
        "🔥 Scegli una categoria o visualizza tutte le offerte:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def show_offers_all(update, context, hours=None, days=None):
    query = update.callback_query
    await query.answer()
    
    if hours:
        msgs = get_messages_recent(hours)
        title = "🆕 Tutte le offerte - Ultime 24h"
    else:
        msgs = get_messages_week()
        title = "📆 Tutte le offerte - Questa settimana"
    
    if not msgs:
        await query.edit_message_text(
            "📭 Nessun messaggio.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Indietro", callback_data="offers_menu")]])
        )
        return
    
    context.user_data["offers_msgs"] = msgs
    context.user_data["offers_page"] = 0
    context.user_data["offers_back_callback"] = "offers_menu"
    context.user_data["offers_type"] = "all"
    
    text, keyboard = build_offers_text(msgs, 0, title, context)
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)

async def offers_cat_show(update, context):
    query = update.callback_query
    await query.answer()
    cat_id = int(query.data.split("_")[2])
    cat_name = get_category_name(cat_id)
    context.user_data["offers_cat_id"] = cat_id
    context.user_data["offers_back_callback"] = f"offers_cat_{cat_id}"
    
    keyboard = [
        [InlineKeyboardButton("🆕 Ultime 24h", callback_data=f"offers_cat_{cat_id}_24h")],
        [InlineKeyboardButton("📆 Questa settimana", callback_data=f"offers_cat_{cat_id}_week")],
        [InlineKeyboardButton("↩️ Indietro", callback_data="offers_menu")]
    ]
    
    await query.edit_message_text(
        f"📂 {cat_name}\n\nScegli il periodo:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def offers_cat_period(update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    cat_id = int(parts[2])
    period = parts[3]
    cat_name = get_category_name(cat_id)
    
    if period == "24h":
        msgs = get_messages_by_category(cat_id, hours=24)
        title = f"🆕 {cat_name} - Ultime 24h"
    else:
        msgs = get_messages_by_category_week(cat_id)
        title = f"📆 {cat_name} - Questa settimana"
    
    if not msgs:
        await query.edit_message_text(
            f"📭 Nessun messaggio in {cat_name}.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Indietro", callback_data=f"offers_cat_{cat_id}")]])
        )
        return
    
    context.user_data["offers_msgs"] = msgs
    context.user_data["offers_page"] = 0
    context.user_data["offers_back_callback"] = f"offers_cat_{cat_id}"
    context.user_data["offers_type"] = f"cat_{cat_id}_{period}"
    
    text, keyboard = build_offers_text(msgs, 0, title, context)
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)

async def offers_page_navigate(update, context):
    query = update.callback_query
    await query.answer()
    
    page = int(query.data.split("_")[2])
    msgs = context.user_data.get("offers_msgs", [])
    
    if not msgs:
        await query.edit_message_text("❌ Nessuna offerta disponibile.")
        return
    
    title = "📄 Offerte"
    if context.user_data.get("offers_type", "").startswith("cat_"):
        cat_id = context.user_data.get("offers_cat_id")
        cat_name = get_category_name(cat_id) if cat_id else "Categoria"
        period = context.user_data.get("offers_type", "").split("_")[-1]
        title = f"📂 {cat_name} - {'Ultime 24h' if period == '24h' else 'Questa settimana'}"
    elif context.user_data.get("offers_type") == "all":
        title = "📆 Tutte le offerte"
    elif context.user_data.get("offers_type") == "search":
        title = f"🔍 {context.user_data.get('search_keyword', 'Risultati')}"
    
    text, keyboard = build_offers_text(msgs, page, title, context)
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)

# ---------- CANALI ----------
async def channels_menu(update, context):
    query = update.callback_query
    await query.answer()
    channels = get_channels()
    text = "📢 Canali monitorati:\n\n"
    if channels:
        for ch in channels:
            text += f"• @{esc(ch['username'])}\n"
    else:
        text += "Nessun canale aggiunto.\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ Aggiungi", callback_data="ch_add")],
        [InlineKeyboardButton("🗑️ Rimuovi", callback_data="ch_del")],
        [InlineKeyboardButton("🔄 Riavvia reader", callback_data="reader_restart")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu")]
    ]
    await query.edit_message_text(truncate(text), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def ch_add(update, context):
    query = update.callback_query
    await query.answer()
    context.user_data["waiting_cat"] = False
    context.user_data["waiting_ch"] = True
    await query.edit_message_text(
        "Inserisci il nome utente del canale (es. offerte_pc):\n\n"
        "Invia /cancel per annullare.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Annulla", callback_data="channels_menu")]])
    )

async def ch_add_input(update, context):
    if context.user_data.get("waiting_ch"):
        username = update.message.text.strip().replace("@", "")
        add_channel(username)
        await update.message.reply_text(
            f"✅ Canale @{username} aggiunto!\n"
            "🔄 Il reader si riavvierà automaticamente tra qualche secondo."
        )
        context.user_data["waiting_ch"] = False
        await restart_reader()
        return True
    return False

async def text_dispatch(update, context):
    if await cat_add_input(update, context):
        return
    if await ch_add_input(update, context):
        return

async def cancel_command(update, context):
    context.user_data["waiting_cat"] = False
    context.user_data["waiting_ch"] = False
    await update.message.reply_text("❌ Operazione annullata.", reply_markup=main_menu())

# ---------- RICERCA ----------
async def search_command(update, context):
    if not context.args:
        await update.message.reply_text("Uso: /cerca <parola chiave>\nEsempio: /cerca ssd")
        return
    keyword = " ".join(context.args)
    msgs = search_messages(keyword)
    
    if not msgs:
        await update.message.reply_text(f"📭 Nessun risultato per '{esc(keyword)}'.")
        return
    
    context.user_data["offers_msgs"] = msgs
    context.user_data["offers_page"] = 0
    context.user_data["offers_back_callback"] = "offers_menu"
    context.user_data["offers_type"] = "search"
    context.user_data["search_keyword"] = keyword
    
    title = f"🔍 Risultati per '{esc(keyword)}'"
    text, keyboard = build_offers_text(msgs, 0, title, context)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard, disable_web_page_preview=True)

async def ch_del(update, context):
    query = update.callback_query
    await query.answer()
    channels = get_channels()
    if not channels:
        await query.edit_message_text("📭 Nessun canale da rimuovere.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Indietro", callback_data="channels_menu")]]))
        return
    keyboard = [[InlineKeyboardButton(f"🗑️ @{c['username']}", callback_data=f"ch_del_{c['username']}")] for c in channels]
    keyboard.append([InlineKeyboardButton("↩️ Indietro", callback_data="channels_menu")])
    await query.edit_message_text("Seleziona canale da rimuovere:", reply_markup=InlineKeyboardMarkup(keyboard))

async def ch_del_confirm(update, context):
    query = update.callback_query
    await query.answer()
    username = query.data[len("ch_del_"):]
    delete_channel(username)
    await query.edit_message_text(f"🗑️ Canale @{username} rimosso.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Indietro", callback_data="channels_menu")]]))

async def reader_restart_callback(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔄 Riavvio del reader in corso...")
    await restart_reader()

# ---------- SETTINGS ----------
async def settings_menu(update, context):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🧹 Pulisci scadute", callback_data="clean")],
        [InlineKeyboardButton("⭐ Categorie preferite", callback_data="fav_menu")],
        [InlineKeyboardButton("🗑️ Elimina TUTTE le offerte", callback_data="wipe_all")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu")]
    ]
    await query.edit_message_text("⚙️ Impostazioni", reply_markup=InlineKeyboardMarkup(keyboard))

async def fav_menu(update, context):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    favs = set(get_favorite_category_ids(chat_id))
    cats = get_categories()
    keyboard = []
    for c in cats:
        mark = "✅" if c["id"] in favs else "▫️"
        indent = "　" if c["parent_id"] else ""
        keyboard.append([InlineKeyboardButton(f"{mark} {indent}{c['name']}", callback_data=f"fav_toggle_{c['id']}")])
    keyboard.append([InlineKeyboardButton("↩️ Indietro", callback_data="settings_menu")])
    await query.edit_message_text(
        "⭐ Categorie preferite\n\n"
        "Riceverai un messaggio istantaneo ogni volta che arriva una nuova "
        "offerta in una categoria selezionata.\n\nTocca per attivare/disattivare:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def fav_toggle(update, context):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    cat_id = int(query.data[len("fav_toggle_"):])
    current = set(get_favorite_category_ids(chat_id))
    if cat_id in current:
        remove_favorite(chat_id, cat_id)
    else:
        add_favorite(chat_id, cat_id)
    await fav_menu(update, context)

async def clean_expired_callback(update, context):
    query = update.callback_query
    await query.answer()
    delete_expired_messages()
    await query.edit_message_text(
        "🧹 Offerte scadute (oltre 7 giorni) rimosse.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Indietro", callback_data="settings_menu")]])
    )

async def wipe_all_confirm_ask(update, context):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("⚠️ Sì, elimina tutto", callback_data="wipe_all_confirm")],
        [InlineKeyboardButton("↩️ Annulla", callback_data="settings_menu")]
    ]
    await query.edit_message_text(
        "⚠️ Questo eliminerà DEFINITIVAMENTE tutte le offerte salvate (comprese quelle non scadute).\n"
        "Sei sicuro?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def wipe_all_confirm(update, context):
    query = update.callback_query
    await query.answer()
    delete_all_messages()
    await query.edit_message_text(
        "🗑️ Tutte le offerte sono state eliminate.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Indietro", callback_data="settings_menu")]])
    )

async def restart_command(update, context):
    await update.message.reply_text("🔄 Riavviando il reader...")
    await restart_reader()

# ---------- REGISTRA HANDLER ----------
def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("restart", restart_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("cerca", search_command))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(cat_menu, pattern="^cat_menu$"))
    app.add_handler(CallbackQueryHandler(cat_add, pattern="^cat_add$"))
    app.add_handler(CallbackQueryHandler(cat_del, pattern="^cat_del$"))
    app.add_handler(CallbackQueryHandler(cat_del_confirm, pattern="^cat_del_\\d+$"))
    app.add_handler(CallbackQueryHandler(offers_menu, pattern="^offers_menu$"))
    app.add_handler(CallbackQueryHandler(lambda u,c: show_offers_all(u,c,hours=24), pattern="^offers_24h_all$"))
    app.add_handler(CallbackQueryHandler(lambda u,c: show_offers_all(u,c,days=7), pattern="^offers_week_all$"))
    app.add_handler(CallbackQueryHandler(offers_cat_show, pattern="^offers_cat_\\d+$"))
    app.add_handler(CallbackQueryHandler(offers_cat_period, pattern="^offers_cat_\\d+_(24h|week)$"))
    app.add_handler(CallbackQueryHandler(offers_page_navigate, pattern="^offers_page_\\d+$"))
    app.add_handler(CallbackQueryHandler(channels_menu, pattern="^channels_menu$"))
    app.add_handler(CallbackQueryHandler(ch_add, pattern="^ch_add$"))
    app.add_handler(CallbackQueryHandler(ch_del, pattern="^ch_del$"))
    app.add_handler(CallbackQueryHandler(ch_del_confirm, pattern="^ch_del_.+$"))
    app.add_handler(CallbackQueryHandler(reader_restart_callback, pattern="^reader_restart$"))
    app.add_handler(CallbackQueryHandler(settings_menu, pattern="^settings_menu$"))
    app.add_handler(CallbackQueryHandler(clean_expired_callback, pattern="^clean$"))
    app.add_handler(CallbackQueryHandler(wipe_all_confirm_ask, pattern="^wipe_all$"))
    app.add_handler(CallbackQueryHandler(wipe_all_confirm, pattern="^wipe_all_confirm$"))
    app.add_handler(CallbackQueryHandler(fav_menu, pattern="^fav_menu$"))
    app.add_handler(CallbackQueryHandler(fav_toggle, pattern="^fav_toggle_\\d+$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_dispatch))