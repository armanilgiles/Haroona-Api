from __future__ import annotations

"""Generate Haroona's auditable fashion-scoring ontology.

The generated JSON is committed and used at runtime.  This script exists so
future vocabulary changes remain reviewable instead of becoming hand-edited,
unstructured keyword lists.
"""

from collections import Counter
from datetime import date
import json
from pathlib import Path
import re


OUTPUT_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "curation"
    / "data"
    / "fashion_scoring_ontology_v1.json"
)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


# Forty groups x ten concepts = 400 canonical concepts.  Group traits are the
# semantic bridge between product language and destination profiles.
CONCEPT_GROUPS: list[dict[str, object]] = [
    {
        "category": "garment_type",
        "traits": ["heritage", "preppy", "tailoring", "structured", "smart_casual", "daywear", "layerable"],
        "items": "trench coat|pea coat|blazer dress|shirt dress|polo dress|rugby dress|tailored trousers|pencil skirt|sheath dress|waistcoat",
    },
    {
        "category": "garment_type",
        "traits": ["romantic", "feminine", "cottagecore", "daywear", "flowing", "countryside"],
        "items": "tea dress|wrap dress|puff sleeve dress|prairie dress|smocked dress|tiered dress|cottagecore dress|milkmaid dress|babydoll dress|fit and flare dress",
    },
    {
        "category": "garment_type",
        "traits": ["evening", "glamorous", "urban_polish", "occasion", "statement"],
        "items": "slip dress|cowl neck dress|halter dress|column gown|cocktail dress|sequin dress|satin gown|backless dress|bodycon dress|tuxedo dress",
    },
    {
        "category": "garment_type",
        "traits": ["resort", "coastal", "relaxed", "warm_weather", "flowing", "vacation"],
        "items": "maxi dress|kaftan|beach cover up|sarong|crochet dress|linen set|resort shirt|palazzo pants|sundress|cutout dress",
    },
    {
        "category": "garment_type",
        "traits": ["streetwear", "utility", "technical", "experimental", "urban", "functional"],
        "items": "cargo pants|utility jacket|bomber jacket|moto jacket|hoodie dress|track pants|technical shell|denim jumpsuit|boiler suit|parachute pants",
    },
    {
        "category": "garment_type",
        "traits": ["casual", "daywear", "versatile", "relaxed", "everyday"],
        "items": "t shirt dress|sweater dress|knit dress|denim dress|tunic dress|skater dress|cami dress|tank dress|polo shirt|cardigan",
    },
    {
        "category": "garment_type",
        "traits": ["separates", "versatile", "styling_piece", "day_to_night"],
        "items": "silk blouse|peasant blouse|corset top|crop top|halter top|rugby shirt|oxford shirt|camp shirt|bustier|bandeau",
    },
    {
        "category": "garment_type",
        "traits": ["separates", "daywear", "versatile", "movement", "city_walking"],
        "items": "pleated skirt|midi skirt|maxi skirt|mini skirt|wide leg trousers|straight leg jeans|flared jeans|tailored shorts|bermuda shorts|culottes",
    },
    {
        "category": "garment_type",
        "traits": ["outerwear", "layerable", "weather_ready", "city_walking", "structured"],
        "items": "puffer coat|wool coat|raincoat|field jacket|cape coat|shearling jacket|chore jacket|varsity jacket|kimono jacket|duster coat",
    },
    {
        "category": "garment_type",
        "traits": ["accessory", "styling_piece", "city_walking", "day_to_night"],
        "items": "loafers|ballet flats|pumps|stilettos|sneakers|combat boots|sandals|espadrilles|structured handbag|woven tote",
    },
    {
        "category": "silhouette",
        "traits": ["silhouette", "intentional_shape"],
        "items": "a line|empire waist|drop waist|hourglass|column|oversized|relaxed fit|body skimming|boxy|cocoon",
    },
    {
        "category": "silhouette",
        "traits": ["proportion", "skin_exposure"],
        "items": "mini|midi|maxi|cropped|floor length|sleeveless|strapless|open back|cutout|high slit",
    },
    {
        "category": "construction_detail",
        "traits": ["neckline", "face_framing", "design_detail"],
        "items": "polo collar|point collar|peter pan collar|square neck|sweetheart neck|v neck|crew neck|boat neck|halter neck|cowl neck",
    },
    {
        "category": "construction_detail",
        "traits": ["sleeve", "design_detail", "proportion"],
        "items": "puff sleeve|bishop sleeve|bell sleeve|cap sleeve|flutter sleeve|balloon sleeve|raglan sleeve|dolman sleeve|long sleeve|three quarter sleeve",
    },
    {
        "category": "construction_detail",
        "traits": ["intentional_construction", "design_detail"],
        "items": "tailored|deconstructed|reconstructed|asymmetrical|draped|pleated|smocked|shirred|ruched|tiered",
    },
    {
        "category": "construction_detail",
        "traits": ["decorative", "craft", "statement_detail"],
        "items": "ruffles|embroidery|applique|lace trim|fringe|tassels|sequins|beading|bows|rosettes",
    },
    {
        "category": "construction_detail",
        "traits": ["structured", "intentional_construction", "shape_control"],
        "items": "boning|corsetry|shoulder pads|peplum|darts|princess seams|panelled|bias cut|wrap construction|gathered waist",
    },
    {
        "category": "construction_detail",
        "traits": ["functional_detail", "versatile"],
        "items": "button front|zip front|double breasted|single breasted|drawstring|elastic waist|belted|cargo pockets|patch pockets|detachable detail",
    },
    {
        "category": "surface_design",
        "traits": ["graphic", "surface_interest", "statement"],
        "items": "color block|graphic logo|logo print|contrast trim|piping|raw edge|distressed|washed finish|coated finish|quilted",
    },
    {
        "category": "silhouette",
        "traits": ["movement", "volume", "intentional_shape"],
        "items": "flowing|fluid|sculptural volume|oversized volume|full skirt|circle skirt|tapered|flared|wide leg|architectural shape",
    },
    {
        "category": "material",
        "traits": ["natural_fiber", "breathable", "warm_weather", "daywear", "premium_material"],
        "items": "cotton|organic cotton|linen|organic linen|hemp|ramie|bamboo|seersucker|poplin|chambray",
    },
    {
        "category": "material",
        "traits": ["luxury_material", "occasion", "drape", "premium_material"],
        "items": "silk|satin|chiffon|crepe|organza|velvet|lace|brocade|jacquard|taffeta",
    },
    {
        "category": "material",
        "traits": ["cold_weather", "insulating", "layerable", "premium_material"],
        "items": "wool|cashmere|merino|alpaca|mohair|tweed|boucle|felt|shearling|corduroy",
    },
    {
        "category": "material",
        "traits": ["durable", "streetwear", "structured", "urban"],
        "items": "denim|raw denim|selvedge denim|leather|suede|faux leather|canvas|nylon|ripstop|neoprene",
    },
    {
        "category": "material",
        "traits": ["soft_hand", "movement", "everyday"],
        "items": "polyester|acrylic|viscose|rayon|modal|lyocell|jersey|knit|rib knit|mesh",
    },
    {
        "category": "material_property",
        "traits": ["climate_property", "functional"],
        "items": "technical nylon|waterproof fabric|water resistant fabric|breathable fabric|lightweight fabric|heavyweight fabric|insulated fabric|stretch fabric|performance fabric|recycled fabric",
    },
    {
        "category": "pattern",
        "traits": ["pattern", "visual_interest"],
        "items": "floral print|micro floral|botanical print|paisley|polka dot|gingham|plaid|tartan|stripe|pinstripe",
    },
    {
        "category": "pattern",
        "traits": ["pattern", "graphic", "statement"],
        "items": "animal print|leopard print|zebra print|abstract print|geometric print|graphic print|logo motif|novelty print|toile|camouflage",
    },
    {
        "category": "color",
        "traits": ["neutral_color", "versatile", "urban_polish"],
        "items": "black|white|cream|ivory|beige|camel|taupe|gray|navy|brown",
    },
    {
        "category": "color",
        "traits": ["warm_color", "statement_color", "sunlit_palette"],
        "items": "red|burgundy|blood orange|orange|terracotta|rust|yellow|mustard|coral|peach",
    },
    {
        "category": "color",
        "traits": ["cool_color", "fresh_palette"],
        "items": "blue|cobalt|sky blue|teal|turquoise|green|olive|emerald|mint|lavender",
    },
    {
        "category": "color",
        "traits": ["expressive_color", "statement", "playful"],
        "items": "pink|blush|hot pink|purple|lilac|metallic|gold|silver|neon|pastel",
    },
    {
        "category": "aesthetic",
        "traits": ["heritage", "preppy", "structured_casual", "classic"],
        "items": "preppy|ivy style|collegiate|heritage|british heritage|equestrian|nautical|mod|old money|country club",
    },
    {
        "category": "aesthetic",
        "traits": ["romantic", "feminine", "craft", "soft_styling"],
        "items": "romantic|cottagecore|prairie|coquette|balletcore|feminine minimalism|french girl|bohemian|folk|artisanal",
    },
    {
        "category": "aesthetic",
        "traits": ["minimal", "refined", "urban_polish", "timeless"],
        "items": "minimalist|quiet luxury|monochrome|scandi minimal|clean lines|understated|timeless|polished|refined|contemporary classic",
    },
    {
        "category": "aesthetic",
        "traits": ["experimental", "urban", "statement", "subculture"],
        "items": "avant garde|deconstruction|architectural|utilitarian|technical|streetwear|punk|grunge|y2k|futuristic",
    },
    {
        "category": "aesthetic",
        "traits": ["mood", "styling_direction"],
        "items": "resort glam|coastal|tropical|mediterranean|sexy minimalism|playful|maximalist|glamorous|sporty chic|casual chic",
    },
    {
        "category": "occasion",
        "traits": ["occasion", "lifestyle"],
        "items": "brunch|office|commute|market day|sightseeing|garden party|cocktail|dinner|nightlife|black tie",
    },
    {
        "category": "occasion",
        "traits": ["occasion", "lifestyle", "travel"],
        "items": "beach club|poolside|resort dinner|vineyard|wedding guest|festival|gallery opening|date night|weekend casual|active day",
    },
    {
        "category": "material_property",
        "traits": ["climate_property", "practical"],
        "items": "breathable|airy|layerable|rain friendly|humidity friendly|heat friendly|cold weather|wind resistant|packable|wrinkle resistant",
    },
]


