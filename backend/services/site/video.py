# -*- coding: utf-8 -*-
"""Klipp till Matjakts presentation, hämtade från Pexels video-API.

Same key, same licence and the same rule as the recipe photos: we only use
sources we may actually use commercially, and we store where every clip came
from so its origin can be shown later.

WHAT MAKES THIS DIFFERENT FROM PICKING SIX NICE VIDEOS. A presentation is a
sequence, not a gallery. Each scene here has a job in the story - choosing
food, the week taking shape, the list, real packages on a shelf, the
comparison, the saving - so a clip is judged on whether it plays ITS scene,
not on whether it is pretty. That is the whole difference between a
presentation and a stock-footage reel, and it is why the queries and the
scoring live next to the script instead of being one generic "food" search.
"""

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from ..recipes.images import PEXELS_LICENCE, USER_AGENT, pexels_key

PEXELS_VIDEO_API = "https://api.pexels.com/videos/search"

# Where the clips land. Served by GitHub Pages next to the landing page, not
# hotlinked from Pexels: a marketing page that goes blank because someone
# else's CDN changed a URL is a page we do not control.
CLIP_DIR = Path(__file__).resolve().parents[3] / "frontend" / "site" / "video"
# The path the LANDING PAGE uses, which is not the path the directory has.
# Writing "video/x.mp4" into the manifest gave every clip a URL relative to
# the site root instead of to the page, and the presentation rendered as
# empty green tiles - poster and clip both 404.
WEB_PREFIX = "site/video"
MANIFEST = CLIP_DIR / "clips.json"

# A background loop wants a few calm seconds. Under 4s visibly stutters on the
# loop point; over 25s is weight we make the phone carry for nothing.
MIN_DURATION, MAX_DURATION = 4, 25
# Below this the clip looks soft blown up to full width; above it we are
# shipping cinema resolution to a phone.
MIN_WIDTH, MAX_WIDTH = 960, 1920

# Things that are never in a Matjakt presentation, however good the footage.
# Alcohol and restaurant-bar scenes are not what a household grocery budget
# looks like; the rest simply are not food.
FORBIDDEN = [
    "dog", "cat", "pet", "puppy", "kitten", "smoking", "cigarette", "vape",
    "beer", "wine", "cocktail", "whiskey", "vodka", "bar", "alcohol", "drunk",
    "blood", "hunting", "slaughter", "gun", "war", "christmas", "halloween",
    "birthday", "wedding", "makeup", "fashion",
    # The list scene once got a clip of someone filling in an INVOICE -
    # "BILL TO", "P.O. NUMBER", a Redmond WA address. Technically a hand
    # writing on paper; visibly not a shopping list, and the sort of thing a
    # viewer notices immediately.
    "invoice", "bill", "office", "desk", "work", "business", "laptop",
    "sticky", "poster", "meeting", "chinese", "convenience",
]

# Klipp vi valt med ögat, per scen. Sökning kan sortera bort det som är fel;
# den kan inte avgöra vad som känns svenskt. These ids are the difference
# between a cramped shop with PROMO signage and a bright Nordic aisle, and no
# amount of query tuning gets there reliably - so the good ones are named.
PEXELS_VIDEO_BY_ID = "https://api.pexels.com/videos/videos"


def _slug_words(url: str) -> list[str]:
    """The words Pexels put in a clip's page URL.

    Videos carry no alt text, but the page slug is a human-written sentence
    ("a-woman-cooking-in-the-kitchen-3298830") - the best relevance signal the
    API gives us, so we read it rather than guessing from the thumbnail."""
    slug = urllib.parse.urlparse(url or "").path.rstrip("/").rsplit("/", 1)[-1]
    return [w for w in re.split(r"[^a-z]+", slug.lower()) if w]


