from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations
from typing import Iterable

from app.matching.normalize import extract_volume_ml
from app.matching.identity import extract_abv_pct, extract_vintage_year


_PHRASE_ALIASES = {
    "etiqueta negra": "black label",
    "etiqueta roja": "red label",
    "etiqueta azul": "blue label",
    "etiqueta dorada": "gold label",
    "etiqueta oro": "gold label",
    "etiqueta verde": "green label",
    "johnny walker": "johnnie walker",
    "jhonnie walker": "johnnie walker",
    "jack daniel s": "jack daniels",
    "jack daniel": "jack daniels",
    "j b": "jb",
    "six pack": "pack 6",
}

_TOKEN_ALIASES = {
    "whiskey": "whisky",
    "anejo": "aneho",
    "aňejo": "aneho",
    "litre": "litro",
    "lts": "litro",
    "lt": "litro",
}

_GENERIC_WORDS = {
    "whisky",
    "whiskey",
    "vino",
    "vinos",
    "ron",
    "rones",
    "gin",
    "vodka",
    "tequila",
    "pisco",
    "licor",
    "licores",
    "espumante",
    "espumantes",
    "cerveza",
    "cervezas",
    "botella",
    "botellas",
    "lata",
    "latas",
    "unidad",
    "unidades",
    "un",
    "u",
    "oferta",
    "ofertas",
    "promo",
    "promocion",
    "descuento",
    "precio",
    "especial",
    "formato",
    "contenido",
    "alcohol",
    "grado",
    "grados",
    "ml",
    "cc",
    "cl",
    "litro",
    "litros",
    "pack",
    "caja",
    "case",
    "estuche",
}

_PACK_WORD_RE = re.compile(r"\b(pack|caja|case|sixpack|estuche|combo)\b", re.IGNORECASE)
_BUNDLE_MARKER_RE = re.compile(
    r"\b(regalo|incluye|copa|vaso|jigger|miniatura|personalizad[oa]s?|grabada?|grabado)\b"
    r"|(?:\+|\by\b)\s*\d*\s*(?:agua|bebida|tonica|tónica|red bull|copa|vaso)",
    re.IGNORECASE,
)
_PACK_COUNT_PATTERNS = (
    re.compile(r"\b(?:pack|caja|case|combo)\s*(?:de\s*)?(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})\s*(?:unidades|unidad|uds|ud|u)\b", re.IGNORECASE),
    re.compile(
        r"\b(\d{1,2})\s*[x×]\s*\d+(?:[.,]\d+)?\s*(?:ml|cc|cl|l|lt|lts)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(\d{1,2})\s+botellas?\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})\s+latas?\b", re.IGNORECASE),
)

# Muchas tiendas chilenas expresan multipacks como ``X6 750 ml`` o
# ``750 cc x6`` sin escribir "pack". La expresión histórica sólo reconocía
# ``6x750 ml`` y por eso esos productos podían entrar al Matching 2.0 como
# botellas individuales. Estos patrones se evalúan de forma conservadora: el
# multiplicador desnudo requiere además un volumen verificable en el título.
_PACK_SUFFIX_MULTIPLIER_PATTERNS = (
    re.compile(r"\b[x×]\s*(\d{1,2})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})\s*[x×](?=\s|$)", re.IGNORECASE),
)
_COMMON_MULTIPACK_COUNTS = {2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 20, 24, 30, 36, 48}

_VOLUME_REMOVE_RE = re.compile(
    r"(?<!\d)\d+(?:[.,]\d+)?\s*(?:ml|cc|cl|l|lt|lts|litro|litros)\b",
    re.IGNORECASE,
)

_KNOWN_BRANDS = tuple(
    sorted(
        {
            "johnnie walker",
            "jack daniels",
            "chivas regal",
            "ballantines",
            "buchanans",
            "glenfiddich",
            "glenlivet",
            "jameson",
            "jim beam",
            "wild turkey",
            "makers mark",
            "absolut",
            "smirnoff",
            "grey goose",
            "bombay sapphire",
            "tanqueray",
            "beefeater",
            "hendricks",
            "bacardi",
            "havana club",
            "captain morgan",
            "jose cuervo",
            "don julio",
            "alto del carmen",
            "pisco mistral",
            "mistral",
            "capel",
            "el gobernador",
            "santa rita",
            "concha y toro",
            "casillero del diablo",
            "marques de casa concha",
            "miguel torres",
            "veuve clicquot",
            "moet chandon",
        },
        key=lambda value: (-len(value.split()), value),
    )
)

