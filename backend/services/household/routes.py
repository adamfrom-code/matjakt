# -*- coding: utf-8 -*-
"""HTTP-lagret för hushållet: översätter vägar till anrop i lagret.

Ligger utanför api_server.py av två skäl. Det ena är att api_server redan är
3 000 rader if-satser. Det andra är viktigare: `handle()` är en ren funktion
av (metod, väg, payload, token) → (status, kropp), så hela behörighets- och
statusmodellen kan testas utan att någon startar en socket.

TRE REGLER SOM GÄLLER VARJE VÄG HÄR

1. household_id kommer ALDRIG från klienten. Det slås upp från sessionens
   användar-id (`_actor`). Det finns därför ingen parameter att manipulera -
   klassisk IDOR är omöjlig, inte bara osannolik.
2. NotAMemberError blir 404, inte 403. Ett 403 vore ett svar på frågan "finns
   det här hushållet?" som ingen utomstående ska få.
3. Sammansatta handlingar ("har hemma") görs i ETT anrop och svarar med både
   den ändrade listraden, skafferiraden och en ångra-beskrivning. Annars kan
   halva handlingen lyckas och lämna familjen med en vara som varken står i
   listan eller i skafferiet.
"""

from __future__ import annotations

import logging

from .notifications import PREF_ALL, PREFERENCES
from .store import (
    ALREADY_HAVE, HouseholdError, LOCATIONS, NEED_TO_BUY, NotAMemberError,
    PURCHASED, REMOVED,
)

logger = logging.getLogger("matjakt.household")

# Var köpta/hemmavarande varor hamnar när klienten inte säger något. Kyl är
# fel för pasta och skafferi fel för glass - därför gissar vi inte alls utan
# lägger i skafferiet, som är den plats användaren lättast flyttar ifrån.
DEFAULT_LOCATION = "skafferi"


