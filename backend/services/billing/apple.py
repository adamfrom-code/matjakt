# -*- coding: utf-8 -*-
"""Apple In-App Purchase på servern: notiserna, appens köpanmälan och vad
de betyder för kontot. (P02c)

Bakom flaggan MATJAKT_APPLE_IAP - av som standard. Två vägar in:

* App Store Server Notifications V2 (`POST /api/billing/apple/notifications`):
  Apple säger vad som hänt med en prenumeration. Kroppen är
  `{"signedPayload": <JWS>}`, JWS:en verifieras mot Apple Root CA - G3
  (services/billing/apple_jws.py), och payloadens `notificationType`
  avgör tillståndet. Idempotent på `notificationUUID` - Apple: "Use this
  value to identify a duplicate notification."
* Appens egen anmälan (`POST /api/billing/apple/transaction`): StoreKit 2
  lämnar ut samma sorts JWS för en transaktion (`jwsRepresentation`), och
  appen skickar in den efter ett köp eller "Återställ köp". Samma
  verifierare; dessutom ska transaktionens `appAccountToken` vara det
  inloggade kontots, annars kan en JWS från en annan telefon inte ge
  Premium här.

KOPPLINGEN KONTO <-> APPLE-KUND är `appAccountToken`: ett UUID v5 som
härleds ur konto-id:t med en fast namnrymd. Appen skickar med det i köpet,
Apple bär det i varje transaktion och notis. Apple ger oss aldrig kundens
e-post; token är den enda vägen tillbaka, och den är deterministisk så
att servern kan räkna ut den för vilket konto som helst utan att lagra
något. Ingen hemlighet ingår: att kunna gissa någon annans token ger bara
möjligheten att betala för hennes Premium.

TILLSTÅNDEN skrivs med AccountStore.apply_apple_subscription (P02b), i
vår vokabulär: active, grace, billing_retry, expired, revoked. Tabellen i
`docs/IAP_COMPLIANCE.md` (C2) är facit; `state_from()` är dess kod.
Transaktionsinfon är sanningen om produkt och slutdatum; notistypen
avgör bara statusen. Informativa notiser (auto-förnyelse av/på, byte av
plan inför nästa period, prishöjning) behåller den status kontot redan
har.

REGLERNA FRÅN STRIPE-WEBHOOKEN GÄLLER (B1, J5): okänd kund förbrukar inte
UUID:t och besvaras 500, så Apple försöker igen - "at 1, 12, 24, 48, and
72 hours after the previous attempt" - och under tiden hinner appens
anmälan binda transaktionen till kontot. Sandbox-notiser appliceras bara
när MATJAKT_APPLE_IAP_ACCEPT_SANDBOX är satt (staging); i produktion
kvitteras de utan åtgärd, så ett sandbox-köp aldrig ger riktigt Premium.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .apple_jws import TRUSTED_ROOTS, AppleJwsError, verify_jws

logger = logging.getLogger("matjakt.billing.apple")

#: Bundle-id:t appen bär (capacitor.config.json / Xcode). Konstant, inte
#: konfiguration: byts det är det en ny app i App Store Connect.
BUNDLE_ID = "se.matjakt.app"

# Namnrymden för appAccountToken. Ett fast, publikt värde - poängen är
# determinism, inte hemlighet (se modulens docstring).
APP_ACCOUNT_TOKEN_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://matjakt.store/apple/appAccountToken")

# Notistyper -> vår status. None = informativ: behåll kontots nuvarande
# status, uppdatera bara det transaktionen säger.
STATUS_BY_TYPE = {
    "SUBSCRIBED": "active",
    "DID_RENEW": "active",
    "REFUND_REVERSED": "active",
    "EXPIRED": "expired",
    "GRACE_PERIOD_EXPIRED": "billing_retry",
    "REFUND": "revoked",
    "REVOKE": "revoked",
    "DID_CHANGE_RENEWAL_STATUS": None,
    "DID_CHANGE_RENEWAL_PREF": None,
    "OFFER_REDEEMED": None,
    "PRICE_INCREASE": None,
    "RENEWAL_EXTENDED": None,
}
# DID_FAIL_TO_RENEW beror på subtypen: med GRACE_PERIOD fortsätter Premium
# ("continue to provide service through the grace period"), utan slutar det
# ("you can stop providing the subscription service").
HANDLED_TYPES = frozenset(STATUS_BY_TYPE) | {"DID_FAIL_TO_RENEW"}


class AppleIapError(Exception):
    """Fel som får visas för anroparen (400)."""


@dataclass(frozen=True)
class AppleIapConfig:
    enabled: bool = False
    bundle_id: str = BUNDLE_ID
    app_apple_id: str | None = None          # numeriskt Apple ID som sträng, eller None
    accept_sandbox: bool = False
    trusted_roots: tuple = TRUSTED_ROOTS
    products: dict = field(default_factory=dict)   # {"monthly": produkt-id, "yearly": produkt-id}

    @staticmethod
    def from_env(environ, products=None) -> "AppleIapConfig":
        """Konfigurationen ur miljön. Produkt-id:na kommer ur
        features.PRICING - samma strängar som dokumentet och App Store
        Connect - om inget annat skickas in (tester)."""
        truthy = {"1", "true", "yes", "on"}
        if products is None:
            from ..accounts import features
            products = {plan: entry["storekitProductId"] for plan, entry in features.PRICING.items()}
        return AppleIapConfig(
            enabled=str(environ.get("MATJAKT_APPLE_IAP", "")).strip().lower() in truthy,
            app_apple_id=(str(environ.get("MATJAKT_APPLE_APP_ID", "")).strip() or None),
            accept_sandbox=str(environ.get("MATJAKT_APPLE_IAP_ACCEPT_SANDBOX", "")).strip().lower() in truthy,
            products=dict(products),
        )


def app_account_token(user_id) -> str:
    """Kontots appAccountToken - UUID v5, deterministiskt, gemener."""
    return str(uuid.uuid5(APP_ACCOUNT_TOKEN_NAMESPACE, str(int(user_id))))


def _ms_to_iso(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _now_ms(now=None) -> int:
    moment = now() if now else datetime.now(timezone.utc)
    return int(moment.timestamp() * 1000)


# ---- avkodning ----------------------------------------------------------------

@dataclass
class Notification:
    type: str
    subtype: str | None
    uuid: str | None
    signed_date: int | None            # ms
    environment: str | None
    bundle_id: str | None
    app_apple_id: str | None
    transaction: dict | None
    renewal: dict | None
    version: str | None


def decode_notification(signed_payload: str, config: AppleIapConfig, *, now=None) -> Notification:
    """Verifierar det yttre JWS:et OCH de inre (signedTransactionInfo,
    signedRenewalInfo) - var och en bär sin egen x5c-kedja - och plockar ut
    det handlaren behöver. Kastar AppleJwsError/AppleIapError."""
    if not isinstance(signed_payload, str) or not signed_payload:
        raise AppleIapError("signedPayload saknas")
    payload = verify_jws(signed_payload, trusted_roots=config.trusted_roots, now=now)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    transaction = renewal = None
    if isinstance(data.get("signedTransactionInfo"), str):
        transaction = verify_jws(data["signedTransactionInfo"], trusted_roots=config.trusted_roots, now=now)
    if isinstance(data.get("signedRenewalInfo"), str):
        renewal = verify_jws(data["signedRenewalInfo"], trusted_roots=config.trusted_roots, now=now)
    app_apple_id = data.get("appAppleId")
    return Notification(
        type=str(payload.get("notificationType") or ""),
        subtype=(str(payload["subtype"]) if payload.get("subtype") else None),
        uuid=(str(payload["notificationUUID"]) if payload.get("notificationUUID") else None),
        signed_date=(int(payload["signedDate"]) if isinstance(payload.get("signedDate"), (int, float))
                     and not isinstance(payload.get("signedDate"), bool) else None),
        environment=(data.get("environment") or (transaction or {}).get("environment")),
        bundle_id=(data.get("bundleId") or (transaction or {}).get("bundleId")),
        app_apple_id=(str(app_apple_id) if app_apple_id is not None else None),
        transaction=transaction, renewal=renewal,
        version=payload.get("version"),
    )


def check_app(config: AppleIapConfig, *, bundle_id, environment, app_apple_id=None) -> str | None:
    """Hör den här datan till VÅR app, i en miljö vi godtar? Returnerar
    None när allt stämmer, annars en orsak: "wrong_bundle", "wrong_app",
    "sandbox_ignored" eller "unknown_environment"."""
    if bundle_id != config.bundle_id:
        return "wrong_bundle"
    if environment == "Sandbox":
        if not config.accept_sandbox:
            return "sandbox_ignored"
    elif environment != "Production":
        return "unknown_environment"
    # appAppleId finns bara i produktion ("It isn't present in the sandbox
    # environment") och prövas bara när Adam skrivit in det.
    if (config.app_apple_id and environment == "Production" and app_apple_id is not None
            and str(app_apple_id) != str(config.app_apple_id)):
        return "wrong_app"
    return None


# ---- tillståndet -----------------------------------------------------------------

@dataclass(frozen=True)
class AppleState:
    status: str | None                 # None = behåll kontots nuvarande
    original_transaction_id: str | None
    product_id: str | None
    expires_at_iso: str | None
    auto_renew: bool | None
    environment: str | None
    signed_date: int | None


def state_from(notification: Notification) -> AppleState | None:
    """Vad notisen betyder för kontot, eller None när typen inte rör
    prenumerationens tillstånd (TEST, CONSUMPTION_REQUEST, ...)."""
    kind = notification.type
    if kind not in HANDLED_TYPES:
        return None
    tx = notification.transaction or {}
    renewal = notification.renewal or {}
    if kind == "DID_FAIL_TO_RENEW":
        status = "grace" if notification.subtype == "GRACE_PERIOD" else "billing_retry"
    else:
        status = STATUS_BY_TYPE[kind]
    expires = _ms_to_iso(tx.get("expiresDate"))
    grace_until = _ms_to_iso(renewal.get("gracePeriodExpiresDate"))
    if status == "grace" and grace_until:
        expires = max(filter(None, (expires, grace_until)))
    if status == "revoked":
        expires = _ms_to_iso(tx.get("revocationDate")) or _ms_to_iso(notification.signed_date) or expires
    auto_renew = renewal.get("autoRenewStatus")
    return AppleState(
        status=status,
        original_transaction_id=(str(tx["originalTransactionId"]) if tx.get("originalTransactionId") else None),
        product_id=(str(tx["productId"]) if tx.get("productId") else None),
        expires_at_iso=expires,
        auto_renew=(bool(auto_renew) if isinstance(auto_renew, int) and not isinstance(auto_renew, bool)
                    else (auto_renew if isinstance(auto_renew, bool) else None)),
        environment=notification.environment,
        signed_date=notification.signed_date,
    )


def state_from_transaction(tx: dict, *, now=None) -> AppleState:
    """Tillståndet ur en ensam transaktions-JWS (appens anmälan). Ingen
    notistyp att gå på: återkallad om revocationDate finns, annars aktiv
    så länge slutdatumet ligger framför oss."""
    expires_ms = tx.get("expiresDate")
    if tx.get("revocationDate"):
        status, expires = "revoked", _ms_to_iso(tx.get("revocationDate"))
    elif isinstance(expires_ms, (int, float)) and not isinstance(expires_ms, bool):
        status, expires = ("active" if expires_ms > _now_ms(now) else "expired"), _ms_to_iso(expires_ms)
    else:
        raise AppleIapError("transaktionen saknar slutdatum")
    signed = tx.get("signedDate")
    return AppleState(
        status=status,
        original_transaction_id=(str(tx["originalTransactionId"]) if tx.get("originalTransactionId") else None),
        product_id=(str(tx["productId"]) if tx.get("productId") else None),
        expires_at_iso=expires, auto_renew=None, environment=tx.get("environment"),
        signed_date=(int(signed) if isinstance(signed, (int, float)) and not isinstance(signed, bool) else None),
    )


# ---- idempotens ---------------------------------------------------------------------

class AppleNotificationStore:
    """notificationUUID -> mottagen. Delar anslutning och lås med
    AccountStore av samma skäl som PremiumCodeStore: markeringen och
    tillståndsändringen ska ligga i SAMMA transaktion, så att en halvvägs
    misslyckad leverans får köra om utan att något dubbleras."""

    def __init__(self, connection: sqlite3.Connection, lock=None):
        self._connection = connection
        self._lock = lock if lock is not None else threading.RLock()
        self._init_schema()

    def _init_schema(self):
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS apple_notifications (
                    notification_uuid TEXT PRIMARY KEY,
                    notification_type TEXT,
                    subtype TEXT,
                    signed_date INTEGER,
                    original_transaction_id TEXT,
                    user_id INTEGER,
                    outcome TEXT,
                    received_at TEXT NOT NULL
                );
                """
            )
            self._connection.commit()

    def begin(self, notification: Notification) -> bool:
        """Markerar UUID:t - UTAN commit. False = redan sedd. Anroparen
        committar (via apply_apple_subscription) eller rullar tillbaka."""
        if not notification.uuid:
            return True         # utan UUID finns inget att deduplicera på
        cursor = self._connection.execute(
            """INSERT OR IGNORE INTO apple_notifications
               (notification_uuid, notification_type, subtype, signed_date, received_at)
               VALUES (?, ?, ?, ?, ?)""",
            (notification.uuid, notification.type, notification.subtype, notification.signed_date,
             datetime.now(timezone.utc).isoformat()))
        return cursor.rowcount > 0

    def finish(self, notification: Notification, *, user_id, original_transaction_id, outcome) -> None:
        if not notification.uuid:
            return
        self._connection.execute(
            """UPDATE apple_notifications SET user_id = ?, original_transaction_id = ?, outcome = ?
               WHERE notification_uuid = ?""",
            (user_id, original_transaction_id, outcome, notification.uuid))

    def seen(self, notification_uuid) -> dict | None:
        row = self._connection.execute(
            "SELECT * FROM apple_notifications WHERE notification_uuid = ?", (str(notification_uuid),)).fetchone()
        return dict(row) if row else None

    def count(self) -> int:
        return int(self._connection.execute("SELECT COUNT(*) FROM apple_notifications").fetchone()[0])