MANUAL_ALIASES: dict[str, list[str]] = {
    "polo dress": ["polo shirt dress", "collared polo dress", "tennis dress with collar", "preppy shirt dress", "sport polo dress"],
    "rugby dress": ["rugby shirt dress", "striped rugby dress", "collared sport dress", "heritage rugby dress", "preppy rugby dress"],
    "shirt dress": ["shirtwaist dress", "button down dress", "button front shirt dress", "collared day dress", "tailored shirt dress"],
    "reconstructed": ["reworked", "remade construction", "hybrid construction", "spliced design", "reassembled garment"],
    "deconstructed": ["deconstruction detail", "exposed construction", "unfinished tailoring", "inside out construction", "dismantled silhouette"],
    "color block": ["colour block", "colorblocked", "colourblocked", "contrast panel", "graphic color panel"],
    "preppy": ["prep style", "prep school", "collegiate prep", "ivy inspired", "country club style"],
    "ivy style": ["ivy league", "ivy look", "american collegiate", "campus classic", "east coast prep"],
    "british heritage": ["british inspired", "british style", "uk heritage", "english heritage", "london heritage"],
    "polo collar": ["polo neck collar", "sport collar", "ribbed polo collar", "tennis collar", "rugby collar"],
    "stripe": ["striped", "striping", "horizontal stripe", "vertical stripe", "breton stripe"],
    "graphic logo": ["graphic emblem", "applied logo", "logo graphic", "statement logo", "branded graphic"],
    "open back": ["backless", "low back", "open backed", "exposed back", "cutaway back"],
    "cowl neck": ["draped neckline", "cowl neckline", "soft draped neck", "waterfall neckline", "draped cowl"],
    "halter dress": ["halter neck dress", "halter gown", "tie neck dress", "neck tie dress", "open shoulder halter"],
    "smocked": ["smocking", "elasticated bodice", "stretch shirring", "smocked bodice", "elastic shirred"],
    "shirred": ["shirring", "shirred bodice", "elastic ruching", "gathered elastic", "stretch gathered"],
    "tiered": ["tiered skirt", "layered tiers", "multi tier", "graduated tiers", "tier construction"],
    "puff sleeve": ["puffed sleeve", "puffy sleeve", "gathered sleeve head", "romantic puff sleeve", "voluminous short sleeve"],
    "floral print": ["flower print", "floral pattern", "flower pattern", "printed floral", "allover floral"],
    "linen": ["flax linen", "pure linen", "linen blend", "linen fabric", "made from linen"],
    "cotton": ["pure cotton", "cotton blend", "cotton fabric", "made from cotton", "cotton textile"],
    "viscose": ["viscose rayon", "viscose fabric", "viscose blend", "made from viscose", "soft viscose"],
    "rayon": ["rayon fabric", "rayon blend", "made from rayon", "soft rayon", "woven rayon"],
    "technical": ["techwear", "technical design", "performance utility", "technical styling", "technical fashion"],
    "architectural": ["architectural silhouette", "constructed shape", "geometric structure", "architectonic", "built silhouette"],
    "romantic": ["romantic style", "soft romance", "romantic feminine", "dreamy styling", "romantic aesthetic"],
    "cottagecore": ["cottage style", "country romance", "pastoral fashion", "rural romantic", "cottage aesthetic"],
    "minimalist": ["minimal style", "minimal design", "pared back", "simple refined", "clean minimal"],
    "quiet luxury": ["stealth wealth", "understated luxury", "logo free luxury", "discreet luxury", "elevated essentials"],
    "streetwear": ["street style", "urban streetwear", "street fashion", "city street style", "street inspired"],
    "bohemian": ["boho", "boho chic", "free spirited", "festival boho", "bohemian style"],
    "resort glam": ["resort glamour", "vacation glamour", "luxury resort", "island glam", "holiday glamour"],
    "mediterranean": ["mediterranean style", "grecian summer", "italian summer", "riviera style", "aegean style"],
    "breathable": ["breathable construction", "allows airflow", "air permeable", "ventilated fabric", "breathes well"],
    "humidity friendly": ["humid climate friendly", "humidity suitable", "tropical humidity ready", "moisture comfortable", "humid weather"],
    "layerable": ["easy to layer", "layering friendly", "works with layers", "transitional layering", "layer ready"],
}


