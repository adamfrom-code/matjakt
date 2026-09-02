# -*- coding: utf-8 -*-
"""Kanoniska ingredienser: när är "det jag har hemma" det receptet vill ha?

Prismotorn svarar på en annan fråga - "är den här PRODUKTEN den här
ingrediensen?" - och gör det med butikens produktnamn som indata. Här är
båda sidor ingredienser: användarens "gul lök" mot receptets "Lök". Samma
foldning, samma försiktighet, annan relation.

MODELLEN ÄR STÄNGD SOM STANDARD. Två ingredienser hör ihop bara när något
säger det: samma kanoniska id, en STRUKTURELL regel (bestämningsord), eller
en DEKLARERAD tabell. Det finns ingen "de liknar varandra"-väg in. Därför
faller uppgiftens tre motexempel ut av sig själva, utan spärrlista:

    kycklingbuljong ≠ kyckling      tomatsås ≠ tomat      kanelknäcke ≠ kanel

Ingen av dem har en deklarerad relation, och ingen är ett bestämningsord +
grundord. Ett sammansatt ORD delas aldrig upp automatiskt - det är precis
det steget som skulle gjort kokosmjölk till mjölk och jordnötssmör till
smör.

FYRA RELATIONER, INTE EN. "Har jag det?" är inte ett ja eller nej:

    exact       samma vara                     lök / lök
    specific    jag har en SORT av det som behövs   behöver lök, har gul lök
    generic     jag har det ALLMÄNNA, receptet vill ha en sort
                                                behöver kycklingfilé, har kyckling
    substitute  två sorter av samma sak         behöver kycklingfilé, har lårfilé

Alla fyra räknas som "finns hemma", men de tre sista är märkta, så en app
kan skriva "du har lårfilé istället för filé" i stället för att låtsas att
det är samma sak. Utan generic skulle uppgiftens första milstolpe inte gå
ihop: recepten säger "Kycklingfilé" och "Gul lök", människan säger
"kyckling" och "lök".
"""

import re

# Prismotorns foldning är den kanoniska foldningen i Matjakt: gemener och
# strippade accenter, så "Kycklingfilé" och "kycklingfile" är samma sträng.
# Att skriva en egen här vore den andra sanningen den här modulen finns för
# att undvika. Samma sak för receptbankens normalized_id: id:t en delad app
# får ut ska vara id:t recepten redan bär.
from ..grocery.pricing import INGREDIENT_ALIASES, _fold
from ..recipes import normalize_ingredient_id


def _tokens(text: str) -> list:
    """Orden i ett foldat namn, i ordning. Ordningen behövs (till skillnad
    från prismotorns frozenset) eftersom "lök & vitlök" och "vitlök & lök"
    ska ge samma id men olika ord ska kunna räknas."""
    return re.findall(r"[a-z0-9]+", _fold(text))


# Ord som BARA bestämmer en vara närmare - de säger något om färg, form,
# temperatur eller ursprungskvalitet utan att göra det till en annan råvara.
# "Gul lök" är lök. "Fryst spenat" är spenat.
#
# Vad som INTE står här är det som gör listan användbar. "Krossade" tomater
# är en konservburk, inte tomater. "Soltorkade" tomater är en egen vara.
# "Grekisk" yoghurt är tjockare än yoghurt. "Gravad" lax är inte lax. Varje
# ord här är ett löfte om att det går att byta ut åt båda håll i ett kök.
QUALIFIERS = frozenset({
    "gul", "gula", "rod", "roda", "gron", "grona", "vit", "vita", "brun", "bruna",
    "svart", "svarta",
    "fryst", "frysta", "fryst", "farsk", "farska", "farskt",
    "riven", "rivet", "rivna", "hackad", "hackade", "hackat",
    "skivad", "skivade", "strimlad", "strimlade",
    "mald", "malen", "malet", "malda",
    "skalad", "skalade", "urkarnade", "urkarnad",
    "hel", "hela", "helt", "stor", "stora", "liten", "sma", "smaa",
    "ekologisk", "ekologiska", "eko",
    "kyld", "kylda", "torkad", "torkade", "torkat",
})

# Rena synonymer och singular/plural: samma vara, olika ord. De slås ihop
# till ETT kanoniskt id, till skillnad från relationerna längre ned som
# håller isär varorna men låter dem matcha varandra.
#
# Ingen automatisk pluralregel. Svensk pluralbildning (-or/-ar/-er/-n) är
# inte entydig nog: "ost"/"oster" och "sill"/"sillar" hade blivit rätt, men
# "smör"/"smörgås" och "lök"/"löken" lika gärna fel. En tabell över de ord
# vi faktiskt har är trist och korrekt.
EQUIVALENTS = {
    "tomat": "tomater",
    "morot": "morötter",
    "champinjon": "champinjoner",
    "kikärter": "kikärtor",
    "ärter": "ärtor",
    "citroner": "citron",
    "äpplen": "äpple",
    "bananer": "banan",
    "paprikor": "paprika",
    "lökar": "lök",
    "gurkor": "gurka",
    "zucchinis": "zucchini",
    "potatisar": "potatis",
    "ägget": "ägg",
    "fetaost": "feta",
    "creme fraiche": "crème fraiche",
    "cremefraiche": "crème fraiche",
    "creme fraîche": "crème fraiche",
    "sojasås": "soja",
    "soija": "soja",
    "vitlöksklyfta": "vitlök",
    "vitlöksklyftor": "vitlök",
    "olivolja extra virgin": "olivolja",
    "rapsolja": "olja",
    "matolja": "olja",
    "svart peppar": "svartpeppar",
    "vit peppar": "vitpeppar",
    "vetemjöl special": "vetemjöl",
    "mjöl": "vetemjöl",
}

