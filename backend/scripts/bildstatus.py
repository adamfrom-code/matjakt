# -*- coding: utf-8 -*-
"""Klassificerar varje receptbild efter vad KÄLLAN säger att fotot visar.

    python backend/scripts/bildstatus.py           # skriver docs/bildstatus.json + BILDSTATUS.md
    python backend/scripts/bildstatus.py --check   # jämför, exit 1 vid drift
    python backend/scripts/bildstatus.py --hamta   # uppdatera Wikimedia-cachen (nät)

P09a. Rättigheter räcker inte: en bild på fel maträtt är fel data. 113 av
229 recept delar bild med ett annat, och alt-texten är GENERERAD ur
receptnamnet ("<namn> upplagd på tallrik") - samma Pexels-foto bär nio alt-
texter som påstår nio olika rätter. Alt-texten är alltså inget bevis; den
ljuger med bilden.

Beviset är källan själv. Pexels-länken bär fotografens egen titel som slug:
fotot nio bowl-recept delar heter "close up of variety of rice in bowls",
grytfotot för nio grytor "top view of cooking ingredients", köttbullarnas
"fried meat cutlet served with boiled potatoes and salad". Wikimedia bär
filnamn och ibland beskrivning; de hämtas en gång och committas som cache
(docs/bildstatus-wikimedia.json) så att --check är offline.

Reglerna är deterministiska och KONSERVATIVA, i denna ordning:

  MISSING               ingen bild i källan
  REJECTED              fotots protein ≠ rättens (salmon för en kycklingrätt)
                        · en köttbit för en färsrätt
                        · generisk titel ("cooking ingredients", "variety of")
                        · delas av recept med OLIKA huvudprotein - högst ett
                          kan vara rätt, och ingen är bevisat rätt
  EXACT-KANDIDAT        titeln nämner rättens protein, eller en riktig
                        rättterm (inte bara ris/potatis/sallad/pasta) - och
                        ingen delar fotot. Bekräftas med ögat.
  GOOD_VARIANT-KANDIDAT delas av recept med samma rättyp; högst ett EXACT
  NEEDS_REVIEW          titeln avgör inte

Ingen status här ändrar något i appen. Det gör P09b: sätta image_status ur
den här filen och visa reservkortet för REJECTED. Hellre MISSING än fel bild.
"""

import argparse
import collections
import html
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KÄLLOR = ROOT / "backend" / "recipe_sources"
UT_JSON = ROOT / "docs" / "bildstatus.json"
UT_MD = ROOT / "docs" / "BILDSTATUS.md"
WIKI_CACHE = ROOT / "docs" / "bildstatus-wikimedia.json"
# P09b: det servern läser vid import - status och alt-text per recept.
UT_APP = ROOT / "backend" / "services" / "recipes" / "bildstatus.json"

STATUSAR = ("MISSING", "REJECTED", "EXACT-KANDIDAT", "GOOD_VARIANT-KANDIDAT", "NEEDS_REVIEW")

# Svensk rättterm i receptnamnet -> ord fotografen använder. Tillbehör
# (ris, potatis, sallad, pasta, bowl) räknas INTE som rätt-bevis ensamma.
TERM = {
    "lax": ["salmon"], "torsk": ["cod"], "räk": ["shrimp", "prawn"], "sill": ["herring"], "tonfisk": ["tuna"],
    "kyckling": ["chicken"], "biff": ["steak", "beef", "medallion"], "köttbull": ["meatball"],
    "köttfärs": ["mince", "ground beef", "bolognese", "meat sauce"], "fläsk": ["pork"], "karré": ["pork"],
    "korv": ["sausage", "hot dog"], "bacon": ["bacon"], "kassler": ["ham"], "skinka": ["ham"], "lamm": ["lamb"],
    "halloumi": ["halloumi"], "tofu": ["tofu"], "falafel": ["falafel"], "lins": ["lentil"], "kikärt": ["chickpea"],
    "soppa": ["soup"], "lasagne": ["lasagna", "lasagne"], "pizza": ["pizza"], "taco": ["taco"], "wrap": ["wrap"],
    "burgare": ["burger"], "gratäng": ["gratin", "casserole"], "gryta": ["stew", "goulash"], "curry": ["curry"],
    "wok": ["stir fry", "wok"], "pannkak": ["pancake"], "pytt": ["hash"], "poke": ["poke"], "risotto": ["risotto"],
    "gnocchi": ["gnocchi"], "omelett": ["omelet"], "quesadilla": ["quesadilla"], "chili": ["chili"],
    "stroganoff": ["stroganoff"], "schnitzel": ["schnitzel"], "kroppkak": ["kroppkaka", "dumpling"],
    "isterband": ["isterband", "sausage"], "ärtsoppa": ["pea soup"], "pudding": ["pudding"],
}
TILLBEHÖR = {"ris", "potatis", "sallad", "pasta", "bowl"}
PROT = {"lax": "fisk", "torsk": "fisk", "fisk": "fisk", "räk": "fisk", "sej": "fisk", "sill": "fisk", "tonfisk": "fisk",
        "kyckling": "kyckling", "biff": "nöt", "rostbiff": "nöt", "köttbull": "färs", "köttfärs": "färs", "färs": "färs",
        "fläsk": "fläsk", "karré": "fläsk", "kassler": "fläsk", "skinka": "fläsk", "bacon": "fläsk", "korv": "korv",
        "isterband": "korv", "lamm": "lamm", "halloumi": "vego", "tofu": "vego", "bön": "vego", "lins": "vego",
        "kikärt": "vego", "falafel": "vego", "vego": "vego", "vegansk": "vego", "ägg": "ägg"}
