from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

def make_message(name: str, segment: str, city: str) -> str:
    first_name = name.strip() or "Olá"
    if segment == "Drywall / construção a seco":
        return (
            f"Olá, tudo bem? Meu nome é Victor e faço parte da equipe comercial da Construcril. "
            f"Estou entrando em contato porque identificamos a {first_name}, em {city}, como uma empresa "
            f"que pode atuar no segmento de drywall e construção a seco. Trabalhamos com soluções para "
            f"construção civil, incluindo soluções relacionadas a massas e bases para drywall, e gostaria de entender "
            f"se vocês compram materiais dessa categoria e quem é a pessoa responsável pelas compras. "
            f"Posso encaminhar uma apresentação breve do nosso portfólio?"
        )
    return (
        f"Olá, tudo bem? Meu nome é Victor e faço parte da equipe comercial da Construcril. "
        f"Estou entrando em contato porque identificamos a {first_name}, em {city}, como uma empresa "
        f"potencialmente relacionada à impermeabilização. Temos um portfólio de soluções para construção civil, "
        f"incluindo linhas como Elastic, Elastic UV, Flex 2000 e Flex Plus, conforme a aplicação. "
        f"Gostaria de entender quais sistemas ou produtos vocês utilizam e quem é responsável pelas compras. "
        f"Posso encaminhar uma apresentação breve para avaliação?"
    )

def score_business(name: str, tags: dict[str, Any], segment_key: str) -> tuple[int, str]:
    name_n = normalize(name)
    shop = normalize(str(tags.get("shop", "")))
    craft = normalize(str(tags.get("craft", "")))
    office = normalize(str(tags.get("office", "")))
    keywords = {
        "drywall": ["drywall", "dry wall", "gesso", "steel frame", "construcao a seco", "divisoria", "forro", "placa cimenticia"],
        "impermeabilizacao": ["impermeabil", "manta asfaltica", "manta liquida", "vedacao", "infiltracao", "impermeabilizante"],
    }[segment_key]
    hits = [word for word in keywords if word in name_n]
    score = min(70, len(hits) * 25)
    reasons = [f"Nome contém: {', '.join(hits)}"] if hits else []
    if segment_key == "drywall" and any(term in (shop + " " + craft + " " + office) for term in ["building materials", "construction", "plasterer", "drywall"]):
        score += 20
        reasons.append("Categoria comercial compatível")
    if segment_key == "impermeabilizacao" and any(term in (shop + " " + craft + " " + office) for term in ["building materials", "construction", "roofer"]):
        score += 20
        reasons.append("Categoria comercial compatível")
    if tags.get("website") or tags.get("contact:website"):
        score += 5
        reasons.append("Site disponível para verificação")
    if tags.get("phone") or tags.get("contact:phone"):
        score += 5
        reasons.append("Telefone disponível")
    score = min(100, score)
    if not reasons:
        reasons.append("Correspondência ampla; revisar manualmente antes de abordar")
    return score, "; ".join(reasons)


def build_overpass_query(area_relation_id: int, segment_key: str) -> str:
    if segment_key == "drywall":
        name_regex = (
            "drywall|dry wall|gesso|steel frame|"
            "construcao a seco|divisoria|forro|placa cimenticia"
        )
        craft_regex = "plasterer|drywall"
    else:
        name_regex = (
            "impermeabil|manta asfaltica|manta liquida|"
            "vedacao|infiltracao|impermeabilizante"
        )
        craft_regex = "roofer|waterproofing"

    area_id = 3600000000 + int(area_relation_id)

    return f"""[out:json][timeout:25];
area({area_id})->.searchArea;
(
  nwr["name"~"{name_regex}",i](area.searchArea);
  nwr["craft"~"{craft_regex}",i](area.searchArea);
  nwr["office"="construction"](area.searchArea);
);
out center tags 50;"""

