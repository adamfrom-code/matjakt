# -*- coding: utf-8 -*-
"""Vad som ANTAS FINNAS HEMMA - en lista över ingredienser, inte ett beslut
per recept.

`pantry_staple = 1` betyder *"antas finnas hemma"*: raden prissätts aldrig
(`grocery/audit.py` hoppar över den) och hamnar i `rows.home` i stället för
`rows.buy` i receptvyn. Fältet finns för att en inköpslista inte ska säga åt
någon att köpa salt varje vecka.

FÖRE M3 VAR DET ETT BESLUT PER RAD, och då blev samma ingrediens klassad åt
två håll i olika recept: ägg prissattes i 34 recept och antogs finnas hemma i
2, vitlök i 70 mot 9, ris i 50 mot 1. Det är ingen smaksak. I just de recept
där ingrediensen låg på skafferisidan blev portionspriset för lågt OCH
inköpslistan för kort - en rätt som behöver ägg gav inga ägg.

ROTEN ÄR SPÅRBAR. `scripts/migrate_recipes.py` byggde bankens 52 äldsta
recept ur den gamla `RECEPT`-arrayen i app.js, och där fanns `hemma: [...]`
vid sidan av de fyra ingredienser den gamla prislistan kände till. Allt som
inte rymdes i prislistan hamnade i `hemma` och skrevs som `pantryStaple`.
"Antas finnas hemma" betydde alltså i praktiken "fanns inte i den gamla
prislistan" - och 33 av de 40 raderna som M3 flyttade tillbaka till köpsidan
kom ur den enda filen `batch00_migrerade.json`.

HUR LISTAN NEDAN BESTÄMDES. Två regler, i den ordningen:

1. **Uppdragets egen lista gäller.** Skafferivaror är sådant man doserar
   efter smak och har kvar månader efter att det öppnats: salt, peppar, olja,
   smör, socker, ättika och vanliga torra kryddor. Ägg, lök och vitlök är
   varor man köper.
2. **För övriga avgör bankens egen dominerande behandling.** Den som redan
   gäller i de allra flesta raderna är svaret; minoriteten är felet. Det är
   uppdragets eget resonemang om ägget ("det gör priset fel i just de två"),
   tillämpat på alla 21 ingredienser som var klassade åt två håll.

De två reglerna sammanfaller på varje ingrediens uppdraget nämner vid namn -
smör 63 mot 16, olivolja 20 mot 3, ättika 7 mot 1, ägg 2 mot 34, vitlök 9 mot
70, lök 2 mot 3. Ett test i `test_recipe_pantry.py` håller kvar den
sammanfallningen, för det är den som gör regel 2 till något annat än en
omröstning.

EN KÄND KANT, MEDVETET LÄMNAD. Banken prissätter curry, garam masala,
gurkmeja, kanel och tacokrydda i *varje* rad de förekommer i, samtidigt som
chilipulver, kryddpeppar och spiskummin aldrig prissätts. Båda grupperna är
konsekventa med sig själva, och M3 rör bara det som var klassat åt två håll.
Att dra en linje genom hela kryddhyllan är nästa fråga - den ska tas som ett
eget paket, med sin egen priseffekt uppmätt, inte som en bieffekt av det här.
"""