# Related traits turn literal product language into fashion meaning.  These are
# deliberately explicit and auditable: recognizing "puff sleeve" should also
# provide evidence for romantic volume, while "open back" can support a warm-
# weather, sexy-minimal resort direction.  They enrich concepts; they do not
# create extra concepts or inflate the required 400/2,000 counts.
RELATED_TRAITS: dict[str, list[str]] = {
    "floral print": ["floral", "romantic", "feminine", "cottagecore", "countryside"],
    "micro floral": ["floral", "romantic", "feminine", "soft_styling"],
    "botanical print": ["floral", "romantic", "countryside", "natural_motif"],
    "puff sleeve": ["romantic", "feminine", "volume", "cottagecore"],
    "bishop sleeve": ["romantic", "feminine", "volume"],
    "flutter sleeve": ["romantic", "feminine", "airy"],
    "cap sleeve": ["romantic", "feminine", "warm_weather"],
    "square neck": ["romantic", "feminine", "cottagecore"],
    "sweetheart neck": ["romantic", "feminine", "glamorous"],
    "smocked": ["romantic", "feminine", "relaxed", "warm_weather"],
    "shirred": ["romantic", "feminine", "relaxed", "soft_styling"],
    "tiered": ["romantic", "feminine", "flowing", "volume"],
    "ruffles": ["romantic", "feminine", "playful", "volume"],
    "empire waist": ["romantic", "feminine", "flowing"],
    "flowing": ["flowing", "airy", "movement", "relaxed"],
    "fluid": ["flowing", "drape", "movement", "refined"],
    "relaxed fit": ["relaxed", "casual", "movement"],
    "open back": ["open", "skin_exposure", "sexy_minimal", "warm_weather", "resort"],
    "cutout": ["open", "skin_exposure", "sexy_minimal", "warm_weather", "statement"],
    "cutout dress": ["sexy_minimal", "warm_weather", "resort", "statement"],
    "halter neck": ["sexy_minimal", "warm_weather", "resort", "evening"],
    "cowl neck": ["sexy_minimal", "drape", "evening", "glamorous", "refined"],
    "halter dress": ["sexy_minimal", "warm_weather", "resort", "evening", "glamorous"],
    "cowl neck dress": ["sexy_minimal", "drape", "evening", "glamorous", "refined"],
    "backless dress": ["sexy_minimal", "warm_weather", "resort", "evening", "glamorous"],
    "slip dress": ["sexy_minimal", "minimal", "drape", "refined", "evening"],
    "satin": ["drape", "glamorous", "evening", "refined"],
    "silk": ["drape", "glamorous", "refined", "timeless"],
    "chiffon": ["airy", "flowing", "romantic", "feminine"],
    "lightweight fabric": ["lightweight", "airy", "warm_weather", "travel_friendly"],
    "breathable fabric": ["breathable", "warm_weather", "practical"],
    "resort dinner": ["resort", "vacation", "evening", "glamorous", "day_to_night"],
    "beach club": ["resort", "coastal", "vacation", "glamorous"],
    "poolside": ["resort", "coastal", "vacation", "warm_weather"],
    "vineyard": ["romantic", "countryside", "outdoor", "day_to_night"],
    "garden party": ["romantic", "feminine", "outdoor", "daywear"],
    "performance fabric": ["sporty", "active", "functional", "warm_weather"],
    "stretch fabric": ["sporty", "active", "movement", "practical"],
    "body skimming": ["bodycon", "sexy_minimal", "glamorous"],
    "mini": ["skin_exposure", "warm_weather", "youthful"],
    "tartan": ["punk", "british_heritage", "heritage", "graphic"],
    "plaid": ["punk", "british_heritage", "heritage", "preppy"],
    "raw edge": ["punk", "deconstructed", "experimental"],
    "distressed": ["punk", "grunge", "streetwear"],
    "wool coat": ["tailoring", "structured", "layerable", "timeless", "urban_polish"],
    "structured handbag": ["refined", "timeless", "urban_polish", "smart_casual"],
    "quiet luxury": ["minimal", "refined", "timeless", "understated"],
    "clean lines": ["minimal", "refined", "timeless", "urban_polish"],
    "column": ["minimal", "refined", "architectural", "urban_polish"],
    "prairie dress": ["prairie", "romantic", "cottagecore", "countryside", "feminine"],
    "polo dress": ["polo", "preppy", "heritage", "smart_casual", "british_heritage"],
    "rugby dress": ["rugby", "preppy", "heritage", "sporty", "british_heritage"],
    "polo collar": ["polo", "preppy", "heritage", "smart_casual"],
    "reconstructed": ["graphic", "intentional_construction", "upcycled_detail"],
    "color block": ["graphic", "playful", "statement", "visual_interest"],
    "denim jumpsuit": ["utility", "streetwear", "relaxed", "active", "casual"],
    "sneakers": ["sporty", "streetwear", "active", "city_walking"],
    "trench coat": ["british_heritage", "tailoring", "structured", "timeless", "refined", "layerable"],
}