# En SORT av något annat. Nyckeln är den smalare varan, värdet den bredare.
#
# Bara enordssammansättningar och namn där sambandet inte går att räkna ut
# ur orden står här - flerordsformer ("gul lök", "fryst torsk") får sitt
# samband av QUALIFIERS och behöver ingen rad.
#
# Styckningsdetaljer är avsiktligt sparsamt hanterade. Kyckling finns med:
# den som skriver "kyckling" menar filé, lårfilé eller klubbor, och alla tre
# blir samma middag. Fläskfilé och fläskkarré finns INTE med som samma
# familj - de har olika tillagningstid och byts inte rakt av.
EXTRA_SPECIALIZES = {
    "kycklingfilé": "kyckling",
    "kycklinglårfilé": "kyckling",
    "kycklingbröstfilé": "kyckling",
    "kycklingklubbor": "kyckling",
    "kycklinglår": "kyckling",
    "kycklingstrimlor": "kyckling",
    "kycklingfärs": "kyckling",
    "laxfilé": "lax",
    "torskfilé": "torsk",
    "sejfilé": "sej",
    "basmatiris": "ris",
    "jasminris": "ris",
    "grötris": "ris",
    "långkornigt ris": "ris",
    "rödlök": "lök",
    "gullök": "lök",
    "vispgrädde": "grädde",
    "matlagningsgrädde": "grädde",
    "matgrädde": "grädde",
    "gratängost": "ost",
    "hushållsost": "ost",
    "prästost": "ost",
    "nötfärs": "köttfärs",
    "blandfärs": "köttfärs",
    "fläskfärs": "köttfärs",
    "kalvfärs": "köttfärs",
    "buljongtärning": "buljong",
    "grönsaksbuljong": "buljong",
    "kycklingbuljong": "buljong",
    "spaghetti": "pasta",
    "makaroner": "pasta",
    "penne": "pasta",
    "fusilli": "pasta",
    "tagliatelle": "pasta",
    "farfalle": "pasta",
    "lasagneplattor": "pasta",
    "äggnudlar": "nudlar",
    "isbergssallad": "sallad",
    "romansallad": "sallad",
    "chiliflakes": "chili",
    "chilipulver": "chili",
    "röd currypasta": "currypasta",
    "grön currypasta": "currypasta",
}

# Varor som ofta redan står i skåpet. Ett recept ska inte rankas ned för att
# "salt" saknas i en registrerad kyl - men listan är en STANDARD, inte en
# sanning: matchningen tar emot användarens egen uppsättning, och den som
# inte har smör hemma ska få se smör som en sak att köpa.
#
# Torkade kryddor räknas med, färska örter inte. Ris, vitlök, lök och honung
# räknas INTE med, trots att en del recept i banken flaggar dem: de är
# riktiga inköp, och ett "kan lagas nu" som förutsätter ris man inte har är
# ett löfte appen inte kan hålla.
DEFAULT_PANTRY_STAPLES = frozenset(normalize_ingredient_id(name) for name in (
    "Salt", "Peppar", "Svartpeppar", "Vitpeppar", "Kryddpeppar",
    "Socker", "Olja", "Olivolja", "Smör", "Vetemjöl", "Ättika", "Vatten",
    "Maizena", "Jäst", "Bakpulver", "Kryddor",
    "Paprikapulver", "Spiskummin", "Curry", "Gurkmeja", "Kanel", "Muskot",
    "Lagerblad", "Oregano", "Timjan", "Chiliflakes", "Chilipulver",
    "Garam masala", "Tacokrydda", "Sirap",
))


def canonical_id(name: str) -> str:
    """Det stabila id:t för en ingrediens, oavsett stavning eller böjning.

    Samma härledning som receptbankens normalized_id, så en ingrediens från
    /api/v1/shared/recipes och en sträng en människa skrivit i en annan app
    landar på samma nyckel."""
    folded = _fold(name)
    if not folded:
        return ""
    # Synonymtabellen slås upp på foldad text, annars missar varje rad med
    # å/ä/ö sig själv - samma fälla som prismotorns _FOLDED_RULES löser.
    resolved = _FOLDED_EQUIVALENTS.get(folded, name)
    return normalize_ingredient_id(resolved)