_VARIANT_MARKERS = {
    "black",
    "red",
    "blue",
    "gold",
    "green",
    "double",
    "honey",
    "apple",
    "fire",
    "cinnamon",
    "orange",
    "cherry",
    "blanco",
    "silver",
    "reposado",
    "aneho",
    "reserva",
    "gran",
    "premium",
    "select",
    "especial",
    "original",
    "zero",
    "sin",
}


@dataclass(frozen=True)
class ProductSignature:
    source_name: str
    normalized_text: str
    core_tokens: tuple[str, ...]
    core_key: str
    volume_ml: int | None
    pack_count: int | None
    is_pack: bool
    brand: str | None
    variant_tokens: frozenset[str]
    abv_pct: float | None
    vintage_year: int | None

    @property
    def comparison_key(self) -> str:
        volume = str(self.volume_ml) if self.volume_ml is not None else "unknown"
        return f"{self.core_key}|{volume}"


@dataclass(frozen=True)
class PairScore:
    accepted: bool
    confidence: float
    method: str
    reason: str


@dataclass(frozen=True)
class MatchCandidate:
    left_id: int
    right_id: int
    confidence: float
    method: str


@dataclass(frozen=True)
class ReviewCandidate:
    left_id: int
    right_id: int
    confidence: float
    method: str
    reason: str


@dataclass(frozen=True)
class MatchingPlan:
    candidates: tuple[MatchCandidate, ...]
    review_candidates: tuple[ReviewCandidate, ...]
    total_products: int
    eligible_products: int
    skipped_packs: int
    skipped_unknown_volume: int
    candidate_pairs: int
    ambiguous_products: int