PROT_EN = {"salmon": "fisk", "cod": "fisk", "fish": "fisk", "shrimp": "fisk", "prawn": "fisk", "herring": "fisk",
           "tuna": "fisk", "chicken": "kyckling", "steak": "nöt", "beef": "nöt", "pork": "fläsk", "ham": "fläsk",
           "bacon": "fläsk", "sausage": "korv", "lamb": "lamm", "halloumi": "vego", "tofu": "vego", "bean": "vego",
           "lentil": "vego", "chickpea": "vego", "meatball": "färs", "mince": "färs", "cutlet": "kött", "egg": "ägg"}
GENERISKA = ("cooking ingredients", "variety of", "assorted", "close up of food", "food on table",
             "table with food", "ingredients on", "top view of food", "flat lay")


def _källor():
    for path in sorted(KÄLLOR.glob("*.json")):
        for r in json.loads(path.read_text(encoding="utf-8")):
            yield r


def _slug(url):
    m = re.search(r"pexels\.com/(?:sv-se/)?photo/([a-z0-9-]+?)-\d+/?$", url or "")
    return m.group(1).replace("-", " ") if m else ""


def _protein_sv(name):
    n = name.lower()
    for k, v in PROT.items():
        if k in n:
            return v
    return None


def _protein_en(text):
    t = text.lower()
    for k, v in PROT_EN.items():
        if k in t:
            return v
    return None


def _terms(name, text):
    n, t = name.lower(), text.lower()
    return [k for k, ens in TERM.items() if k in n and any(e in t for e in ens)]


def ren_text(value: str) -> str:
    """Commons-beskrivningen som TEXT: entiteter avkodade, taggar borta.

    Commons skickar ibland HTML-escapad HTML ("&lt;a href=...&gt;"), och
    ett taggfilter som bara ser riktiga taggar släppte igenom en hel
    fotografs länk i klartext - och klartextvakten (test_utgaende_i_klartext)
    fällde cachen för en http-adress vi aldrig anropar. Länkar är inte
    beskrivning; namnet räcker som attribution. Skulle en bar adress ändå
    stå kvar i löptexten skrivs den med https - det är en adress i en
    text, inte något vi hämtar, och vakten gör ingen skillnad på de två.
    """
    text = html.unescape(value or "")
    text = html.unescape(text)  # dubbelt escapad förekommer (&amp;lt;)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace("http://", "https://")


