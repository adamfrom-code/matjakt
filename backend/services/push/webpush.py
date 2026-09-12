# -*- coding: utf-8 -*-
"""Web Push-avsändaren: RFC 8291 (aes128gcm) + RFC 8292 (VAPID).

DEN VIKTIGASTE EGENSKAPEN ÄR ATT DEN KAN TIGA.

Ett nyckelpar för VAPID är Adams, inte repots. Den privata halvan sätts i
Renders dashboard och får aldrig finnas i en spårad fil (se CLAUDE.md §3-4).
Utan nycklarna ska ingenting krascha och ingenting larma - notisen ska bara
utebli, och `blocked_reason()` ska kunna säga varför på svenska. Det är
därför hela modulen är byggd runt en fråga som besvaras innan något händer
i stället för ett undantag som kastas mitt i en söndagskörning.

NYCKLARNA
    MATJAKT_VAPID_PUBLIC_KEY    base64url, 65 byte okomprimerad P-256-punkt
    MATJAKT_VAPID_PRIVATE_KEY   base64url, 32 byte rå skalär
    MATJAKT_VAPID_SUBJECT       mailto:… eller https://… (vem tjänsten kan nå)
Exakt det `npx web-push generate-vapid-keys` skriver ut. Den publika halvan
går också till webbläsaren (den ÄR publik); den privata lämnar aldrig servern.

VAD SOM ÄR TESTBART UTAN BIBLIOTEK
Ramen, HKDF:en, JWT:ns osignerade del, publiken och rubrikerna är rena
funktioner av sina argument och prövas i backend/tests/test_sondagsnotis.py
mot RFC 5869:s och RFC 8291:s egna testvektorer. Bara tre steg behöver
riktig kryptografi - ECDH, AES-GCM och ES256-signaturen - och de ligger
samlade i `_primitives()` bakom en valfri import av `cryptography`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import struct
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from ..data_guard import guard_outbound_http

logger = logging.getLogger("matjakt.push")

# En söndagsnotis som inte nått fram till måndag morgon ska inte nå fram
# alls - den handlar om att planera veckan som börjar i morgon.
DEFAULT_TTL_SECONDS = 15 * 3600
JWT_LIFETIME_SECONDS = 12 * 3600
# Enda postens storlek. Notisen är under 300 byte; 4 096 är standardvalet
# och det som alla push-tjänster garanterat tar emot.
RECORD_SIZE = 4096
# Fallbacket när ingen annan adress är satt. En VAPID-sub ska vara något en
# push-tjänst kan höra av sig till om vi beter oss illa.
DEFAULT_SUBJECT = "https://matjakt.store"

MISSING_PUBLIC = "MATJAKT_VAPID_PUBLIC_KEY är inte satt"
MISSING_PRIVATE = "MATJAKT_VAPID_PRIVATE_KEY är inte satt"
MISSING_CRYPTO = "python-paketet cryptography saknas"


class WebPushError(Exception):
    """Avsändningen misslyckades. Notisen uteblir; ingenting annat händer."""


class WebPushGone(WebPushError):
    """404/410 från push-tjänsten: prenumerationen finns inte längre och
    ska bort ur databasen. Att fortsätta försöka varje söndag i all framtid
    är det enda sättet att göra en avinstallerad app till ett larm."""


# ---- små, rena byggstenar ---------------------------------------------------

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    raw = (value or "").strip()
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    """HKDF-SHA256, extract + expand (RFC 5869). Ren stdlib."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    okm = b""
    block = b""
    counter = 1
    while len(okm) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        okm += block
        counter += 1
    return okm[:length]


def vapid_audience(endpoint: str) -> str:
    """Publiken är push-tjänstens ursprung, aldrig hela endpointen - den
    senare innehåller mottagarens id och har inget i ett JWT att göra."""
    parts = urlsplit(endpoint or "")
    if parts.scheme != "https" or not parts.netloc:
        raise ValueError("Ogiltig push-endpoint")
    return f"{parts.scheme}://{parts.netloc}"