def _generic_aliases(label: str, category: str) -> list[str]:
    if category == "garment_type":
        return [f"womens {label}", f"{label} style", f"{label} outfit", f"{label} silhouette", f"{label} design"]
    if category == "material":
        return [f"{label} fabric", f"{label} blend", f"made from {label}", f"{label} textile", f"{label} material"]
    if category == "material_property":
        return [f"{label} fabric", f"{label} construction", f"{label} material", f"{label} design", f"{label} garment"]
    if category == "pattern":
        return [f"{label} pattern", f"{label} print", f"allover {label}", f"printed {label}", f"{label} motif"]
    if category == "color":
        return [f"{label} color", f"{label} colour", f"in {label}", f"{label} tone", f"{label} shade"]
    if category == "aesthetic":
        return [f"{label} style", f"{label} aesthetic", f"{label} inspired", f"{label} look", f"{label} fashion"]
    if category == "occasion":
        return [f"{label} outfit", f"for {label}", f"{label} look", f"{label} dressing", f"{label} ready"]
    return [f"{label} detail", f"{label} design", f"{label} construction", f"{label} silhouette", f"{label} finish"]


def _aliases(label: str, category: str) -> list[str]:
    candidates = [*MANUAL_ALIASES.get(label, []), *_generic_aliases(label, category)]
    normalized_label = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
    result: list[str] = []
    seen: set[str] = {normalized_label}
    for candidate in candidates:
        normalized = re.sub(r"[^a-z0-9]+", " ", candidate.lower()).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(candidate)
        if len(result) == 5:
            break
    if len(result) != 5:
        raise ValueError(f"Could not create five unique aliases for {label!r}")
    return result