def hamta_wikimedia(recept) -> dict:
    """Nät. Körs bara med --hamta; resultatet committas."""
    titlar = {}
    for r in recept:
        if "wikimedia" in (r.get("imageSourceUrl") or "").lower():
            m = re.search(r"(File:[^?#]+)", urllib.parse.unquote(r["imageSourceUrl"]))
            if m:
                titlar[r["id"]] = m.group(1)
    meta = {}
    if titlar:
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query", "prop": "imageinfo", "iiprop": "extmetadata", "format": "json",
            "titles": "|".join(sorted(set(titlar.values())))})
        req = urllib.request.Request(url, headers={"User-Agent": "Matjakt-bildaudit/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        for page in data.get("query", {}).get("pages", {}).values():
            ii = (page.get("imageinfo") or [{}])[0].get("extmetadata", {})
            desc = ren_text(ii.get("ImageDescription", {}).get("value", ""))
            meta[page.get("title")] = {"beskrivning": desc[:200],
                                       "licens": ii.get("LicenseShortName", {}).get("value", "")}
    return {"titlar": titlar, "meta": meta}


def klassificera(recept, wiki) -> list[dict]:
    by_url = collections.defaultdict(list)
    namn = {}
    for r in recept:
        namn[r["id"]] = r["name"]
        if r.get("image"):
            by_url[r["image"]].append(r["id"])
    rader = []
    for r in recept:
        rid, name, img = r["id"], r["name"], r.get("image") or ""
        src = r.get("imageSourceUrl") or ""
        delare = [x for x in by_url.get(img, []) if x != rid]
        bevis = {"kalla": r.get("imageSource") or None, "kallankning": src or None}
        if not img:
            rader.append({"id": rid, "namn": name, "status": "MISSING", "skal": "ingen bild i källan",
                          "bevis": bevis, "delas_med": []})
            continue
        if "pexels" in src:
            titel = _slug(src)
            bevis["fotografens_titel"] = titel
        else:
            t = wiki.get("titlar", {}).get(rid, "")
            m = wiki.get("meta", {}).get(t, {})
            titel = (t.replace("File:", "").replace("_", " ").rsplit(".", 1)[0] + " " + (m.get("beskrivning") or "")).strip()
            bevis["fil"] = t or None
            bevis["beskrivning"] = m.get("beskrivning") or None
        p_sv, p_en = _protein_sv(name), _protein_en(titel)
        hits = _terms(name, titel)
        riktiga = [h for h in hits if h not in TILLBEHÖR]
        generisk = any(g in titel.lower() for g in GENERISKA)
        grupp = {_protein_sv(namn[d]) for d in delare} | {p_sv}
        blandad = len(grupp - {None}) > 1
        if p_en and p_sv and p_en not in (p_sv, "kött"):
            status, skal = "REJECTED", f'fotot visar {p_en} ("{titel}"), rätten är {p_sv}'
        elif p_en == "kött" and p_sv == "färs":
            status, skal = "REJECTED", f'fotot visar en köttbit ("{titel}"), rätten är färs'
        elif generisk:
            status, skal = "REJECTED", f'generiskt matfoto ("{titel}") - visar ingen bestämd rätt'
        elif delare and blandad:
            status, skal = "REJECTED", f"delas av {len(delare) + 1} recept med olika huvudprotein ({', '.join(sorted(x for x in grupp if x))})"
        elif not delare and ((p_en and p_en == p_sv) or riktiga):
            vad = ", ".join(riktiga) if riktiga else f"proteinet ({p_sv})"
            status, skal = "EXACT-KANDIDAT", f'titeln nämner {vad} ("{titel}") - bekräfta med ögat'
        elif delare:
            status, skal = "GOOD_VARIANT-KANDIDAT", f"delas av {len(delare) + 1} recept med samma rättyp; högst ett kan vara EXACT"
        else:
            status, skal = "NEEDS_REVIEW", f'titeln avgör inte ("{titel}")'
        rader.append({"id": rid, "namn": name, "status": status, "skal": skal, "bevis": bevis, "delas_med": delare})
    return rader


def alt_text(rad: dict) -> str | None:
    """Alt-texten ur BEVISET, aldrig ur receptnamnet (P09a: alt-texten
    "<namn> upplagd på tallrik" ljög med bilden). Fotografens titel eller
    Commons-filnamnet säger vad fotot visar; källan står med, så en
    skärmläsare hör var det kommer ifrån. None när det inte finns något
    bevis att bygga på."""
    if rad["status"] not in ("EXACT-KANDIDAT", "GOOD_VARIANT-KANDIDAT"):
        return None
    b = rad.get("bevis") or {}
    titel = (b.get("fotografens_titel") or "").strip()
    if not titel and b.get("fil"):
        titel = b["fil"].replace("File:", "").rsplit(".", 1)[0].replace("_", " ").strip()
    if not titel and b.get("beskrivning"):
        titel = str(b["beskrivning"]).strip()[:120]
    kalla = b.get("kalla") or "okänd källa"
    return f"{titel} (foto: {kalla})" if titel else f"Foto: {kalla}"


def rendera_app(rader) -> str:
    """Den kompakta kartan servern läser: {id: {status, alt}}. Sorterad, så
    en ändring i ett recept ger en diff på det receptet."""
    karta = {r["id"]: {"status": r["status"], "alt": alt_text(r)} for r in sorted(rader, key=lambda r: r["id"])}
    return json.dumps(karta, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def rendera_md(rader) -> str:
    c = collections.Counter(r["status"] for r in rader)
    ut = ["# Bildstatus — vad källan säger att fotot visar", "",
          "Genererad av `backend/scripts/bildstatus.py`. Redigera inte för hand — kör skriptet.", "",
          "| status | antal | betyder |", "|---|---|---|",
          f"| MISSING | {c['MISSING']} | ingen bild i källan |",
          f"| REJECTED | {c['REJECTED']} | källan säger att fotot visar något annat, eller ett generiskt foto, eller delas av rätter med olika protein |",
          f"| EXACT-KANDIDAT | {c['EXACT-KANDIDAT']} | fotografens titel nämner rättens protein eller rättterm — bekräftas med ögat |",
          f"| GOOD_VARIANT-KANDIDAT | {c['GOOD_VARIANT-KANDIDAT']} | delas av recept med samma rättyp; högst ett kan vara EXACT |",
          f"| NEEDS_REVIEW | {c['NEEDS_REVIEW']} | titeln avgör inte |", "",
          "## Alt-texten är inget bevis", "",
          "`imageAlt` är genererad ur receptnamnet (*\"<namn> upplagd på tallrik\"*). Samma foto bär därför olika alt-texter som påstår olika rätter. Den ska inte användas som evidens och bör i P09b ersättas med källans egen beskrivning eller *\"Foto: <källa>\"*.", "",
          "## REJECTED, med bevis", "", "| id | namn | skäl |", "|---|---|---|"]
    for r in rader:
        if r["status"] == "REJECTED":
            ut.append(f"| `{r['id']}` | {r['namn']} | {r['skal']} |")
    ut += ["", "## MISSING", "", ", ".join(f"`{r['id']}`" for r in rader if r["status"] == "MISSING"), "",
           "## Nästa steg (P09b, inte det här paketet)", "",
           "1. `image_status` sätts ur `docs/bildstatus.json` vid import; REJECTED visar reservkortet. Hellre MISSING än fel bild.",
           "2. EXACT-KANDIDAT och GOOD_VARIANT-KANDIDAT bekräftas med ögat och blir EXACT / GOOD_VARIANT / REJECTED.",
           "3. Alt-texten byts mot källans beskrivning.", ""]
    return "\n".join(ut)


def main(argv=None) -> int:
    tolk = argparse.ArgumentParser()
    tolk.add_argument("--check", action="store_true")
    tolk.add_argument("--hamta", action="store_true", help="uppdatera Wikimedia-cachen (nät)")
    arg = tolk.parse_args(argv)
    recept = list(_källor())
    if arg.hamta:
        WIKI_CACHE.write_text(json.dumps(hamta_wikimedia(recept), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wikimedia-cachen uppdaterad: {WIKI_CACHE.relative_to(ROOT)}")
    wiki = json.loads(WIKI_CACHE.read_text(encoding="utf-8")) if WIKI_CACHE.exists() else {}
    rader = klassificera(recept, wiki)
    js = json.dumps(rader, ensure_ascii=False, indent=1) + "\n"
    md = rendera_md(rader)
    app = rendera_app(rader)
    if arg.check:
        ok = (UT_JSON.exists() and UT_JSON.read_text(encoding="utf-8") == js and UT_MD.exists()
              and UT_MD.read_text(encoding="utf-8") == md
              and UT_APP.exists() and UT_APP.read_text(encoding="utf-8") == app)
        print("bildstatus stämmer med källorna" if ok else
              "bildstatus är INTE genererad ur dagens källor. Kör: python backend/scripts/bildstatus.py", file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    UT_JSON.write_text(js, encoding="utf-8")
    UT_MD.write_text(md, encoding="utf-8")
    UT_APP.write_text(app, encoding="utf-8")
    c = collections.Counter(r["status"] for r in rader)
    print("skrev docs/bildstatus.json + docs/BILDSTATUS.md:", dict(c))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