class HouseholdRouter:
    def __init__(self, store, notifications, account_store, app_url="https://matjakt.store"):
        self.store = store
        self.notifications = notifications
        self.accounts = account_store
        self.app_url = (app_url or "").rstrip("/")

    # ---- identitet -------------------------------------------------------

    def _actor(self, token):
        """(user_id, e-post) för en levande session. Allt annat är 401."""
        identity = self.accounts.identity_for_token(token) if token else None
        if not identity:
            raise _Unauthorized()
        return identity

    def _household_id(self, user_id):
        household_id = self.store.household_id_for_user(user_id)
        if not household_id:
            raise _NoHousehold()
        return household_id

    def _actor_name(self, household_id, user_id, email=""):
        """Vad notisen ska kalla den som gjorde ändringen. Visningsnamnet om
        det finns, annars e-postens lokaldel - aldrig hela adressen, som inte
        hör hemma på någon annans låsskärm."""
        for member in self.store._members(household_id):
            if member["userId"] == user_id:
                if member["displayName"]:
                    return member["displayName"]
        local = str(email or "").split("@")[0]
        return local[:24] or None

    def _notify(self, household_id, actor_user_id, event_type, *, subject=None,
                actor_name=None, extra=None):
        """Händelse in i det gemensamma lagret + notiser ut till de andra.

        Fel här får ALDRIG välta skrivningen som redan lyckats: en trasig
        notis är ett irritationsmoment, en förlorad inköpsrad är ett fel."""
        try:
            self.store.record_event(household_id, actor_user_id, event_type,
                                    {"subject": subject} if subject else None)
            self.notifications.publish(
                event_type=event_type, household_id=household_id,
                actor_user_id=actor_user_id,
                recipient_ids=self.store.member_user_ids(household_id),
                actor_name=actor_name, subject=subject, extra=extra)
        except Exception:
            logger.exception("Kunde inte skapa notis för %s", event_type)

    # ---- dispatch --------------------------------------------------------

    def handle(self, method: str, path: str, query: dict, payload, token):
        try:
            return self._dispatch(method, path, query, payload, token)
        except _Unauthorized:
            return 401, {"error": "Du måste vara inloggad"}
        except _NoHousehold:
            return 404, {"error": "Du är inte med i något hushåll", "code": "NO_HOUSEHOLD"}
        except NotAMemberError:
            # Regel 2: samma svar som för ett hushåll som inte finns.
            return 404, {"error": "Hushållet finns inte"}
        except HouseholdError as error:
            return 400, {"error": str(error)}

    def _dispatch(self, method, path, query, payload, token):
        payload = payload if isinstance(payload, dict) else {}
        # Den ENDA vägen som inte kräver inloggning: landningssidan för en
        # inbjudan, som bara visar hushållets namn och vem som bjöd in.
        if method == "GET" and path == "/api/household/invite":
            return self._invite_preview(query)

        user_id, email = self._actor(token)

        if method == "GET":
            if path == "/api/household":
                return self._my_household(user_id, email)
            if path == "/api/household/sync":
                return self._sync(user_id, query)
            if path == "/api/household/notifications":
                return self._notifications(user_id)
            return 404, {"error": "Okänd väg"}

        if method != "POST":
            return 405, {"error": "Metoden stöds inte"}

        route = _POST_ROUTES.get(path)
        if not route:
            return 404, {"error": "Okänd väg"}
        return route(self, user_id, email, payload)

    # ---- läsning ---------------------------------------------------------

    def _my_household(self, user_id, email):
        household_id = self.store.household_id_for_user(user_id)
        if not household_id:
            return 200, {"household": None}
        return 200, {"household": self._household_payload(household_id, user_id)}

    def _household_payload(self, household_id, user_id):
        household = self.store.household_for(household_id, user_id)
        household["members"] = self._decorate_members(household["members"], user_id)
        return household

    def _decorate_members(self, members, user_id) -> list:
        """E-post och "det här är jag" läggs på HÄR, inte i lagret: hushålls-
        databasen ska inte kunna lämna ut en adress ens av misstag, och den
        här metoden nås bara efter att medlemskapet redan bevisats."""
        for member in members or []:
            try:
                member["email"] = self.accounts.email_for_user_id(member["userId"])
            except Exception:
                member["email"] = None
            member["isMe"] = member["userId"] == user_id
        return members or []

    def _sync(self, user_id, query):
        household_id = self._household_id(user_id)
        since = _int(_first(query, "since"), 0)
        payload = self.store.sync(household_id, user_id, since)
        # Medlemslistan berikas ÄVEN här, inte bara i den första hämtningen.
        # Utan detta skrev varje delta-sync över den berikade listan med
        # lagrets råa - och klienten tappade "det här är jag", varpå
        # "Ta bort medlem" dök upp bredvid ens eget namn.
        payload["members"] = self._decorate_members(payload["members"], user_id)
        if payload["household"] is not None:
            payload["household"] = self._household_payload(household_id, user_id)
        return 200, payload

    def _notifications(self, user_id):
        return 200, {
            "preferences": self.notifications.preferences(user_id),
            "notifications": self.notifications.due(user_id),
            "pending": self.notifications.pending_count(user_id),
        }

    # ---- hushåll ---------------------------------------------------------

    def _create(self, user_id, email, payload):
        household = self.store.create_household(user_id, payload.get("name"))
        self.store.set_profile(household["id"], user_id,
                               display_name=payload.get("displayName") or _local_part(email))
        return 201, {"household": self._household_payload(household["id"], user_id)}

    def _rename(self, user_id, email, payload):
        household_id = self._household_id(user_id)
        self.store.rename_household(household_id, user_id, payload.get("name"))
        return 200, {"household": self._household_payload(household_id, user_id)}

    def _profile(self, user_id, email, payload):
        household_id = self._household_id(user_id)
        self.store.set_profile(household_id, user_id,
                               display_name=payload.get("displayName"),
                               profile=payload.get("profile"))
        return 200, {"household": self._household_payload(household_id, user_id)}

    def _create_invite(self, user_id, email, payload):
        household_id = self._household_id(user_id)
        invite = self.store.create_invite(household_id, user_id)
        household = self.store.household_for(household_id, user_id)
        name = self._actor_name(household_id, user_id, email) or "Någon"
        # Färdig text att dela i SMS/WhatsApp - användaren ska inte behöva
        # formulera inbjudan själv (§1).
        url = f"{self.app_url}/?invite={invite['token']}"
        return 200, {
            "token": invite["token"],
            "url": url,
            "expiresAt": invite["expiresAt"],
            "shareTitle": f"Gå med i {household['name']} på Matjakt",
            "shareText": f"{name} har bjudit in dig till {household['name']} på Matjakt. Öppna länken så är du med: {url}",
        }

    def _revoke_invites(self, user_id, email, payload):
        household_id = self._household_id(user_id)
        return 200, {"revoked": self.store.revoke_invites(household_id, user_id)}

    def _invite_preview(self, query):
        token = _first(query, "token")
        if not token:
            return 400, {"error": "Ingen inbjudan angiven"}
        try:
            return 200, self.store.preview_invite(token)
        except HouseholdError as error:
            return 410, {"error": str(error), "code": "INVITE_INVALID"}

    def _join(self, user_id, email, payload):
        household = self.store.accept_invite(payload.get("token"), user_id)
        household_id = household["id"]
        name = payload.get("displayName") or _local_part(email)
        self.store.set_profile(household_id, user_id, display_name=name)
        self._notify(household_id, user_id, "household.member_joined", subject=name,
                     actor_name=name)
        return 200, {"household": self._household_payload(household_id, user_id)}

    def _leave(self, user_id, email, payload):
        household_id = self._household_id(user_id)
        self.store.leave(household_id, user_id)
        self.notifications.forget_household(user_id, household_id)
        return 200, {"household": None}

    def _remove_member(self, user_id, email, payload):
        household_id = self._household_id(user_id)
        target = _int(payload.get("userId"), 0)
        self.store.remove_member(household_id, user_id, target)
        self.notifications.forget_household(target, household_id)
        return 200, {"household": self._household_payload(household_id, user_id)}

    # ---- inköpslistan ----------------------------------------------------

    def _shopping_item(self, user_id, email, payload):
        household_id = self._household_id(user_id)
        item = self.store.upsert_shopping_item(household_id, user_id, payload)
        if payload.get("source") == "manual":
            self._notify(household_id, user_id, "household.shopping_item_added",
                         subject=item["name"], actor_name=self._actor_name(household_id, user_id, email))
        return 200, {"item": item, "revision": self.store.revision(household_id)}

    def _shopping_status(self, user_id, email, payload):
        household_id = self._household_id(user_id)
        status = payload.get("status")
        item = self.store.set_item_status(household_id, user_id, _ref(payload), status)
        if status == PURCHASED:
            self._notify(household_id, user_id, "household.shopping_item_purchased",
                         subject=item["name"], actor_name=self._actor_name(household_id, user_id, email))
        return 200, {"item": item, "revision": self.store.revision(household_id)}

    def _shopping_week(self, user_id, email, payload):
        household_id = self._household_id(user_id)
        items = payload.get("items")
        if not isinstance(items, list):
            return 400, {"error": "Ogiltig lista"}
        result = self.store.replace_week_items(household_id, user_id, items)
        return 200, result

    def _shopping_delete(self, user_id, email, payload):
        household_id = self._household_id(user_id)
        self.store.delete_shopping_item(household_id, user_id, _ref(payload))
        return 200, {"ok": True, "revision": self.store.revision(household_id)}

    def _at_home(self, user_id, email, payload):
        """"Har hemma" (§5) - ETT anrop, två effekter.

        Varan lämnar det aktiva behovet OCH hamnar i skafferiet. Svaret bär
        båda raderna plus en ångra-beskrivning, så knappen "Ångra" kan lämna
        tillbaka exakt det som ändrades - inte en gissning."""
        household_id = self._household_id(user_id)
        row = self.store._find_shopping_row(household_id, _ref(payload))
        if not row:
            return 400, {"error": "Varan finns inte i listan"}
        previous = row["status"]
        item = self.store.set_item_status(household_id, user_id, row["id"], ALREADY_HAVE)
        location = payload.get("location") if payload.get("location") in LOCATIONS else DEFAULT_LOCATION
        inventory, created = self._into_inventory(household_id, user_id, item, location, payload)
        self._notify(household_id, user_id, "household.shopping_item_at_home",
                     subject=item["name"], actor_name=self._actor_name(household_id, user_id, email))
        return 200, {
            "item": item,
            "inventory": inventory,
            "revision": self.store.revision(household_id),
            "undo": {"key": item["key"], "status": previous,
                     "inventoryKey": inventory.get("key") if created else None},
        }

    def _purchased(self, user_id, email, payload):
        """"Köpt" (§6). Skiljer sig från "har hemma" på en avgörande punkt:
        detta ÄR ett köp, och räknas som ett. Att lägga varan i kyl/frys/
        skafferi är valfritt och görs bara när klienten ber om det."""
        household_id = self._household_id(user_id)
        row = self.store._find_shopping_row(household_id, _ref(payload))
        if not row:
            return 400, {"error": "Varan finns inte i listan"}
        previous = row["status"]
        item = self.store.set_item_status(household_id, user_id, row["id"], PURCHASED)
        inventory, created = {}, False
        if payload.get("addToInventory"):
            location = payload.get("location") if payload.get("location") in LOCATIONS else DEFAULT_LOCATION
            inventory, created = self._into_inventory(household_id, user_id, item, location, payload)
        self._notify(household_id, user_id, "household.shopping_item_purchased",
                     subject=item["name"], actor_name=self._actor_name(household_id, user_id, email))
        return 200, {
            "item": item,
            "inventory": inventory,
            "revision": self.store.revision(household_id),
            "undo": {"key": item["key"], "status": previous,
                     "inventoryKey": inventory.get("key") if created else None},
        }

    def _into_inventory(self, household_id, user_id, item, location, payload):
        """Lägger listraden i skafferiet och säger om raden var NY.

        Nyhetsbeskedet är hela poängen med ångra: en vara som redan fanns
        hemma ska inte försvinna ur skafferiet bara för att någon ångrade
        sitt klick i Handla."""
        key = item["key"]
        existing = self.store._find_inventory_row(household_id, key)
        created = existing is None or bool(existing["deleted"])
        if not created:
            # Fanns redan hemma: plats, mängd, bäst före och kategori är
            # familjens uppgifter och skrivs inte över av ett klick i Handla
            # (granskningen 2026-09-07, P1-1). Bara revisionen bumpas.
            return self.store.touch_inventory_item(household_id, user_id, existing["id"]), False
        product = item.get("product") or {}
        entry = {
            "key": key,
            "name": product.get("productName") or item["name"],
            "location": location,
            # KONSERVATIVT (§11): vi vet att varan finns hemma, inte hur
            # mycket. En förpackning är det enda vi kan stå för; receptets
            # behov säger ingenting om vad som står i kylen.
            "amount": _number(payload.get("amount"), 1),
            "unit": payload.get("unit") or "st",
            "category": item.get("category"),
            "gtin": product.get("gtin"),
            "product": product or None,
        }
        return self.store.upsert_inventory_item(household_id, user_id, entry), created

    def _undo(self, user_id, email, payload):
        """Ångra en "har hemma"/"köpt". Statusen går tillbaka, och en
        skafferirad som SKAPADES av handlingen tas bort igen."""
        household_id = self._household_id(user_id)
        status = payload.get("status")
        if status not in (NEED_TO_BUY, ALREADY_HAVE, PURCHASED, REMOVED):
            status = NEED_TO_BUY
        item = self.store.set_item_status(household_id, user_id, _ref(payload), status)
        inventory_key = payload.get("inventoryKey")
        if inventory_key:
            try:
                self.store.remove_inventory_item(household_id, user_id, inventory_key)
            except HouseholdError:
                pass    # någon annan hann ta bort den - inget att ångra
        return 200, {"item": item, "revision": self.store.revision(household_id)}

    # ---- skafferi --------------------------------------------------------

    def _inventory_item(self, user_id, email, payload):
        household_id = self._household_id(user_id)
        item = self.store.upsert_inventory_item(household_id, user_id, payload)
        self._notify(household_id, user_id, "household.inventory_changed",
                     subject=item["name"], actor_name=self._actor_name(household_id, user_id, email))
        return 200, {"item": item, "revision": self.store.revision(household_id)}

    def _inventory_adjust(self, user_id, email, payload):
        household_id = self._household_id(user_id)
        item = self.store.adjust_inventory(household_id, user_id, _ref(payload),
                                           _number(payload.get("delta"), 0))
        return 200, {"item": item, "revision": self.store.revision(household_id)}

    def _inventory_remove(self, user_id, email, payload):
        household_id = self._household_id(user_id)
        item = self.store.remove_inventory_item(household_id, user_id, _ref(payload))
        return 200, {"item": item, "revision": self.store.revision(household_id)}

    # ---- delade dokument -------------------------------------------------

    def _doc(self, user_id, email, payload):
        household_id = self._household_id(user_id)
        doc = payload.get("doc")
        result = self.store.set_doc(household_id, user_id, doc, payload.get("body"))
        if doc == "week":
            event = "household.week_ready" if payload.get("ready") else "household.week_changed"
            self._notify(household_id, user_id, event,
                         subject=payload.get("subject") or "veckoplaneringen",
                         actor_name=self._actor_name(household_id, user_id, email),
                         extra={"summary": payload.get("summary")})
        return 200, result

    # ---- notiser ---------------------------------------------------------

    def _notification_prefs(self, user_id, email, payload):
        values = payload.get("preferences")
        if not isinstance(values, dict):
            values = {key: value for key, value in payload.items()
                      if key in PREFERENCES or key == PREF_ALL}
        return 200, {"preferences": self.notifications.set_preferences(user_id, values)}

    def _register_device(self, user_id, email, payload):
        try:
            self.notifications.register_device(user_id, payload.get("token"),
                                               payload.get("platform") or "web")
        except ValueError as error:
            return 400, {"error": str(error)}
        return 200, {"ok": True}

    def _forget_device(self, user_id, email, payload):
        self.notifications.forget_device(payload.get("token") or "", user_id=user_id)
        return 200, {"ok": True}