def _ascii_lower(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    plain = "".join(char for char in normalized if not unicodedata.combining(char))
    return plain.casefold()


def _apply_aliases(text: str) -> str:
    normalized = f" {_ascii_lower(text)} "
    normalized = normalized.replace("&", " and ").replace("'", " ").replace("’", " ")
    normalized = re.sub(r"\bjw\b", " johnnie walker ", normalized)
    for source, target in _PHRASE_ALIASES.items():
        normalized = re.sub(rf"\b{re.escape(source)}\b", target, normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def extract_pack_count(text: str) -> int | None:
    normalized = _apply_aliases(text)
    for pattern in _PACK_COUNT_PATTERNS:
        match = pattern.search(normalized)
        if match is None:
            continue
        count = int(match.group(1))
        if 2 <= count <= 48:
            return count

    # Formatos reales observados en producción:
    #   "Casas Patronales ... X6 750 ml"
    #   "Cocotel ... X6 1000 ml"
    #   "Vodka ... 700cc x6"
    # Un token Xn aislado sólo se considera multipack si el nombre también
    # contiene un volumen de botella/lata, reduciendo falsos positivos con
    # nombres de ediciones o modelos que pudieran contener una X.
    if extract_volume_ml(normalized) is not None:
        for pattern in _PACK_SUFFIX_MULTIPLIER_PATTERNS:
            match = pattern.search(normalized)
            if match is None:
                continue
            count = int(match.group(1))
            if count in _COMMON_MULTIPACK_COUNTS:
                return count

    if _PACK_WORD_RE.search(normalized) or _BUNDLE_MARKER_RE.search(normalized):
        return 2
    return None


def _infer_brand(tokens: tuple[str, ...], text: str) -> str | None:
    padded = f" {text} "
    for brand in _KNOWN_BRANDS:
        if f" {brand} " in padded:
            return brand
    if not tokens:
        return None
    if len(tokens) >= 2 and tokens[1] not in _VARIANT_MARKERS and not tokens[1].isdigit():
        return " ".join(tokens[:2])
    return tokens[0]


def build_product_signature(name: str) -> ProductSignature:
    normalized = _apply_aliases(name)
    volume_ml = extract_volume_ml(normalized)
    pack_count = extract_pack_count(normalized)
    is_pack = pack_count is not None or bool(
        _PACK_WORD_RE.search(normalized) or _BUNDLE_MARKER_RE.search(normalized)
    )

    cleaned = re.sub(r"\$\s*[\d.]+", " ", normalized)
    cleaned = re.sub(r"-?\d+(?:[.,]\d+)?\s*%", " ", cleaned)
    cleaned = _VOLUME_REMOVE_RE.sub(" ", cleaned)
    for pattern in _PACK_COUNT_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)

    raw_tokens = [token for token in cleaned.split() if token]
    tokens: list[str] = []
    for token in raw_tokens:
        token = _TOKEN_ALIASES.get(token, token)
        if token in _GENERIC_WORDS:
            continue
        if token == "and":
            continue
        tokens.append(token)

    core_tokens = tuple(tokens)
    core_key = " ".join(sorted(core_tokens))
    variant_tokens = frozenset(
        token
        for token in core_tokens
        if token in _VARIANT_MARKERS or token.isdigit()
    )
    brand = _infer_brand(core_tokens, " ".join(core_tokens))
    return ProductSignature(
        source_name=name,
        normalized_text=normalized,
        core_tokens=core_tokens,
        core_key=core_key,
        volume_ml=volume_ml,
        pack_count=pack_count,
        is_pack=is_pack,
        brand=brand,
        variant_tokens=variant_tokens,
        abv_pct=extract_abv_pct(name),
        vintage_year=extract_vintage_year(name),
    )


def compare_signatures(
    left: ProductSignature,
    right: ProductSignature,
    *,
    minimum_confidence: float = 0.86,
) -> PairScore:
    if left.is_pack or right.is_pack:
        return PairScore(False, 0.0, "excluded_pack", "packs no se comparan automáticamente")
    if left.volume_ml is None or right.volume_ml is None:
        return PairScore(False, 0.0, "unknown_volume", "volumen no verificable")
    if left.volume_ml != right.volume_ml:
        return PairScore(False, 0.0, "volume_conflict", "volúmenes distintos")
    if left.vintage_year is not None and right.vintage_year is not None and left.vintage_year != right.vintage_year:
        return PairScore(False, 0.0, "vintage_conflict", "añadas distintas")
    if left.abv_pct is not None and right.abv_pct is not None and abs(left.abv_pct - right.abv_pct) > 1.5:
        return PairScore(False, 0.0, "abv_conflict", "graduación alcohólica incompatible")
    if not left.core_tokens or not right.core_tokens:
        return PairScore(False, 0.0, "empty_signature", "nombre insuficiente")
    if left.brand and right.brand and left.brand != right.brand:
        return PairScore(False, 0.0, "brand_conflict", "marcas distintas")
    if (
        left.variant_tokens
        and right.variant_tokens
        and left.variant_tokens != right.variant_tokens
    ):
        return PairScore(False, 0.0, "variant_conflict", "variantes distintas")

    left_set = set(left.core_tokens)
    right_set = set(right.core_tokens)
    intersection = left_set & right_set
    if not intersection:
        return PairScore(False, 0.0, "no_overlap", "sin palabras en común")

    if left.core_key == right.core_key:
        return PairScore(True, 1.0, "alias_exact", "firma normalizada exacta")

    minimum_size = max(1, min(len(left_set), len(right_set)))
    containment = len(intersection) / minimum_size
    union = left_set | right_set
    jaccard = len(intersection) / max(1, len(union))
    ordered_ratio = SequenceMatcher(
        None,
        " ".join(left.core_tokens),
        " ".join(right.core_tokens),
    ).ratio()
    sorted_ratio = SequenceMatcher(None, left.core_key, right.core_key).ratio()
    sequence = max(ordered_ratio, sorted_ratio)
    confidence = 0.50 * containment + 0.25 * jaccard + 0.25 * sequence

    if containment == 1.0 and min(len(left_set), len(right_set)) >= 2:
        confidence = max(confidence, 0.92)
    if len(intersection) < 2 and min(len(left_set), len(right_set)) > 1:
        confidence -= 0.10
    if left.vintage_year is not None and left.vintage_year == right.vintage_year:
        confidence += 0.02
    if left.abv_pct is not None and right.abv_pct is not None and abs(left.abv_pct - right.abv_pct) <= 0.2:
        confidence += 0.015
    confidence = max(0.0, min(0.999, confidence))

    accepted = confidence >= minimum_confidence
    return PairScore(
        accepted,
        confidence,
        "fuzzy_brand_variant_volume" if accepted else "below_threshold",
        "marca, variante y volumen compatibles" if accepted else "similitud insuficiente",
    )


def _candidate_pool(
    signatures: dict[int, ProductSignature],
    product_ids: Iterable[int],
) -> dict[tuple[int, str], set[int]]:
    index: dict[tuple[int, str], set[int]] = {}
    for product_id in product_ids:
        signature = signatures[product_id]
        if signature.is_pack or signature.volume_ml is None:
            continue
        for token in set(signature.core_tokens):
            index.setdefault((signature.volume_ml, token), set()).add(product_id)
    return index


def build_matching_plan(
    products: Iterable[object],
    *,
    minimum_confidence: float = 0.86,
) -> MatchingPlan:
    product_list = list(products)
    signatures = {
        int(product.id): build_product_signature(str(product.name)) for product in product_list
    }
    skipped_packs = sum(signature.is_pack for signature in signatures.values())
    skipped_unknown_volume = sum(
        not signature.is_pack and signature.volume_ml is None
        for signature in signatures.values()
    )
    eligible = len(product_list) - skipped_packs - skipped_unknown_volume

    by_store: dict[int, list[int]] = {}
    for product in product_list:
        if product.store_id is None:
            continue
        by_store.setdefault(int(product.store_id), []).append(int(product.id))

    raw_candidates: list[MatchCandidate] = []
    review_raw: list[ReviewCandidate] = []
    checked_pairs = 0
    for left_store, right_store in combinations(sorted(by_store), 2):
        left_ids = by_store[left_store]
        right_ids = by_store[right_store]
        right_index = _candidate_pool(signatures, right_ids)
        for left_id in left_ids:
            left_signature = signatures[left_id]
            if left_signature.is_pack or left_signature.volume_ml is None:
                continue
            possible: set[int] = set()
            for token in set(left_signature.core_tokens):
                possible.update(right_index.get((left_signature.volume_ml, token), set()))
            for right_id in possible:
                checked_pairs += 1
                score = compare_signatures(
                    left_signature,
                    signatures[right_id],
                    minimum_confidence=minimum_confidence,
                )
                if score.accepted:
                    raw_candidates.append(
                        MatchCandidate(
                            left_id=left_id,
                            right_id=right_id,
                            confidence=score.confidence,
                            method=score.method,
                        )
                    )
                elif score.confidence >= max(0.72, minimum_confidence - 0.12):
                    review_raw.append(
                        ReviewCandidate(
                            left_id=left_id, right_id=right_id,
                            confidence=score.confidence, method="near_threshold", reason=score.reason,
                        )
                    )

    # Una publicación puede tener un equivalente válido en cada una de las
    # demás tiendas. La v4.5 elegía un único mejor candidato global, lo que
    # convertía los empates exactos de 3 o más tiendas en una falsa
    # ambigüedad. En v5.0 se elige el mejor candidato por tienda contraparte.
    product_store = {
        int(product.id): int(product.store_id)
        for product in product_list
        if product.store_id is not None
    }
    candidates_by_product_store: dict[tuple[int, int], list[MatchCandidate]] = {}
    for candidate in raw_candidates:
        left_other_store = product_store.get(candidate.right_id)
        right_other_store = product_store.get(candidate.left_id)
        if left_other_store is not None:
            candidates_by_product_store.setdefault(
                (candidate.left_id, left_other_store), []
            ).append(candidate)
        if right_other_store is not None:
            candidates_by_product_store.setdefault(
                (candidate.right_id, right_other_store), []
            ).append(candidate)

    unambiguous_best: dict[tuple[int, int], MatchCandidate] = {}
    ambiguous_product_ids: set[int] = set()
    for key, candidates in candidates_by_product_store.items():
        ordered = sorted(candidates, key=lambda item: item.confidence, reverse=True)
        if len(ordered) > 1 and abs(ordered[0].confidence - ordered[1].confidence) < 0.015:
            ambiguous_product_ids.add(key[0])
            for item in ordered[:2]:
                review_raw.append(
                    ReviewCandidate(
                        left_id=item.left_id, right_id=item.right_id,
                        confidence=item.confidence, method="ambiguous_best",
                        reason="dos candidatos equivalentes dentro de 0.015",
                    )
                )
            continue
        unambiguous_best[key] = ordered[0]

    accepted: list[MatchCandidate] = []
    seen_pairs: set[tuple[int, int]] = set()
    for candidate in raw_candidates:
        pair = tuple(sorted((candidate.left_id, candidate.right_id)))
        if pair in seen_pairs:
            continue
        left_store = product_store.get(candidate.left_id)
        right_store = product_store.get(candidate.right_id)
        if left_store is None or right_store is None:
            continue
        if (
            unambiguous_best.get((candidate.left_id, right_store)) == candidate
            and unambiguous_best.get((candidate.right_id, left_store)) == candidate
        ):
            accepted.append(candidate)
            seen_pairs.add(pair)

    ambiguous_products = len(ambiguous_product_ids)
    reviews_by_pair: dict[tuple[int, int], ReviewCandidate] = {}
    for item in review_raw:
        pair = tuple(sorted((item.left_id, item.right_id)))
        current = reviews_by_pair.get(pair)
        if current is None or item.confidence > current.confidence:
            reviews_by_pair[pair] = ReviewCandidate(
                left_id=pair[0], right_id=pair[1], confidence=item.confidence,
                method=item.method, reason=item.reason,
            )

    return MatchingPlan(
        candidates=tuple(sorted(accepted, key=lambda item: (item.left_id, item.right_id))),
        review_candidates=tuple(sorted(reviews_by_pair.values(), key=lambda item: (-item.confidence, item.left_id, item.right_id))),
        total_products=len(product_list),
        eligible_products=eligible,
        skipped_packs=skipped_packs,
        skipped_unknown_volume=skipped_unknown_volume,
        candidate_pairs=checked_pairs,
        ambiguous_products=ambiguous_products,
    )
