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
        raise CategorizationError("Groq client non configurato")

    categories = get_categories()
    tree = build_category_tree(categories)
    category_list = "\n".join(tree)

    prompt = f"""Sei un assistente che categorizza messaggi di offerte hardware/tech.

Messaggio da categorizzare:
{text}

Categorie disponibili (con ID):
{category_list}

**REGOLE FONDAMENTALI (GERARCHIA E SOTTOCATEGORIE):**

1. **Ogni sottocategoria APPARTIENE anche alla sua categoria padre.**
   - Esempio: DDR5 è sottocategoria di RAM → se un prodotto è DDR5, è anche RAM.
   - Esempio: AMD è sottocategoria di CPU → se un prodotto è AMD, è anche CPU.
   - Esempio: AM5 è sottocategoria di Motherboard → se un prodotto è AM5, è anche Motherboard.
   - Questa regola vale per TUTTE le sottocategorie, anche quelle che aggiungerai in futuro.

2. **REGOLE DI ASSEGNAZIONE PER LE SOTTOCATEGORIE:**
   - Se il messaggio menziona una sottocategoria, assegna SIA la sottocategoria che la categoria padre.
   - Esempio: "DDR5 16GB" → **[ID_DDR5, ID_RAM]**
   - Esempio: "AMD Ryzen" → **[ID_AMD, ID_CPU]**
   - Esempio: "AM5" → **[ID_AM5, ID_Motherboard]**
   - Esempio: "RTX 3060" → **[ID_RTX, ID_GPU]**
   - Se il messaggio menziona una categoria che NON ha sottocategorie, assegna SOLO quella categoria.
   - Esempio: "SSD 1TB" → **[ID_SSD]**
   - Esempio: "CPU Intel" → **[ID_CPU]**

3. **CONDIZIONE OBBLIGATORIA PER LE SOTTOCATEGORIE:**
   - Per assegnare una sottocategoria (DDR5, AMD, AM5, RTX, ecc.), il prodotto DEVE appartenere naturalmente alla categoria padre.
   - Esempio: "Lavatrice DDR5" → NON DDR5, NON RAM → **[2]** (Tech Generale)
   - Esempio: "Frigorifero AMD" → NON AMD, NON CPU → **[2]** (Tech Generale)
   - Esempio: "Lavatrice RTX" → NON RTX, NON GPU → **[2]** (Tech Generale)
   - Regola generale: **sottocategoria → deve appartenere alla categoria padre**.
   - Se il prodotto non appartiene alla categoria padre, NON assegnare la sottocategoria.

4. **PRIORITÀ:**
   - Se il messaggio corrisponde a una sottocategoria specifica, assegna SEMPRE anche la categoria padre.
   - Esempio: "RAM DDR5 16GB" → **[ID_DDR5, ID_RAM]** (NON solo DDR5).
   - Esempio: "GPU RTX 3060" → **[ID_RTX, ID_GPU]** (NON solo GPU).

5. **FALLBACK:**
   - Se il messaggio non appartiene a nessuna categoria specifica, usa **[2]** (Tech Generale).

**RISPOSTA:**
Rispondi SOLO con un array JSON di ID. Nient'altro.
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
            messages=[
                {"role": "system", "content": "Sei un assistente che categorizza messaggi di offerte hardware. Segui le regole gerarchiche: sottocategoria → sempre anche categoria padre. Rispondi solo con un array JSON di ID."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            max_tokens=150
        )
        result = response.choices[0].message.content.strip()
        logger.info(f"📥 Risposta grezza: {result!r}")

        if not result:
            raise CategorizationError("Risposta vuota dal modello")

        json_match = re.search(r'\[.*\]', result, re.DOTALL)
        if json_match:
            try:
                ids = json.loads(json_match.group(0))
                parsed = [int(i) for i in ids if isinstance(i, int)]
                if parsed:
                    logger.info(f"✅ Categorie parse: {parsed}")
                    return parsed
            except json.JSONDecodeError:
                pass

        raise CategorizationError(f"Risposta non valida: {result[:200]!r}")

    except Exception as e:
        logger.error(f"❌ Errore Groq: {e}", exc_info=True)
        raise CategorizationError(str(e))