DESTINATIONS: dict[str, dict[str, object]] = {
    "london": {
        "display_name": "London",
        "destination_type": "city",
        "climate": "mild-variable",
        "visual_traits": {"british_heritage": 3.0, "heritage": 2.4, "preppy": 2.1, "tailoring": 2.2, "structured": 1.5, "punk": 1.8, "mod": 1.8, "layerable": 1.3, "romantic": 0.8, "graphic": 0.8, "experimental": 1.0, "urban_polish": 1.2, "smart_casual": 0.8, "timeless": 0.8, "refined": 0.7},
        "visual_conflicts": {"tropical": 1.1, "poolside": 1.3, "beach_only": 1.4},
        "lifestyle_traits": {"smart_casual": 2.2, "daywear": 1.8, "layerable": 1.7, "city_walking": 1.5, "office": 1.5, "evening": 1.0, "versatile": 1.2},
    },
    "paris": {
        "display_name": "Paris",
        "destination_type": "city",
        "climate": "mild-variable",
        "visual_traits": {"refined": 2.6, "minimal": 2.1, "urban_polish": 2.2, "timeless": 2.0, "tailoring": 1.8, "romantic": 1.5, "feminine": 1.2, "luxury_material": 1.6, "monochrome": 1.5, "understated": 1.7},
        "visual_conflicts": {"technical": 0.8, "festival": 1.0, "beach_only": 1.2},
        "lifestyle_traits": {"day_to_night": 2.0, "city_walking": 1.5, "office": 1.5, "evening": 1.8, "refined": 1.8, "versatile": 1.2},
    },
    "copenhagen": {
        "display_name": "Copenhagen",
        "destination_type": "city",
        "climate": "mild-variable",
        "visual_traits": {"playful": 2.5, "scandi": 2.8, "minimal": 1.7, "volume": 2.0, "natural_fiber": 1.8, "sustainable": 2.1, "relaxed": 1.6, "craft": 1.5, "expressive_color": 1.4, "preppy": 0.9, "graphic": 1.0, "refined": 1.0, "urban_polish": 0.8, "architectural": 0.8},
        "visual_conflicts": {"black_tie": 0.8, "bodycon": 0.7, "bling": 1.0},
        "lifestyle_traits": {"city_walking": 1.8, "cycling": 1.7, "daywear": 1.8, "relaxed": 1.5, "layerable": 1.4, "versatile": 1.3},
    },
    "new-york": {
        "display_name": "New York City",
        "destination_type": "city",
        "climate": "four-season-humid",
        "visual_traits": {"urban_polish": 2.5, "tailoring": 2.0, "structured": 1.7, "statement": 1.6, "graphic": 1.4, "experimental": 1.5, "streetwear": 1.6, "preppy": 1.4, "heritage": 0.9, "ivy_style": 2.0, "collegiate": 1.8, "evening": 1.8, "minimal": 1.3, "glamorous": 1.4},
        "visual_conflicts": {"beach_only": 1.3, "countryside": 0.8, "tropical": 0.8, "resort": 0.6},
        "lifestyle_traits": {"day_to_night": 2.1, "office": 1.8, "commute": 1.7, "city_walking": 1.5, "evening": 1.9, "smart_casual": 1.6, "versatile": 1.5},
    },
    "los-angeles": {
        "display_name": "Los Angeles",
        "destination_type": "city",
        "climate": "warm-dry",
        "visual_traits": {"relaxed": 2.0, "warm_weather": 1.8, "sexy_minimal": 2.0, "sporty": 1.8, "casual": 1.5, "denim": 1.4, "statement": 1.0, "resort": 1.2, "bodycon": 1.5, "coastal": 1.3, "streetwear": 1.0},
        "visual_conflicts": {"cold_weather": 1.4, "heavy": 1.3, "formal_heritage": 0.7},
        "lifestyle_traits": {"brunch": 1.8, "day_to_night": 1.6, "coastal": 1.5, "active": 1.6, "casual": 1.8, "evening": 1.2, "versatile": 1.2},
    },
    "tokyo": {
        "display_name": "Tokyo",
        "destination_type": "city",
        "climate": "four-season-humid",
        "visual_traits": {"experimental": 2.6, "deconstructed": 2.6, "architectural": 2.4, "technical": 2.4, "streetwear": 2.1, "graphic": 1.9, "statement": 1.4, "layerable": 1.5, "volume": 1.7, "preppy": 1.0, "romantic": 0.8, "feminine": 0.8, "punk": 1.7, "minimal": 1.3},
        "visual_conflicts": {"beach_only": 1.4, "generic_resort": 1.1, "resort": 1.8, "tropical": 2.0, "cottagecore": 2.4, "countryside": 2.0, "prairie": 2.2, "smocked": 1.8, "shirred": 1.5, "tiered": 1.2, "basic": 0.8},
        "lifestyle_traits": {"commute": 1.8, "city_walking": 1.7, "layerable": 1.5, "streetwear": 1.7, "evening": 1.2, "versatile": 1.2},
    },
    "sydney": {
        "display_name": "Sydney",
        "destination_type": "city",
        "climate": "temperate-coastal",
        "visual_traits": {"coastal": 2.5, "warm_weather": 1.7, "relaxed": 1.8, "resort": 1.7, "flowing": 1.5, "natural_fiber": 1.4, "minimal": 1.0, "sporty": 1.2, "romantic": 0.8},
        "visual_conflicts": {"heavy": 1.2, "cold_weather": 1.0, "formal_heritage": 0.6},
        "lifestyle_traits": {"coastal": 2.1, "brunch": 1.6, "day_to_night": 1.5, "active": 1.4, "casual": 1.5, "outdoor": 1.6},
    },
    "miami": {
        "display_name": "Miami",
        "destination_type": "city",
        "climate": "warm-humid",
        "visual_traits": {"glamorous": 2.2, "statement": 2.0, "expressive_color": 1.8, "sexy_minimal": 2.0, "resort": 1.8, "tropical": 1.7, "bodycon": 1.7, "evening": 1.7, "metallic": 1.4},
        "visual_conflicts": {"cold_weather": 1.6, "heavy": 1.5, "understated": 0.5},
        "lifestyle_traits": {"nightlife": 2.1, "beach_club": 2.0, "poolside": 1.9, "resort": 1.7, "evening": 1.7, "brunch": 1.2},
    },
    "provence": {
        "display_name": "Provence",
        "destination_type": "region",
        "climate": "warm-dry",
        "visual_traits": {"romantic": 2.7, "cottagecore": 2.6, "countryside": 2.3, "feminine": 1.8, "floral": 2.0, "craft": 1.5, "natural_fiber": 1.6, "flowing": 1.4, "sunlit_palette": 1.3, "daywear": 1.0},
        "visual_conflicts": {"technical": 1.4, "bodycon": 1.0, "black_tie": 1.0, "streetwear": 0.8},
        "lifestyle_traits": {"market_day": 2.0, "vineyard": 2.0, "garden_party": 1.9, "sightseeing": 1.5, "daywear": 1.7, "outdoor": 1.4},
    },
    "tuscany": {
        "display_name": "Tuscany / Florence",
        "destination_type": "region",
        "climate": "warm-dry",
        "visual_traits": {"romantic": 2.2, "sunlit_palette": 2.0, "warm_color": 1.8, "natural_fiber": 1.6, "flowing": 1.5, "refined": 1.3, "resort": 1.0, "feminine": 1.3, "craft": 1.3, "glamorous": 1.0},
        "visual_conflicts": {"technical": 1.2, "cold_weather": 1.0, "streetwear": 0.6},
        "lifestyle_traits": {"vineyard": 2.2, "dinner": 1.8, "market_day": 1.6, "sightseeing": 1.5, "day_to_night": 1.5, "outdoor": 1.3},
    },
    "greek-islands": {
        "display_name": "Mykonos / Santorini",
        "destination_type": "island-region",
        "climate": "warm-dry",
        "visual_traits": {"resort": 2.7, "mediterranean": 2.6, "coastal": 2.2, "sexy_minimal": 2.1, "flowing": 1.8, "warm_weather": 1.7, "minimal": 1.1, "glamorous": 1.3, "natural_fiber": 1.2},
        "visual_conflicts": {"cold_weather": 1.6, "heavy": 1.5, "technical": 0.8},
        "lifestyle_traits": {"resort_dinner": 2.2, "beach_club": 2.0, "poolside": 1.7, "sightseeing": 1.4, "evening": 1.5, "vacation": 1.8},
    },
    "bali": {
        "display_name": "Bali",
        "destination_type": "island-region",
        "climate": "warm-humid",
        "visual_traits": {"tropical": 2.6, "bohemian": 2.4, "resort": 2.1, "craft": 1.8, "flowing": 1.8, "natural_fiber": 1.6, "warm_weather": 1.7, "relaxed": 1.6, "romantic": 0.8},
        "visual_conflicts": {"cold_weather": 1.7, "heavy": 1.6, "tailoring": 0.8, "formal_heritage": 0.8},
        "lifestyle_traits": {"resort": 2.0, "poolside": 1.6, "market_day": 1.5, "sightseeing": 1.4, "relaxed": 1.7, "vacation": 1.8},
    },
}