# The script. Order is the story order, and each scene states what it must
# show - so a clip that is merely food-adjacent cannot drift in.
SCENES = [
    {
        "key": "hero",
        # ljust skandinaviskt kök, kvinna lagar mat
        "prefer": [8176824, 7496073],
        "queries": ["cooking fresh vegetables kitchen", "home cooking pan vegetables",
                    "chopping vegetables kitchen"],
        "want": ["cook", "cooking", "kitchen", "vegetable", "vegetables", "fresh",
                 "chopping", "pan", "food", "preparing"],
        "headline": "Planera veckan.",
    },
    {
        "key": "valj",
        # någon serverar en färdig rätt på trabord
        "prefer": [5765844, 34521396],
        "queries": ["delicious homemade dinner plate", "serving dinner plate food",
                    "tasty meal on table"],
        "want": ["dinner", "plate", "meal", "food", "serving", "delicious", "dish",
                 "homemade", "table"],
        "headline": "Välj vad du vill äta.",
        "caption": "Du säger vad du är sugen på.",
    },
    {
        "key": "vecka",
        # ljust minimalistiskt kök, veckoplanen skrivs
        "prefer": [8845453, 8845456],
        "queries": ["meal prep containers food", "preparing meals for the week",
                    "healthy meal prep"],
        "want": ["meal", "prep", "containers", "week", "preparing", "healthy",
                 "food", "lunch", "boxes"],
        "headline": "Matjakt bygger veckan.",
        "caption": "Sju middagar som håller din budget.",
    },
    {
        "key": "lista",
        # lista skrivs bland färska grönsaker
        "prefer": [5449990, 8851746],
        "queries": ["writing shopping list", "person using phone in kitchen",
                    "making a list notebook kitchen"],
        "want": ["writing", "list", "shopping", "phone", "notebook", "kitchen",
                 "hand", "paper", "planning"],
        "headline": "Recepten blir en inköpslista.",
        "caption": "Allt du behöver, i rätt mängd.",
    },
    {
        "key": "produkter",
        # mejerihyllan - riktiga förpackningar, ljus butik
        "prefer": [39221961, 34506452],
        "queries": ["grocery store shelves products", "supermarket shelf groceries",
                    "picking product from shelf"],
        "want": ["grocery", "supermarket", "shelf", "shelves", "store", "products",
                 "aisle", "picking", "market"],
        "headline": "Riktiga produkter och förpackningar.",
        "caption": "Rätt förpackning, inte ett cirkapris.",
    },
    {
        "key": "butiker",
        # par med kundvagn i ljus grönsaksavdelning
        "prefer": [4121625, 34982661],
        "queries": ["shopping cart supermarket aisle", "pushing trolley grocery store",
                    "woman shopping groceries"],
        "want": ["cart", "trolley", "supermarket", "grocery", "aisle", "shopping",
                 "store", "walking", "market"],
        "headline": "Jämför riktiga matpriser.",
        "caption": "Samma lista, flera butiker.",
    },
    {
        "key": "billigast",
        # kassan, ljus och ren
        "prefer": [5103988, 8421358],
        "queries": ["paying at grocery checkout", "supermarket checkout counter",
                    "cashier scanning groceries"],
        "want": ["paying", "checkout", "cashier", "counter", "scanning", "receipt",
                 "payment", "grocery", "supermarket", "store"],
        "headline": "Spara pengar varje vecka.",
        "caption": "Du ser var veckan blir billigast.",
    },
]

CLOSING = "Matjakt gör jobbet åt dig."


def _get(url: str, params: dict) -> dict:
    key = pexels_key()
    if not key:
        return {}
    request = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(params)}",
        headers={"Authorization": key, "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_by_id(video_id: int) -> dict | None:
    """One named clip, or None if it is gone.

    A pinned id can stop working - contributors remove clips. Falling back to
    search then costs a slightly worse clip, not a broken page."""
    try:
        data = _get(f"{PEXELS_VIDEO_BY_ID}/{video_id}", {})
    except Exception:
        return None
    return data if data.get("video_files") else None


def score_clip(video: dict, scene: dict) -> float:
    """How well one clip plays this particular scene.

    Returns 0 for anything disqualified - a clip that cannot be used should
    not be ranked at all, only excluded."""
    words = set(_slug_words(video.get("url", "")))
    if not words or words & set(FORBIDDEN):
        return 0.0
    duration = video.get("duration") or 0
    if not MIN_DURATION <= duration <= MAX_DURATION:
        return 0.0

    hits = words & set(scene["want"])
    # One incidental word ("food") is not evidence that a clip shows a
    # checkout. Two independent matches is the difference between a clip that
    # plays the scene and a clip that merely comes from the same world.
    if len(hits) < 2:
        return 0.0

    score = float(len(hits))
    # A short loop reads as deliberate; a long one gets cut off mid-motion.
    if 6 <= duration <= 15:
        score += 1.0
    if (video.get("width") or 0) >= 1920:
        score += 0.5
    return score


def pick_file(video: dict, vertical: bool = False) -> dict | None:
    """The rendition to actually download.

    Pexels offers the same clip from phone-sized to 4K. We want the smallest
    file that still looks sharp full-width, because every megabyte here is a
    megabyte a phone on mobile data pays for."""
    files = [f for f in video.get("video_files", [])
             if (f.get("file_type") == "video/mp4") and f.get("link")]
    if not files:
        return None
    wanted = [f for f in files if MIN_WIDTH <= (f.get("width") or 0) <= MAX_WIDTH]
    candidates = wanted or files
    if vertical:
        portrait = [f for f in candidates if (f.get("height") or 0) > (f.get("width") or 0)]
        candidates = portrait or candidates
    # Smallest acceptable rendition, not the biggest available.
    return min(candidates, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0))