def vapid_claims(endpoint: str, subject: str, now: int) -> dict:
    return {"aud": vapid_audience(endpoint), "exp": int(now) + JWT_LIFETIME_SECONDS,
            "sub": subject or DEFAULT_SUBJECT}


def jwt_signing_input(claims: dict) -> bytes:
    header = {"typ": "JWT", "alg": "ES256"}
    encode = lambda part: b64url(json.dumps(part, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{encode(header)}.{encode(claims)}".encode("ascii")


def authorization_header(signing_input: bytes, signature: bytes, public_key: str) -> str:
    return f"vapid t={signing_input.decode('ascii')}.{b64url(signature)}, k={public_key}"


def aes128gcm_body(salt: bytes, server_public: bytes, ciphertext: bytes,
                   record_size: int = RECORD_SIZE) -> bytes:
    """Ramen runt det krypterade (RFC 8188 §2.1):

        salt(16) | rs(4, big-endian) | idlen(1) | avsändarens nyckel(65) | chiffer
    """
    if len(salt) != 16:
        raise ValueError("salt ska vara 16 byte")
    return salt + struct.pack("!I", record_size) + bytes([len(server_public)]) + server_public + ciphertext


def content_keys(salt: bytes, ecdh_secret: bytes, auth_secret: bytes,
                 ua_public: bytes, server_public: bytes) -> tuple[bytes, bytes]:
    """(CEK, NONCE) enligt RFC 8291 §3.4. Ren stdlib - ECDH-hemligheten är
    det enda som behövde ett bibliotek, och den skickas in."""
    key_info = b"WebPush: info\x00" + ua_public + server_public
    ikm = hkdf(auth_secret, ecdh_secret, key_info, 32)
    cek = hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    return cek, nonce


def _primitives():  # pragma: no cover - beror på en valfri import
    """De tre stegen som inte går att göra i stdlib. Saknas biblioteket är
    det ett `blocked_reason`, inte ett undantag - se klassen nedan."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return ec, AESGCM, hashes, serialization, decode_dss_signature


def crypto_available() -> bool:
    try:
        _primitives()
    except Exception:
        return False
    return True


# ---- avsändaren -------------------------------------------------------------

class WebPushSender:
    """Skickar ETT krypterat meddelande till EN prenumeration.

    `opener(request)` finns för testernas skull och är urlopen i drift.
    Repots sjunde absoluta förbud - ingen riktig utgående trafik i tester -
    är hela anledningen till att den är ett argument och inte en import.

    Men ett argument räcker inte som spärr, och test_db_guard säger varför:
    ett test som GLÖMMER att skicka in sin opener får den äkta urlopen, och
    då är förbudet bara en vana. Standardöppnaren går därför genom
    guard_outbound_http() precis som varje annan utgående väg i services/ -
    en glömd mock blir ett fel i testet i stället för ett paket på nätet."""

    def __init__(self, public_key: str = "", private_key: str = "",
                 subject: str = DEFAULT_SUBJECT, opener=None, timeout: float = 10.0):
        self.public_key = (public_key or "").strip()
        self.private_key = (private_key or "").strip()
        self.subject = (subject or DEFAULT_SUBJECT).strip()
        self.timeout = timeout
        self._opener = opener or self._guarded_urlopen

    def _guarded_urlopen(self, request):
        """urlopen som vägrar under en testkörning - se services/data_guard."""
        guard_outbound_http("Web Push")
        return urllib.request.urlopen(request, timeout=self.timeout)

    @classmethod
    def from_env(cls, env=None, opener=None) -> "WebPushSender":
        env = os.environ if env is None else env
        return cls(public_key=env.get("MATJAKT_VAPID_PUBLIC_KEY", ""),
                   private_key=env.get("MATJAKT_VAPID_PRIVATE_KEY", ""),
                   subject=env.get("MATJAKT_VAPID_SUBJECT", "") or DEFAULT_SUBJECT,
                   opener=opener)

    def blocked_reason(self):
        """Varför ingenting kan skickas - eller None när allt finns.

        Ordningen är avsiktlig: den publika nyckeln först, för det är den
        klienten också behöver för att ens kunna prenumerera. Saknas den har
        ingen användare någon prenumeration att skicka till heller."""
        if not self.public_key:
            return MISSING_PUBLIC
        if not self.private_key:
            return MISSING_PRIVATE
        if not crypto_available():
            return MISSING_CRYPTO
        return None

    def configured(self) -> bool:
        return self.blocked_reason() is None

    # -- kryptering --
    def encrypt(self, p256dh: str, auth: str, payload: bytes, *, salt=None,
                server_key=None) -> bytes:  # pragma: no cover - kräver cryptography
        ec, AESGCM, _hashes, serialization, _decode = _primitives()
        ua_public = b64url_decode(p256dh)
        auth_secret = b64url_decode(auth)
        server_key = server_key or ec.generate_private_key(ec.SECP256R1())
        server_public = server_key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        ecdh_secret = server_key.exchange(
            ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
        salt = salt or os.urandom(16)
        cek, nonce = content_keys(salt, ecdh_secret, auth_secret, ua_public, server_public)
        # 0x02 är avgränsaren för SISTA posten (RFC 8188 §2). Notisen får
        # plats i en post, så det finns bara en sista.
        ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
        return aes128gcm_body(salt, server_public, ciphertext)

    def _signature(self, signing_input: bytes) -> bytes:  # pragma: no cover - kräver cryptography
        ec, _AESGCM, hashes, _serialization, decode_dss_signature = _primitives()
        scalar = int.from_bytes(b64url_decode(self.private_key), "big")
        key = ec.derive_private_key(scalar, ec.SECP256R1())
        r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
        # ES256 vill ha r||s som 64 råa byte, inte DER.
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")

    def headers(self, endpoint: str, body_length: int, ttl: int, now: int) -> dict:  # pragma: no cover
        claims = vapid_claims(endpoint, self.subject, now)
        signing_input = jwt_signing_input(claims)
        return {
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "Content-Length": str(body_length),
            "TTL": str(int(ttl)),
            "Urgency": "normal",
            "Authorization": authorization_header(signing_input, self._signature(signing_input),
                                                  self.public_key),
        }

    # -- avsändning --
    def deliver(self, endpoint: str, body: bytes, headers: dict) -> int:
        """POSTen och ingenting annat - skild från krypteringen med flit, så
        felöversättningen (404/410 = borta, allt annat = uteblivet) går att
        pröva utan ett nyckelpar och utan ett enda riktigt paket på nätet."""
        request = urllib.request.Request(endpoint, data=body, method="POST", headers=headers)
        try:
            with self._opener(request) as response:
                return int(getattr(response, "status", 0) or 0)
        except urllib.error.HTTPError as error:
            if error.code in (404, 410):
                raise WebPushGone(f"Prenumerationen finns inte längre ({error.code})") from error
            raise WebPushError(f"Push-tjänsten svarade {error.code}") from error
        except WebPushError:
            raise
        except Exception as error:
            raise WebPushError(str(error)) from error

    def send(self, subscription: dict, payload, *, ttl: int = DEFAULT_TTL_SECONDS,
             now=None) -> int:
        reason = self.blocked_reason()
        if reason:
            raise WebPushError(reason)
        endpoint = str((subscription or {}).get("endpoint") or "")
        keys = subscription.get("keys") if isinstance(subscription.get("keys"), dict) else subscription
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        body = self.encrypt(str(keys.get("p256dh") or ""), str(keys.get("auth") or ""), data)
        headers = self.headers(endpoint, len(body), ttl,
                               int(now if now is not None else time.time()))
        return self.deliver(endpoint, body, headers)