# ---- vem hör transaktionen till? ---------------------------------------------------

def find_user(accounts, *, original_transaction_id, app_account_token_value) -> int | None:
    """Kontot bakom en transaktion: originalTransactionId först (kontot har
    redan bundits), sedan appAccountToken - deterministiskt, så det räknas
    ut för varje konto i stället för att slås upp. Billigt på vår skala,
    och den dagen det inte är det får kolumnen ett index."""
    user_id = accounts.user_id_for_apple_transaction(original_transaction_id)
    if user_id:
        return user_id
    token = str(app_account_token_value or "").strip().lower()
    if not token:
        return None
    for (candidate,) in accounts.connection.execute("SELECT id FROM users"):
        if app_account_token(candidate) == token:
            return int(candidate)
    return None


# ---- hanteringen ----------------------------------------------------------------------

def handle_notification(accounts, notifications: AppleNotificationStore, signed_payload,
                        config: AppleIapConfig, *, now=None) -> dict:
    """Hela vägen för en notis. Returnerar {"outcome": ..., ...}; outcome:

      applied           tillståndet skrevs
      ignored           äldre än det senast applicerade (eller inget att ändra)
      duplicate         notificationUUID redan behandlat
      unhandled         typ vi inte agerar på (TEST m.fl.) - kvitteras
      sandbox_ignored   sandbox-notis i produktion - kvitteras
      unknown_customer  ingen kundrad - anroparen svarar 500 så Apple försöker igen

    Kastar AppleJwsError/AppleIapError när datan inte går att lita på
    (anroparen svarar 400)."""
    notification = decode_notification(signed_payload, config, now=now)
    reason = check_app(config, bundle_id=notification.bundle_id, environment=notification.environment,
                       app_apple_id=notification.app_apple_id)
    if reason in ("wrong_bundle", "wrong_app", "unknown_environment"):
        raise AppleIapError(f"notisen hör inte till den här appen ({reason})")
    base = {"type": notification.type, "subtype": notification.subtype, "uuid": notification.uuid}
    if reason == "sandbox_ignored":
        return {**base, "outcome": "sandbox_ignored"}
    state = state_from(notification)
    if state is None:
        return {**base, "outcome": "unhandled"}
    tx = notification.transaction or {}
    with accounts.lock:
        try:
            if not notifications.begin(notification):
                accounts.connection.rollback()
                return {**base, "outcome": "duplicate"}
            user_id = find_user(accounts, original_transaction_id=state.original_transaction_id,
                                app_account_token_value=tx.get("appAccountToken"))
            if user_id is None:
                # ROLLBACK, inte commit: UUID:t får inte förbrukas av en
                # händelse som ingenting ändrade (B1:s regel).
                accounts.connection.rollback()
                return {**base, "outcome": "unknown_customer"}
            status = state.status
            if status is None:
                current = accounts.apple_subscription(user_id)
                status = (current or {}).get("apple_status") or "active"
            outcome = accounts.apply_apple_subscription(
                user_id, original_transaction_id=state.original_transaction_id, product_id=state.product_id,
                expires_at_iso=state.expires_at_iso, status=status, auto_renew=state.auto_renew,
                environment=state.environment, signed_date=state.signed_date)
            # apply_apple_subscription committade (även vid "ignored") - och
            # tog markeringen med sig. Avslutningen skrivs i en egen liten
            # commit; faller den är händelsen ändå kvitterad och applicerad.
            notifications.finish(notification, user_id=user_id,
                                 original_transaction_id=state.original_transaction_id, outcome=outcome)
            accounts.connection.commit()
            return {**base, "outcome": outcome, "userId": user_id}
        except Exception:
            accounts.connection.rollback()
            raise