BRANDS: list[dict[str, object]] = [
    {"key": "burberry", "aliases": ["burberry london"], "origin": "london", "strength": 1.0, "affinities": {"new-york": 0.45, "tokyo": 0.4, "paris": 0.3}},
    {"key": "nobodys-child", "aliases": ["nobody's child", "nobodys child"], "origin": "london", "strength": 0.8, "affinities": {"provence": 0.4, "paris": 0.35, "copenhagen": 0.3}},
    {"key": "ganni", "aliases": [], "origin": "copenhagen", "strength": 1.0, "affinities": {"london": 0.35, "new-york": 0.3, "tokyo": 0.25}},
    {"key": "cecilie-bahnsen", "aliases": ["cecilie bahnsen"], "origin": "copenhagen", "strength": 1.0, "affinities": {"provence": 0.35, "tokyo": 0.3, "london": 0.25}},
    {"key": "stine-goya", "aliases": ["stine goya"], "origin": "copenhagen", "strength": 0.9, "affinities": {"london": 0.3, "new-york": 0.25}},
    {"key": "beams", "aliases": ["beams japan"], "origin": "tokyo", "strength": 1.0, "affinities": {"new-york": 0.35, "london": 0.25, "copenhagen": 0.25}},
    {"key": "comme-des-garcons", "aliases": ["comme des garcons", "cdg"], "origin": "tokyo", "strength": 1.0, "affinities": {"new-york": 0.4, "paris": 0.35, "london": 0.3}},
    {"key": "issey-miyake", "aliases": ["issey miyake"], "origin": "tokyo", "strength": 1.0, "affinities": {"paris": 0.35, "new-york": 0.35}},
    {"key": "yohji-yamamoto", "aliases": ["yohji yamamoto"], "origin": "tokyo", "strength": 1.0, "affinities": {"paris": 0.35, "new-york": 0.35}},
    {"key": "uniqlo", "aliases": [], "origin": "tokyo", "strength": 0.65, "affinities": {"new-york": 0.25, "london": 0.25, "copenhagen": 0.25}},
    {"key": "apc", "aliases": ["a.p.c.", "a p c"], "origin": "paris", "strength": 0.9, "affinities": {"new-york": 0.35, "london": 0.3, "copenhagen": 0.25}},
    {"key": "sezane", "aliases": ["sézane"], "origin": "paris", "strength": 0.9, "affinities": {"provence": 0.4, "london": 0.25, "new-york": 0.25}},
    {"key": "chanel", "aliases": [], "origin": "paris", "strength": 1.0, "affinities": {"new-york": 0.4, "london": 0.35, "tokyo": 0.3}},
    {"key": "dior", "aliases": ["christian dior"], "origin": "paris", "strength": 1.0, "affinities": {"new-york": 0.4, "london": 0.35, "tokyo": 0.3}},
    {"key": "saint-laurent", "aliases": ["saint laurent", "ysl"], "origin": "paris", "strength": 1.0, "affinities": {"new-york": 0.45, "london": 0.35, "miami": 0.25}},
    {"key": "reformation", "aliases": [], "origin": "los-angeles", "strength": 0.9, "affinities": {"provence": 0.4, "new-york": 0.35, "sydney": 0.3}},
    {"key": "staud", "aliases": [], "origin": "los-angeles", "strength": 0.9, "affinities": {"miami": 0.35, "new-york": 0.3, "sydney": 0.25}},
    {"key": "kate-spade", "aliases": ["kate spade", "kate spade new york"], "origin": "new-york", "strength": 0.85, "affinities": {"london": 0.25, "paris": 0.2}},
    {"key": "ralph-lauren", "aliases": ["ralph lauren", "polo ralph lauren"], "origin": "new-york", "strength": 1.0, "affinities": {"london": 0.4, "paris": 0.25, "tokyo": 0.25}},
    {"key": "diane-von-furstenberg", "aliases": ["diane von furstenberg", "dvf"], "origin": "new-york", "strength": 0.95, "affinities": {"paris": 0.35, "london": 0.3, "miami": 0.25}},
    {"key": "khaite", "aliases": [], "origin": "new-york", "strength": 0.9, "affinities": {"paris": 0.35, "london": 0.3}},
    {"key": "coach", "aliases": ["coach new york"], "origin": "new-york", "strength": 0.85, "affinities": {"london": 0.3, "tokyo": 0.25}},
    {"key": "michael-kors", "aliases": ["michael kors"], "origin": "new-york", "strength": 0.85, "affinities": {"miami": 0.3, "london": 0.25}},
    {"key": "gucci", "aliases": [], "origin": "tuscany", "strength": 1.0, "affinities": {"paris": 0.4, "new-york": 0.4, "london": 0.35, "tokyo": 0.35}},
    {"key": "ferragamo", "aliases": ["salvatore ferragamo"], "origin": "tuscany", "strength": 1.0, "affinities": {"paris": 0.35, "new-york": 0.3, "london": 0.25}},
    {"key": "zimmermann", "aliases": [], "origin": "sydney", "strength": 1.0, "affinities": {"greek-islands": 0.45, "provence": 0.4, "miami": 0.3}},
    {"key": "aje", "aliases": ["aje athletica"], "origin": "sydney", "strength": 0.9, "affinities": {"greek-islands": 0.35, "los-angeles": 0.3}},
    {"key": "camilla", "aliases": ["camilla with love"], "origin": "sydney", "strength": 0.85, "affinities": {"bali": 0.4, "miami": 0.35, "greek-islands": 0.3}},
    {"key": "jacquemus", "aliases": [], "origin": "provence", "strength": 0.9, "affinities": {"paris": 0.45, "greek-islands": 0.35, "miami": 0.25}},
    {"key": "farm-rio", "aliases": ["farm rio"], "origin": None, "strength": 0.0, "affinities": {"miami": 0.5, "bali": 0.45, "sydney": 0.3}},
]