# normaliserat id -> varför det står här. Nyckeln är `normalize_ingredient_id`
# av namnet: samma härledning som kopplar en receptrad till varuvärlden, så
# "Smör" och "smör " landar på samma rad i listan.
#
# Listan är STÄNGD på samma sätt som M1:s värdeförråd: det som inte står här
# är en köpvara. Att fela åt det hållet är rätt håll - en ny ingrediens som
# ingen klassificerat hamnar på inköpslistan och prissätts, i stället för att
# tyst antas finnas hemma och försvinna ur både pris och lista.
PANTRY_STAPLES = {
    # Salt och peppar. Bankens två vanligaste rader överhuvudtaget.
    "salt": "Doseras efter smak, finns i varje kök.",
    "peppar": "Doseras efter smak, finns i varje kök.",
    "svartpeppar": "Doseras efter smak, finns i varje kök.",
    "vitpeppar": "Doseras efter smak, finns i varje kök.",
    "kryddpeppar": "Torr krydda i burk, räcker i åratal.",

    # Torra kryddor som banken aldrig prissätter i någon rad.
    "kryddor": "Receptets samlingsrad för kryddhyllan - har aldrig en mängd.",
    "chilipulver": "Torr krydda i burk, räcker i åratal.",
    "chiliflakes": "Torr krydda i burk, räcker i åratal.",
    "spiskummin": "Torr krydda i burk. Banken har den som skafferi i 12 rader av 17.",
    "muskot": "Torr krydda i burk, rivs i krm.",
    "lagerblad": "Torr krydda i burk, ett blad i taget.",

    # Matfett. Uppdraget nämner både olja och smör vid namn, och banken gör
    # likadant i 113 av 113 respektive 63 av 79 rader.
    "olja": "Stekfett - doseras i skvätt, aldrig en inköpspost per rätt.",
    "olivolja": "Stekfett - doseras i skvätt, aldrig en inköpspost per rätt.",
    "smor": "Stekfett. Banken har det som skafferi i 63 rader av 79.",

    # Sötning och syra: flaskan respektive paketet som står kvar i skåpet.
    "socker": "Ett kilo räcker ett år, doseras i msk.",
    "attika": "Doseras i skvätt. Flaskan håller i praktiken hur länge som helst.",
    "fisksas": "Doseras i tsk ur en flaska som räcker månader.",

    # Redning.
    "maizena": "Redning i tsk ur ett paket som räcker månader.",
}

# De tre uppdraget pekar ut som varor man KÖPER. De står här för att ett test
# ska kunna kräva att de aldrig smyger in i listan ovan - inte för att koden
# behöver dem: allt som inte står i PANTRY_STAPLES är redan en köpvara.
ALDRIG_SKAFFERI = ("agg", "lok", "vitlok")


class PantryStapleConflict(ValueError):
    """En receptrad påstår motsatsen till vad listan säger om ingrediensen."""


def _key(name_or_id: str) -> str:
    """Normaliserar ett ingrediensnamn till listans nyckel.

    Importen är lokal för att bryta cirkeln: `store` importerar den här
    modulen för att kunna härleda flaggan vid skrivning."""
    from .store import normalize_ingredient_id
    return normalize_ingredient_id(name_or_id)


def is_pantry_staple(name_or_id) -> bool:
    """Är den här ingrediensen en skafferivara? Listan svarar, inte raden."""
    return _key(name_or_id or "") in PANTRY_STAPLES


def reason(name_or_id) -> str:
    """Varför ingrediensen antas finnas hemma. Tom sträng för en köpvara."""
    return PANTRY_STAPLES.get(_key(name_or_id or ""), "")


def require(name_or_id, flagged) -> bool:
    """Släpper igenom en rad som säger samma sak som listan, kastar annars.

    Används av importvägen (`scripts/import_recipes.py`), där en källfil är
    något en människa just har skrivit och felet ska synas direkt. Butiken
    (`RecipeStore`) HÄRLEDER i stället flaggan ur listan: en redan skriven
    databas ska bli konsekvent av att öppnas, inte vägra öppna sig."""
    expected = is_pantry_staple(name_or_id)
    if bool(flagged) == expected:
        return expected
    if expected:
        raise PantryStapleConflict(
            f"{name_or_id!r} är en skafferivara ({reason(name_or_id)}) men raden "
            f"har en mängd och prissätts. Ta bort mängden, eller ta bort "
            f"ingrediensen ur PANTRY_STAPLES i services/recipes/pantry.py.")
    raise PantryStapleConflict(
        f"{name_or_id!r} är märkt som skafferivara men står inte i "
        f"PANTRY_STAPLES. En vara man köper ska ha en mängd och prissättas - "
        f"annars blir portionspriset för lågt och varan saknas på listan.")