def _too_similar(words: set, already_used: list) -> bool:
    """Whether this clip is, to a viewer, the previous clip again.

    Two DIFFERENT Pexels ids can be the same footage from the same shoot -
    "busy-supermarket-aisle-with-shoppers" came back for both the products
    scene and the compare-stores scene. Distinct clips, one visual. In a
    28-second film that reads as a mistake, so near-duplicates are refused on
    what they show rather than on their id."""
    for previous in already_used:
        overlap = len(words & previous)
        if overlap >= 3 and overlap / max(len(words | previous), 1) > 0.5:
            return True
    return False


def find_clip(scene: dict, used_ids: set | None = None,
              orientation: str = "landscape",
              used_slugs: list | None = None) -> dict | None:
    """The best clip for one scene, or None when nothing is good enough.

    None is a real answer. A scene with no fitting clip should fall back to a
    still image, not be filled with footage that undermines the story."""
    used_ids = used_ids if used_ids is not None else set()
    used_slugs = used_slugs if used_slugs is not None else []

    # A clip chosen by eye beats anything scoring can find, so the vetted
    # ones are tried first and are not re-scored - they were already judged,
    # by looking at them.
    for video_id in scene.get("prefer", []):
        if video_id in used_ids:
            continue
        picked = fetch_by_id(video_id)
        if picked:
            built = _describe(picked, scene, orientation, score=9.9)
            if built:
                return built

    best, best_score = None, 0.0
    for query in scene["queries"]:
        try:
            data = _get(PEXELS_VIDEO_API, {"query": query, "per_page": 15,
                                           "orientation": orientation, "size": "medium"})
        except Exception:
            continue
        for video in data.get("videos", []):
            if video.get("id") in used_ids:
                continue
            if _too_similar(set(_slug_words(video.get("url", ""))), used_slugs):
                continue
            score = score_clip(video, scene)
            if score > best_score:
                best, best_score = video, score
        # A strong match on the first query means the later, looser queries
        # can only make the choice worse.
        if best_score >= 5.0:
            break

    return _describe(best, scene, orientation, best_score) if best else None


def _describe(picked: dict, scene: dict, orientation: str, score: float) -> dict | None:
    """One clip, in the shape the manifest stores."""
    chosen = pick_file(picked, vertical=(orientation == "portrait"))
    if not chosen:
        return None
    user = picked.get("user") or {}
    return {
        "sceneKey": scene["key"],
        "pexelsId": picked.get("id"),
        "sourceUrl": picked.get("url"),
        "credit": user.get("name") or "",
        "creditUrl": user.get("url") or "",
        "license": PEXELS_LICENCE,
        "duration": picked.get("duration"),
        "width": chosen.get("width"),
        "height": chosen.get("height"),
        "downloadUrl": chosen["link"],
        "posterUrl": picked.get("image"),
        "score": round(score, 1),
        "matchedWords": sorted(set(_slug_words(picked.get("url", ""))) & set(scene["want"])),
    }


def download(url: str, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response:
        data = response.read()
    destination.write_bytes(data)
    return len(data)


def load_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