CALIBRATION_ARCHETYPES: list[dict[str, object]] = [
    {"name": "romantic-floral-midi", "titles": ["Avery", "Alice", "Garden", "Meadow"], "description": "floral print puff sleeve square neck shirred bodice tiered lightweight viscose midi dress romantic garden party", "brand": "Nobody's Child", "expected": {"provence": [84, 95], "tuscany": [80, 93], "tokyo": [48, 68]}},
    {"name": "orange-cutout-midi", "titles": ["Willow", "Sienna", "Ember", "Sol"], "description": "blood orange cap sleeve empire waist cutout open back relaxed lightweight viscose midi dress for vineyard dinner", "brand": "Nobody's Child", "expected": {"tuscany": [84, 95], "greek-islands": [80, 92], "london": [62, 78]}},
    {"name": "black-cowl-halter", "titles": ["Dolly", "Noir", "Marina", "Selene"], "description": "black cowl neck halter dress open back fluid lightweight satin silhouette for resort dinner and evening", "brand": "Nobody's Child", "expected": {"greek-islands": [85, 96], "sydney": [78, 90], "tokyo": [58, 76]}},
    {"name": "smocked-rayon-maxi", "titles": ["Island", "Breeze", "Palm", "Lagoon"], "description": "printed rayon smocked bodice elastic waist flowing tiered maxi dress relaxed tropical resort day", "brand": None, "expected": {"bali": [82, 94], "greek-islands": [72, 88], "tokyo": [48, 67]}},
    {"name": "reconstructed-polo-dress", "titles": ["Burberry Stripe", "Heritage Block", "Reworked Rugby", "Graphic Polo"], "description": "striped cotton reconstructed polo shirt dress color block polo collar mid sleeves graphic logo inspired by british heritage for smart casual city day", "brand": "Burberry", "expected": {"london": [84, 93], "new-york": [75, 86], "tokyo": [69, 82]}},
    {"name": "tailored-trench", "titles": ["Kensington", "Chelsea", "City", "Heritage"], "description": "tailored cotton trench coat double breasted belted structured layerable british heritage outerwear for commute", "brand": "Burberry", "expected": {"london": [88, 98], "paris": [76, 89], "new-york": [74, 88]}},
    {"name": "black-silk-slip", "titles": ["Left Bank", "Soho", "Midnight", "Line"], "description": "black silk slip dress bias cut minimalist refined fluid midi silhouette for dinner and gallery opening", "brand": "A.P.C.", "expected": {"paris": [84, 95], "new-york": [78, 90], "london": [72, 86]}},
    {"name": "playful-organic-volume", "titles": ["Cloud", "Orbit", "Petal", "Bubble"], "description": "organic cotton color block oversized sculptural volume dress playful sustainable scandi style for market day", "brand": "Ganni", "expected": {"copenhagen": [86, 96], "tokyo": [73, 88], "london": [70, 84]}},
    {"name": "technical-deconstructed-jacket", "titles": ["Modular", "Vector", "Assembly", "Shift"], "description": "black technical nylon deconstructed asymmetrical utility jacket architectural modular cargo pockets streetwear for commute", "brand": "Comme des Garcons", "expected": {"tokyo": [87, 98], "new-york": [77, 90], "paris": [66, 82]}},
    {"name": "active-cutout-mini", "titles": ["Motion", "Pulse", "Studio", "Sprint"], "description": "stretch performance fabric body skimming cutout mini dress sporty chic active day to brunch warm weather", "brand": None, "expected": {"los-angeles": [80, 92], "miami": [76, 90], "london": [55, 73]}},
    {"name": "boho-crochet-resort", "titles": ["Nomad", "Temple", "Sunset", "Cove"], "description": "airy crochet maxi dress artisanal bohemian fringe relaxed tropical resort style for poolside", "brand": None, "expected": {"bali": [84, 95], "greek-islands": [78, 90], "new-york": [50, 69]}},
    {"name": "linen-resort-set", "titles": ["Aegean", "Riviera", "Coast", "Port"], "description": "white linen set relaxed resort shirt and palazzo pants breathable airy mediterranean vacation sightseeing", "brand": None, "expected": {"greek-islands": [86, 96], "sydney": [78, 91], "bali": [78, 91]}},
    {"name": "sequin-cocktail", "titles": ["Disco", "Electric", "After Dark", "Flash"], "description": "metallic sequin cocktail dress body skimming glamorous statement mini for nightlife and black tie party", "brand": None, "expected": {"new-york": [79, 92], "miami": [80, 93], "provence": [45, 65]}},
    {"name": "quiet-luxury-cashmere", "titles": ["Essential", "Gallery", "Soft Line", "Atelier"], "description": "cream cashmere contemporary classic sweater dress clean lines quiet luxury refined minimalist layerable", "brand": None, "expected": {"paris": [82, 94], "london": [78, 91], "copenhagen": [74, 88]}},
    {"name": "punk-plaid-mini", "titles": ["Camden", "Rebel", "Static", "Riot"], "description": "red tartan plaid mini skirt raw edge punk grunge statement styling for nightlife and city day", "brand": None, "expected": {"london": [83, 94], "tokyo": [77, 90], "new-york": [72, 86]}},
    {"name": "prairie-day-dress", "titles": ["Harvest", "Lavender", "Field", "Sunday"], "description": "cotton prairie dress puff sleeve ruffles floral print romantic cottagecore flowing midi for market day", "brand": None, "expected": {"provence": [86, 96], "tuscany": [78, 91], "tokyo": [45, 65]}},
    {"name": "ivy-pleated-look", "titles": ["Campus", "Academy", "Varsity", "Library"], "description": "navy pleated skirt oxford shirt cardigan loafers collegiate ivy style preppy heritage smart casual outfit", "brand": "Ralph Lauren", "expected": {"new-york": [84, 94], "london": [79, 92], "tokyo": [70, 85]}},
    {"name": "denim-utility-jumpsuit", "titles": ["Workshop", "Ranger", "Union", "Mechanic"], "description": "washed denim jumpsuit utility panelled cargo pockets relaxed durable streetwear for active city day", "brand": None, "expected": {"los-angeles": [77, 90], "tokyo": [77, 91], "new-york": [73, 87]}},
    {"name": "refined-satin-gown", "titles": ["Opera", "Étoile", "Palais", "Nocturne"], "description": "navy satin gown draped bias cut floor length refined glamorous evening black tie silhouette", "brand": "Dior", "expected": {"paris": [87, 97], "new-york": [79, 92], "bali": [48, 68]}},
    {"name": "tropical-cover-up", "titles": ["Cabana", "Reef", "Palm", "Heat"], "description": "bright lightweight rayon beach cover up tropical graphic print flowing airy poolside vacation style", "brand": None, "expected": {"bali": [83, 95], "miami": [79, 92], "london": [43, 65]}},
    {"name": "structured-leather-bag", "titles": ["Frame", "Ledger", "Executive", "Top Handle"], "description": "black structured handbag leather clean lines polished refined timeless day to night city accessory", "brand": "Coach", "expected": {"new-york": [84, 94], "paris": [78, 91], "london": [76, 89]}},
    {"name": "graphic-statement-sneaker", "titles": ["Metro", "Neon Step", "Block", "Street"], "description": "color block graphic sneakers technical mesh streetwear playful statement footwear for commute", "brand": "BEAMS", "expected": {"tokyo": [85, 96], "new-york": [77, 90], "los-angeles": [73, 87]}},
    {"name": "tailored-wool-coat", "titles": ["Regent", "Boulevard", "North", "Winter Line"], "description": "camel wool coat tailored double breasted structured refined timeless layerable cold weather outerwear", "brand": None, "expected": {"london": [82, 94], "paris": [81, 93], "miami": [35, 58]}},
    {"name": "playful-puff-volume", "titles": ["Daisy", "Freja", "Mabel", "Candy"], "description": "pastel puff sleeve dress oversized volume playful ruffles organic cotton expressive color market day", "brand": "Stine Goya", "expected": {"copenhagen": [85, 96], "provence": [77, 90], "new-york": [68, 83]}},
    {"name": "minimal-column-dress", "titles": ["Form", "Column", "Still", "Contour"], "description": "monochrome crepe column dress clean lines minimalist refined architectural midi for office and dinner", "brand": None, "expected": {"paris": [82, 94], "new-york": [80, 92], "copenhagen": [74, 88]}},
]


