import json
import re
import logging
import time
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL
from database import get_categories

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

class CategorizationError(Exception):
    pass

def build_category_tree(categories, parent_id=None, indent=0):
    lines = []
    for cat in categories:
        if cat["parent_id"] == parent_id:
            prefix = "  " * indent + "• "
            lines.append(f"{prefix}{cat['name']} (ID: {cat['id']})")
            lines.extend(build_category_tree(categories, cat["id"], indent + 1))
    return lines

_last_request_time = 0
MIN_INTERVAL = 0.5

def categorize_message(text):
    global _last_request_time
    if not client:
        raise CategorizationError("Groq client non configurato (GROQ_API_KEY mancante)")

    categories = get_categories()
    tree = build_category_tree(categories)
    category_list = "\n".join(tree)

    prompt = f"""
Sei un assistente che categorizza messaggi di offerte.

Messaggio:
{text}

Categorie disponibili:
{category_list}

Regole:
- Assegna ALMENO UNA categoria al messaggio.
- Se il messaggio contiene più offerte, assegna TUTTE le categorie rilevanti.
- Se non appartiene a nessuna categoria, assegna la categoria generica "Tech Generale" (ID: 2).
- Restituisci SOLO un array JSON di ID.

Esempio: [1, 3, 5]

Ora, rispondi con il JSON:
"""

    # Rate limiting
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request_time = time.time()

    logger.info(f"📤 Prompt inviato a Groq (modello: {GROQ_MODEL})")
    logger.info(f"📝 Messaggio: {text[:200]}...")

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200
        )
        result = response.choices[0].message.content.strip()
        logger.info(f"📥 Risposta grezza: {result!r}")

        if not result:
            raise CategorizationError("Risposta vuota dal modello")

        json_match = re.search(r'\[.*\]', result, re.DOTALL)
        if json_match:
            ids = json.loads(json_match.group(0))
            parsed = [int(i) for i in ids if isinstance(i, int)]
            if parsed:
                logger.info(f"✅ Categorie parse: {parsed}")
                return parsed

        raise CategorizationError(f"Risposta non valida: {result[:200]!r}")

    except CategorizationError:
        raise
    except Exception as e:
        logger.error(f"❌ Errore durante chiamata Groq: {e}", exc_info=True)
        raise CategorizationError(str(e))