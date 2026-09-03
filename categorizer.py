import json
import re
import time
import logging
from openai import OpenAI
from config import (
    GROQ_API_KEY,
    MISTRAL_API_KEY,
    OPENROUTER_API_KEY
)
from database import get_categories

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------- CONFIGURAZIONE PROVIDER ----------
PROVIDERS = {}

# Stato dei modelli in cooldown (rate limit)
# { "provider/model": timestamp_fine_cooldown }
cooldowns = {}

# 1. Groq (primario)
if GROQ_API_KEY:
    PROVIDERS["groq"] = {
        "client": OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        ),
        "models": [
            "groq/compound",
            "openai/gpt-oss-120b",
            "qwen/qwen3.6-27b",
            "meta-llama/llama-4-scout-17b-16e-instruct",
        ],
    }

# 2. Mistral (fallback)
if MISTRAL_API_KEY:
    PROVIDERS["mistral"] = {
        "client": OpenAI(
            api_key=MISTRAL_API_KEY,
            base_url="https://api.mistral.ai/v1"
        ),
        "models": [
            "mistral-small-latest",
            "mistral-medium-latest",
            "mistral-large-latest",
            "codestral-latest",
        ],
    }

# 3. OpenRouter (terzo fallback)
if OPENROUTER_API_KEY:
    PROVIDERS["openrouter"] = {
        "client": OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1"
        ),
        "models": [
            "openrouter/free",
        ],
    }

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
MIN_INTERVAL = 0.2

def build_prompt(text, categories):
    tree = build_category_tree(categories)
    category_list = "\n".join(tree)
    return f"""
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

def parse_response(result):
    json_match = re.search(r'\[.*\]', result, re.DOTALL)
    if json_match:
        try:
            ids = json.loads(json_match.group(0))
            parsed = [int(i) for i in ids if isinstance(i, int)]
            if parsed:
                return parsed
        except:
            pass
    return None

def call_model(client, model, prompt):
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200
        )
        result = response.choices[0].message.content.strip()
        return result, None
    except Exception as e:
        error_msg = str(e)
        # Estrai tempo di attesa dal messaggio di errore 429
        if "429" in error_msg and "Please try again in" in error_msg:
            import re
            match = re.search(r'Please try again in (\d+)m(\d+\.\d+)s', error_msg)
            if match:
                minutes = int(match.group(1))
                seconds = float(match.group(2))
                wait_seconds = minutes * 60 + seconds + 5  # +5s di margine
                return None, ("rate_limit", wait_seconds)
            else:
                return None, ("rate_limit", 60)
        return None, ("error", error_msg)

def categorize_message(text):
    global _last_request_time
    
    if not PROVIDERS:
        raise CategorizationError("Nessun provider configurato. Verifica le chiavi API nel .env")
    
    # Rate limiting globale (per non sovraccaricare)
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request_time = time.time()

    categories = get_categories()
    prompt = build_prompt(text, categories)
    
    last_error = None
    
    for provider_name, provider in PROVIDERS.items():
        logger.info(f"🔄 Tentativo con provider: {provider_name}")
        
        for model in provider["models"]:
            model_key = f"{provider_name}/{model}"
            
            # Verifica se il modello è in cooldown per rate limit
            if model_key in cooldowns:
                if time.time() < cooldowns[model_key]:
                    remaining = int(cooldowns[model_key] - time.time())
                    logger.info(f"⏳ {model_key} in cooldown per altri {remaining}s, passo al prossimo...")
                    continue
                else:
                    # Cooldown scaduto, rimuovilo
                    del cooldowns[model_key]
            
            try:
                logger.info(f"  📤 Chiamata a {model_key}")
                result, status = call_model(provider["client"], model, prompt)
                
                if status:
                    if status[0] == "rate_limit":
                        wait_seconds = status[1]
                        cooldowns[model_key] = time.time() + wait_seconds
                        logger.warning(f"⏳ Rate limit su {model_key}, in cooldown per {wait_seconds:.0f}s. Passo al prossimo...")
                        continue
                    else:
                        logger.warning(f"⚠️ Errore {model_key}: {status[1][:200]}")
                        last_error = status[1]
                        continue
                
                if result:
                    parsed = parse_response(result)
                    if parsed:
                        logger.info(f"✅ Categorizzato con {model_key}: {parsed}")
                        return parsed
                    else:
                        logger.warning(f"⚠️ Risposta non valida da {model_key}, provo il prossimo...")
                        continue
                        
            except Exception as e:
                logger.warning(f"⚠️ Eccezione {model_key}: {e}")
                last_error = e
                continue
        
        logger.warning(f"❌ Provider {provider_name} fallito completamente, passo al prossimo...")
    
    raise CategorizationError(f"Tutti i provider e modelli hanno fallito. Ultimo errore: {last_error}")