def _concepts() -> list[dict[str, object]]:
    concepts: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for group in CONCEPT_GROUPS:
        category = str(group["category"])
        group_traits = [str(item) for item in group["traits"]]
        labels = [item.strip() for item in str(group["items"]).split("|") if item.strip()]
        if len(labels) != 10:
            raise ValueError(f"Each concept group must contain ten items: {labels}")
        for label in labels:
            concept_id = _slug(label)
            if concept_id in seen_ids:
                raise ValueError(f"Duplicate concept id: {concept_id}")
            seen_ids.add(concept_id)
            traits = list(
                dict.fromkeys(
                    [*group_traits, concept_id, *RELATED_TRAITS.get(label, [])]
                )
            )
            concepts.append(
                {
                    "id": concept_id,
                    "label": label,
                    "category": category,
                    "aliases": _aliases(label, category),
                    "traits": traits,
                }
            )
    return concepts


def _calibration_garments() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for archetype in CALIBRATION_ARCHETYPES:
        titles = list(archetype["titles"])
        for index, title in enumerate(titles, start=1):
            records.append(
                {
                    "id": f"{archetype['name']}-{index}",
                    "title": f"{title} {str(archetype['name']).replace('-', ' ').title()}",
                    "description": archetype["description"],
                    "brand_name": archetype["brand"],
                    "normalized_category": "accessory" if "bag" in str(archetype["name"]) or "sneaker" in str(archetype["name"]) else "dress",
                    "expected_ranges": archetype["expected"],
                }
            )
    return records


def main() -> None:
    concepts = _concepts()
    calibration = _calibration_garments()
    alias_count = sum(len(item["aliases"]) for item in concepts)
    if len(concepts) != 400 or alias_count != 2000 or len(calibration) != 100:
        raise ValueError(
            f"Unexpected counts: concepts={len(concepts)}, aliases={alias_count}, calibration={len(calibration)}"
        )
    category_counts = Counter(str(item["category"]) for item in concepts)
    payload = {
        "schema_version": "1.0.0",
        "scoring_version": "hybrid_v1_1",
        "generated_on": date.today().isoformat(),
        "description": "Haroona deterministic fashion concept graph and calibration benchmark.",
        "counts": {
            "canonical_concepts": len(concepts),
            "aliases_and_related_phrases": alias_count,
            "calibration_garments": len(calibration),
            "destinations": len(DESTINATIONS),
            "brands": len(BRANDS),
        },
        "category_counts": dict(sorted(category_counts.items())),
        "concepts": concepts,
        "destinations": DESTINATIONS,
        "brands": BRANDS,
        "calibration_garments": calibration,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")
    print(json.dumps(payload["counts"], indent=2))


if __name__ == "__main__":
    main()