class _Unauthorized(Exception):
    pass


class _NoHousehold(Exception):
    pass


_POST_ROUTES = {
    "/api/household/create": HouseholdRouter._create,
    "/api/household/rename": HouseholdRouter._rename,
    "/api/household/profile": HouseholdRouter._profile,
    "/api/household/invite": HouseholdRouter._create_invite,
    "/api/household/invite/revoke": HouseholdRouter._revoke_invites,
    "/api/household/join": HouseholdRouter._join,
    "/api/household/leave": HouseholdRouter._leave,
    "/api/household/remove-member": HouseholdRouter._remove_member,
    "/api/household/shopping/item": HouseholdRouter._shopping_item,
    "/api/household/shopping/status": HouseholdRouter._shopping_status,
    "/api/household/shopping/week": HouseholdRouter._shopping_week,
    "/api/household/shopping/delete": HouseholdRouter._shopping_delete,
    "/api/household/shopping/at-home": HouseholdRouter._at_home,
    "/api/household/shopping/purchased": HouseholdRouter._purchased,
    "/api/household/shopping/undo": HouseholdRouter._undo,
    "/api/household/inventory/item": HouseholdRouter._inventory_item,
    "/api/household/inventory/adjust": HouseholdRouter._inventory_adjust,
    "/api/household/inventory/remove": HouseholdRouter._inventory_remove,
    "/api/household/doc": HouseholdRouter._doc,
    "/api/household/notifications/prefs": HouseholdRouter._notification_prefs,
    "/api/household/notifications/device": HouseholdRouter._register_device,
    "/api/household/notifications/device/forget": HouseholdRouter._forget_device,
}


def _first(query, name):
    values = (query or {}).get(name)
    if isinstance(values, (list, tuple)):
        return values[0] if values else None
    return values


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _number(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if number != number else number


def _ref(payload):
    """Vilken rad handlingen gäller: id eller nyckel. Båda slås ändå alltid
    upp inom hushållet, så ett id från ett annat hushåll ger ingen träff."""
    if payload.get("id") is not None:
        return _int(payload.get("id"), 0)
    return str(payload.get("key") or "")


def _local_part(email) -> str:
    """"adam@example.com" → "Adam". Ett vänligt förvalt visningsnamn som
    ingen behöver skriva in - men bara lokaldelen, aldrig hela adressen."""
    local = str(email or "").split("@")[0].strip()[:24]
    return local[:1].upper() + local[1:] if local else ""
