import json
import re
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL
from database import get_categories

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None


class CategorizationError(Exception):
    """Errore tecnico (rate limit, API giù, risposta malformata ecc).
    Chi chiama categorize_message deve mettere il messaggio in coda
    e riprovare più tardi, SENZA assegnare una categoria fallback subito."""
    pass


def build_category_tree(categories, parent_id=None, indent=0):
    """Costruisce una stringa leggibile delle categorie per il prompt"""
    lines = []
    for cat in categories:
        if cat["parent_id"] == parent_id:
            prefix = "  " * indent + "• "
            lines.append(f"{prefix}{cat['name']} (ID: {cat['id']})")
            lines.extend(build_category_tree(categories, cat["id"], indent + 1))
    return lines

def categorize_message(text):
    """Chiama Groq per categorizzare il messaggio.
    Solleva CategorizationError su qualsiasi problema tecnico (rate limit,
    errore di rete, modello non disponibile, risposta non parsabile):
    il chiamante deve rimettere il messaggio in coda, NON assegnare un
    fallback silenzioso."""
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

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200
        )
        result = response.choices[0].message.content.strip()
        json_match = re.search(r'\[.*\]', result, re.DOTALL)
        if json_match:
            ids = json.loads(json_match.group(0))
            parsed = [int(i) for i in ids if isinstance(i, int)]
            if parsed:
                return parsed
        # Risposta vuota o non parsabile: è un fallimento tecnico, non un
        # "nessuna categoria adatta" (il modello DEVE sempre restituirne una).
        raise CategorizationError(f"Risposta non valida dal modello: {result[:200]!r}")
    except CategorizationError:
        raise
    except Exception as e:
        # Qui finiscono rate limit, errori di rete, modello dismesso, ecc.
        raise CategorizationError(str(e))