def bind_transaction(accounts, user_id, jws, config: AppleIapConfig, *, now=None) -> dict:
    """Appens anmälan av ett köp eller en återställning: transaktionens JWS
    från StoreKit 2. Binder transaktionen till DET INLOGGADE kontot - och
    bara om transaktionens appAccountToken är kontots (eller saknas och
    ingen annan redan äger transaktionen)."""
    if not isinstance(jws, str) or not jws:
        raise AppleIapError("transaktionen saknas")
    tx = verify_jws(jws, trusted_roots=config.trusted_roots, now=now)
    reason = check_app(config, bundle_id=tx.get("bundleId"), environment=tx.get("environment"))
    if reason == "sandbox_ignored":
        raise AppleIapError("sandbox-köp godtas inte i den här miljön")
    if reason:
        raise AppleIapError(f"transaktionen hör inte till den här appen ({reason})")
    if tx.get("type") not in (None, "Auto-Renewable Subscription"):
        raise AppleIapError("transaktionen är inte en prenumeration")
    expected = app_account_token(user_id)
    token = str(tx.get("appAccountToken") or "").strip().lower()
    if token and token != expected:
        raise AppleIapError("köpet hör till ett annat Matjakt-konto")
    state = state_from_transaction(tx, now=now)
    owner = accounts.user_id_for_apple_transaction(state.original_transaction_id)
    if owner is not None and owner != int(user_id):
        raise AppleIapError("köpet hör till ett annat Matjakt-konto")
    outcome = accounts.apply_apple_subscription(
        user_id, original_transaction_id=state.original_transaction_id, product_id=state.product_id,
        expires_at_iso=state.expires_at_iso, status=state.status, auto_renew=None,
        environment=state.environment, signed_date=state.signed_date)
    return {"outcome": outcome, "status": state.status, "productId": state.product_id,
            "expiresAt": state.expires_at_iso}


def entitlement_block(config: AppleIapConfig, user_id=None) -> dict:
    """Det /api/entitlements säger om Apple: av, eller på med produkt-id:n
    och - för en inloggad - kontots appAccountToken."""
    if not config.enabled:
        return {"enabled": False}
    block = {"enabled": True, "products": dict(config.products)}
    if user_id:
        block["appAccountToken"] = app_account_token(user_id)
    return block


__all__ = ["AppleIapConfig", "AppleIapError", "AppleJwsError", "AppleNotificationStore", "BUNDLE_ID",
           "HANDLED_TYPES", "app_account_token", "bind_transaction", "check_app", "decode_notification",
           "entitlement_block", "find_user", "handle_notification", "state_from", "state_from_transaction"]