def _structural_general(name: str) -> str | None:
    """Grundordet, när namnet är bestämningsord + EN vara.

    Exakt ett icke-bestämningsord krävs. "Gul lök" ger lök; "lök & vitlök"
    och "krossade tomater" ger ingenting - det första är två varor, det
    andra en egen vara vars första ord inte står i QUALIFIERS."""
    tokens = _tokens(name)
    if len(tokens) < 2:
        return None
    rest = [token for token in tokens if token not in QUALIFIERS]
    if len(rest) != 1 or len(rest) == len(tokens):
        return None
    return normalize_ingredient_id(rest[0])


def _seed_specializations() -> dict:
    """Bygger sort->vara-tabellen ur prismotorns alias plus tabellen ovan.

    INGREDIENT_ALIASES är redan Matjakts svar på "vilka namn betyder samma
    råvara" och är underhållen mot riktiga butikskörningar. Den läses här
    som alias -> nyckel: ett alias är en smalare eller likvärdig form av
    nyckeln ("gul lök" under "lök", "vispgrädde" under "grädde").

    Nycklar som SJÄLVA är bestämda former hoppas över. "Fryst torsk" har
    redan torsk som strukturellt grundord, och att dessutom skriva in torsk
    som en sort av fryst torsk hade vänt relationen upp och ned."""
    table = {}
    for key in sorted(INGREDIENT_ALIASES):
        if _structural_general(key):
            continue
        base = canonical_id(key)
        for alias in INGREDIENT_ALIASES[key]:
            alias_id = canonical_id(alias)
            # Ett alias som redan är sin egen bas, eller som pekar på en bas
            # någon annan nyckel tagit, lämnas som det är. Först i
            # bokstavsordning vinner, så tabellen blir densamma varje start.
            if alias_id and base and alias_id != base and alias_id not in table:
                table[alias_id] = base
    for narrow, broad in EXTRA_SPECIALIZES.items():
        narrow_id, broad_id = canonical_id(narrow), canonical_id(broad)
        if narrow_id and broad_id and narrow_id != broad_id:
            # Den egna tabellen väger tyngre än prismotorns alias: den är
            # skriven för den här frågan, aliasen för produktmatchning.
            table[narrow_id] = broad_id
    return table


_FOLDED_EQUIVALENTS = {_fold(key): value for key, value in EQUIVALENTS.items()}
SPECIALIZES = _seed_specializations()


def general_id(name: str) -> str | None:
    """Den bredare varan, om ingrediensen är en sort av något.

    Strukturen går före tabellen: "gul lök" är lök därför att gul är ett
    bestämningsord, inte därför att någon skrivit in raden."""
    structural = _structural_general(name)
    if structural:
        return structural
    # ETT hopp, aldrig en kedja. Transitiv upplösning hade gjort varje ny
    # aliasrad till en risk för att två orelaterade varor plötsligt delar
    # rot, och roten är det enda som avgör om två saker får bytas mot
    # varandra.
    return SPECIALIZES.get(canonical_id(name))


def canonical_ingredient(name: str) -> dict:
    """Allt lagret vet om ett ingrediensnamn, som data.

    Det här är vad /api/v1/shared/ingredients returnerar, och vad en app
    behöver för att visa "lök" när användaren skrev "Gul Lök 2 st"."""
    identifier = canonical_id(name)
    general = general_id(name)
    return {
        "id": identifier,
        "name": str(name or "").strip(),
        "generalId": general,
        "isPantryStaple": identifier in DEFAULT_PANTRY_STAPLES,
    }


# Hur säker en träff är, från säkrast till lösast. Ordningen används när
# flera skafferivaror matchar samma receptrad - den bästa vinner, så
# "du har kyckling" inte skriver över "du har kycklingfilé".
MATCH_RANK = {"exact": 0, "specific": 1, "generic": 2, "substitute": 3}


def satisfies(have: str, need: str) -> str | None:
    """Duger `have` hemma för receptets `need`? Returnerar relationen.

    None betyder nej, och nej är standardsvaret: bara de fyra relationerna
    modulens docstring räknar upp ger en träff."""
    have_id, need_id = canonical_id(have), canonical_id(need)
    if not have_id or not need_id:
        return None
    if have_id == need_id:
        return "exact"
    have_general, need_general = general_id(have), general_id(need)
    if have_general == need_id:
        return "specific"
    if need_general == have_id:
        return "generic"
    if have_general and have_general == need_general:
        return "substitute"
    return None


def best_match(have_names, need: str):
    """Den bästa av flera skafferivaror för en receptrad.

    Returnerar (namnet, relationen) eller (None, None). Exakt slår sort,
    sort slår allmän, allmän slår utbyte - och vid lika relation vinner den
    som kom först, så svaret inte ändras för att en app råkar skicka sitt
    skafferi i annan ordning."""
    best = (None, None)
    for candidate in have_names:
        relation = satisfies(candidate, need)
        if relation is None:
            continue
        if best[1] is None or MATCH_RANK[relation] < MATCH_RANK[best[1]]:
            best = (candidate, relation)
            if relation == "exact":
                break
    return best
