import json
import re
import time
import logging
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL
from database import get_categories

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

class CategorizationError(Exception):
    pass

# Lista di modelli da provare in sequenza (fallback)
# Ordine: dal più consigliato al meno consigliato
MODEL_FALLBACK = [
    "llama-3.1-8b-instant",              # 1. Più veloce, economico, alto limite
    "groq/compound",                      # 2. Buon equilibrio qualità/prezzo
    "meta-llama/llama-4-scout-17b-16e-instruct",  # 3. Modello recente
    "qwen/qwen3.6-27b",                   # 4. Buona qualità
    "openai/gpt-oss-120b",                # 5. Ultima risorsa (limite più basso)
]

def build_category_tree(categories, parent_id=None, indent=0):
    lines = []
    for cat in categories:
        if cat["parent_id"] == parent_id:
            prefix = "  " * indent + "• "
            lines.append(f"{prefix}{cat['name']} (ID: {cat['id']})")
            lines.extend(build_category_tree(categories, cat["id"], indent + 1))
    return lines

def categorize_message(text):
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

    # Prova ogni modello in sequenza
    last_error = None
    for model in MODEL_FALLBACK:
        try:
            logger.info(f"🔄 Tentativo con modello: {model}")
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=200
            )
            result = response.choices[0].message.content.strip()
            logger.info(f"📥 Risposta da {model}: {result!r}")

            json_match = re.search(r'\[.*\]', result, re.DOTALL)
            if json_match:
                ids = json.loads(json_match.group(0))
                parsed = [int(i) for i in ids if isinstance(i, int)]
                if parsed:
                    logger.info(f"✅ Categorie parse da {model}: {parsed}")
                    return parsed
            # Se arriva qui, la risposta non è un JSON valido
            logger.warning(f"⚠️ Risposta non valida da {model}, provo il prossimo...")
            continue

        except Exception as e:
            error_msg = str(e)
            logger.warning(f"⚠️ Errore con {model}: {error_msg[:200]}")
            last_error = e
            # Se è un errore 429 (rate limit), aspetta un po' prima di passare al prossimo
            if "429" in error_msg and "Please try again in" in error_msg:
                import re
                match = re.search(r'Please try again in (\d+)m(\d+\.\d+)s', error_msg)
                if match:
                    minutes = int(match.group(1))
                    seconds = float(match.group(2))
                    wait_time = min(minutes * 60 + seconds + 5, 60)  # max 60 secondi
                    logger.info(f"⏳ Rate limit su {model}: attendo {wait_time:.0f} secondi...")
                    time.sleep(wait_time)
            continue

    # Se tutti i modelli hanno fallito
    raise CategorizationError(f"Tutti i modelli hanno fallito. Ultimo errore: {last_error}")

# Versione con rate limiting (opzionale)
_last_request_time = 0
MIN_INTERVAL = 0.5

def categorize_message_with_ratelimit(text):
    """Versione con rate limiting integrato."""
    global _last_request_time
    
    # Rate limiting
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request_time = time.time()
    
    return categorize_message(text)