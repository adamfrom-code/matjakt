# -*- coding: utf-8 -*-
"""Verifiering av Apples signerade data - JWS med x5c-kedja - i ren Python.

App Store Server Notifications V2 och StoreKit 2:s transaktioner kommer som
JWS (RFC 7515): `<huvud>.<payload>.<signatur>`, där huvudet bär `alg: ES256`
och `x5c`, en kedja av tre certifikat - löv, mellanliggande, rot. Roten ska
vara **Apple Root CA - G3**. Allt annat är vem som helst som skriver JSON.

VARFÖR REN PYTHON. `backend/requirements.txt` är hash-låst (K2) och saknar
ett kryptobibliotek; `stripe_client.py` är stdlib av samma skäl, och
`IOS_RELEASE.md` pekade ut valet redan innan paketet fanns. Verifiering av
ECDSA behöver ingen konstanttidsaritmetik - ingen hemlighet finns på vår
sida, bara Apples publika nycklar - så en rak implementation av kort
Weierstrass-form över P-256 och P-384 räcker. Samma kod, två
parameteruppsättningar: lövet signerar JWS:en med P-256/SHA-256 (ES256),
Apples mellanliggande och rot signerar certifikaten med P-384/SHA-384.

VAD SOM KONTROLLERAS, i samma ordning som Apples eget referensbibliotek
(app-store-server-library-python, `signed_data_verifier.py`):

  1. `x5c` bär exakt tre certifikat. Färre eller fler avvisas.
  2. Roten är byte för byte ett av de betrodda rotcertifikaten - i drift
     bara Apple Root CA - G3, som ligger inbäddad nedan. Det är ett
     publikt certifikat, inte en hemlighet; fingeravtrycket står bredvid.
  3. Varje länk: utfärdaren stämmer, signaturen verifieras med förälderns
     nyckel, och giltighetstiden täcker payloadens `signedDate`.
  4. Mellanliggande bär OID 1.2.840.113635.100.6.2.1 (Apple WWDR CA),
     lövet OID 1.2.840.113635.100.6.11.1 (App Store-signering).
  5. JWS-signaturen verifieras med lövets nyckel över `<huvud>.<payload>`.

Vad som INTE görs, med avsikt: OCSP (Apples bibliotek gör det som tillval
och mot nätet; vi gör inga nätanrop i den här vägen), och rotens egen
självsignatur (roten är förtroendeankaret, inte något som bevisas).

HUR DET ÄR BEVISAT. `tests/test_apple_jws.py` kör (a) signaturer gjorda av
OpenSSL med nycklar det aldrig sett i den här koden, (b) Apples riktiga
WWDR G6-certifikat verifierat mot den riktiga roten - ett P-384-bevis på
verklig data, och (c) hela kedjor och JWS:er byggda med en egen signerare
och DER-kodare i testet. Ingen skip, inget nät.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone


class AppleJwsError(Exception):
    """Signerad data som inte går att lita på. Anroparen svarar 400."""


# ---- kurvorna -----------------------------------------------------------

@dataclass(frozen=True)
class Curve:
    name: str
    p: int
    a: int
    b: int
    gx: int
    gy: int
    n: int
    size: int   # byte per koordinat

    @property
    def g(self):
        return (self.gx, self.gy)


# NIST P-256 (secp256r1, prime256v1) och P-384 (secp384r1), FIPS 186-4.
P256 = Curve(
    "P-256",
    p=0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff,
    a=0xffffffff00000001000000000000000000000000fffffffffffffffffffffffc,
    b=0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b,
    gx=0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
    gy=0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5,
    n=0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551,
    size=32)
P384 = Curve(
    "P-384",
    p=0xfffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffeffffffff0000000000000000ffffffff,
    a=0xfffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffeffffffff0000000000000000fffffffc,
    b=0xb3312fa7e23ee7e4988e056be3f82d19181d9c6efe8141120314088f5013875ac656398d8a2ed19d2a85c8edd3ec2aef,
    gx=0xaa87ca22be8b05378eb1c71ef320ad746e1d3b628ba79b9859f741e082542a385502f25dbf55296c3a545e3872760ab7,
    gy=0x3617de4a96262c6f5d9e98bf9292dc29f8f41dbd289a147ce9da3113b5f0b8c00a60b1ce1d7e819d7a431d7c90ea0e5f,
    n=0xffffffffffffffffffffffffffffffffffffffffffffffffc7634d81f4372ddf581a0db248b0a77aecec196accc52973,
    size=48)

OID_EC_PUBLIC_KEY = "1.2.840.10045.2.1"
CURVE_BY_OID = {"1.2.840.10045.3.1.7": P256, "1.3.132.0.34": P384}
HASH_BY_SIGNATURE_OID = {
    "1.2.840.10045.4.3.2": "sha256",   # ecdsa-with-SHA256
    "1.2.840.10045.4.3.3": "sha384",   # ecdsa-with-SHA384
    "1.2.840.10045.4.3.4": "sha512",   # ecdsa-with-SHA512
}
# Apples egna tillägg. Mellanliggande CA respektive App Store-signering -
# samma två som Apples referensbibliotek kräver.
OID_APPLE_WWDR_CA = "1.2.840.113635.100.6.2.1"
OID_APPLE_RECEIPT_SIGNING = "1.2.840.113635.100.6.11.1"

# Apple Root CA - G3, DER. Publikt: https://www.apple.com/certificateauthority/
# SHA-256: 63:34:3A:BF:B8:9A:6A:03:EB:B5:7E:9B:3F:5F:A7:BE:7C:4F:5C:75:6F:30:17:B3:A8:C4:88:C3:65:3E:91:79
# CN=Apple Root CA - G3, P-384, giltigt 2014-04-30 - 2039-04-30. Testet
# `test_apple_jws.py` jämför bytena mot fingeravtrycket.
APPLE_ROOT_CA_G3_DER = base64.b64decode(
    "MIICQzCCAcmgAwIBAgIILcX8iNLFS5UwCgYIKoZIzj0EAwMwZzEbMBkGA1UEAwwSQXBwbGUgUm9vdCBDQSAtIEczMSYwJAYD"
    "VQQLDB1BcHBsZSBDZXJ0aWZpY2F0aW9uIEF1dGhvcml0eTETMBEGA1UECgwKQXBwbGUgSW5jLjELMAkGA1UEBhMCVVMwHhcN"
    "MTQwNDMwMTgxOTA2WhcNMzkwNDMwMTgxOTA2WjBnMRswGQYDVQQDDBJBcHBsZSBSb290IENBIC0gRzMxJjAkBgNVBAsMHUFw"
    "cGxlIENlcnRpZmljYXRpb24gQXV0aG9yaXR5MRMwEQYDVQQKDApBcHBsZSBJbmMuMQswCQYDVQQGEwJVUzB2MBAGByqGSM49"
    "AgEGBSuBBAAiA2IABJjpLz1AcqTtkyJygRMc3RCV8cWjTnHcFBbZDuWmBSp3ZHtfTjjTuxxEtX/1H7YyYl3J6YRbTzBPEVoA"
    "/VhYDKX1DyxNB0cTddqXl5dvMVztK517IDvYuVTZXpmkOlEKMaNCMEAwHQYDVR0OBBYEFLuw3qFYM4iapIqZ3r6966/ayySr"
    "MA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgEGMAoGCCqGSM49BAMDA2gAMGUCMQCD6cHEFl4aXTQY2e3v9GwOAEZL"
    "uN+yRhHFD/3meoyhpmvOwgPUnPWTxnS4at+qIxUCMG1mihDK1A3UT82NQz60imOlM27jbdoXt2QfyFMm+YhidDkLF1vLUagM"
    "6BgD56KyKA==")
APPLE_ROOT_CA_G3_SHA256 = "63343abfb89a6a03ebb57e9b3f5fa7be7c4f5c756f3017b3a8c488c3653e9179"
TRUSTED_ROOTS = (APPLE_ROOT_CA_G3_DER,)


# ---- elliptisk aritmetik --------------------------------------------------
# Affina koordinater, None är oändlighetspunkten. Inversen är pow(x, -1, p)
# - det är den dyra operationen, och den görs en gång per punktoperation.
# Två skalärmultiplikationer per verifiering tar några millisekunder, vilket
# är gott nog för en webhook och en köpanmälan.

def point_add(curve: Curve, P, Q):
    if P is None:
        return Q
    if Q is None:
        return P
    x1, y1 = P
    x2, y2 = Q
    p = curve.p
    if x1 == x2:
        if (y1 + y2) % p == 0:
            return None
        lam = (3 * x1 * x1 + curve.a) * pow(2 * y1, -1, p) % p
    else:
        lam = (y2 - y1) * pow(x2 - x1, -1, p) % p
    x3 = (lam * lam - x1 - x2) % p
    y3 = (lam * (x1 - x3) - y1) % p
    return (x3, y3)


def scalar_mult(curve: Curve, k: int, point=None):
    """k * point (generatorn när point är None). Dubbling-och-addition."""
    point = curve.g if point is None else point
    result = None
    for bit in bin(k)[2:]:
        result = point_add(curve, result, result)
        if bit == "1":
            result = point_add(curve, result, point)
    return result


def on_curve(curve: Curve, point) -> bool:
    if point is None:
        return False
    x, y = point
    if not (0 <= x < curve.p and 0 <= y < curve.p):
        return False
    return (y * y - (x * x * x + curve.a * x + curve.b)) % curve.p == 0


def hash_to_int(curve: Curve, digest: bytes) -> int:
    """FIPS 186-4 §6.4: hashens vänstra n-bitar som heltal."""
    value = int.from_bytes(digest, "big")
    excess = 8 * len(digest) - curve.n.bit_length()
    return value >> excess if excess > 0 else value


def ecdsa_verify(curve: Curve, public, digest: bytes, r: int, s: int) -> bool:
    n = curve.n
    if not (1 <= r < n and 1 <= s < n) or not on_curve(curve, public):
        return False
    e = hash_to_int(curve, digest)
    w = pow(s, -1, n)
    u1 = e * w % n
    u2 = r * w % n
    point = point_add(curve, scalar_mult(curve, u1), scalar_mult(curve, u2, public))
    return point is not None and point[0] % n == r


# ---- DER --------------------------------------------------------------------
# Precis så mycket ASN.1 som ett X.509-certifikat med EC-nyckel behöver:
# TLV-läsning med lång längd, OID, tider, BIT STRING och INTEGER.

TAG_INTEGER, TAG_BIT_STRING, TAG_OCTET_STRING, TAG_OID = 0x02, 0x03, 0x04, 0x06
TAG_UTC_TIME, TAG_GENERALIZED_TIME, TAG_SEQUENCE, TAG_BOOLEAN = 0x17, 0x18, 0x30, 0x01


def _tlv(data: bytes, pos: int):
    """(tagg, innehåll, slut) för elementet som börjar vid pos."""
    if pos >= len(data):
        raise AppleJwsError("DER: oväntat slut")
    tag = data[pos]
    if tag & 0x1F == 0x1F:
        raise AppleJwsError("DER: flerbyte-tagg stöds inte")
    pos += 1
    if pos >= len(data):
        raise AppleJwsError("DER: längd saknas")
    length = data[pos]
    pos += 1
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or count > 4 or pos + count > len(data):
            raise AppleJwsError("DER: ogiltig längd")
        length = int.from_bytes(data[pos:pos + count], "big")
        pos += count
    end = pos + length
    if end > len(data):
        raise AppleJwsError("DER: elementet sträcker sig förbi datan")
    return tag, data[pos:end], end


def _children(content: bytes) -> list:
    """[(tagg, innehåll, råa byte), ...] för en SEQUENCE/SET."""
    out, pos = [], 0
    while pos < len(content):
        start = pos
        tag, value, pos = _tlv(content, pos)
        out.append((tag, value, content[start:pos]))
    return out


def _expect(item, tag: int, what: str) -> bytes:
    if item[0] != tag:
        raise AppleJwsError(f"DER: {what} har fel tagg ({item[0]:#04x})")
    return item[1]


def _oid(content: bytes) -> str:
    if not content:
        raise AppleJwsError("DER: tom OID")
    parts = [content[0] // 40, content[0] % 40]
    value = 0
    for byte in content[1:]:
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(value)
            value = 0
    if value:
        raise AppleJwsError("DER: avhuggen OID")
    return ".".join(str(part) for part in parts)


def _time(item) -> datetime:
    tag, content, _ = item
    text = content.decode("ascii", "replace")
    try:
        if tag == TAG_UTC_TIME:
            year = int(text[:2])
            year += 2000 if year < 50 else 1900
            parsed = datetime.strptime(text[2:], "%m%d%H%M%SZ").replace(year=year)
        elif tag == TAG_GENERALIZED_TIME:
            parsed = datetime.strptime(text[:15], "%Y%m%d%H%M%SZ")
        else:
            raise AppleJwsError("DER: okänd tidstyp")
    except ValueError:
        raise AppleJwsError("DER: ogiltig tid")
    return parsed.replace(tzinfo=timezone.utc)


def _integer(content: bytes) -> int:
    return int.from_bytes(content, "big", signed=True)


@dataclass(frozen=True)
class Certificate:
    der: bytes
    tbs: bytes                 # råa TBSCertificate-byten, det som signerats
    serial: int
    issuer: bytes              # råa Name-byten - jämförs, tolkas aldrig
    subject: bytes
    not_before: datetime
    not_after: datetime
    curve: Curve
    public: tuple
    signature_hash: str
    signature: tuple           # (r, s)
    extension_oids: frozenset

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.der).hexdigest()


def parse_certificate(der: bytes) -> Certificate:
    """Ett X.509-certifikat med EC-nyckel. Kastar AppleJwsError på allt
    som inte är precis den formen - hellre ett nej än en gissning."""
    tag, body, end = _tlv(der, 0)
    if tag != TAG_SEQUENCE or end != len(der):
        raise AppleJwsError("DER: certifikatet är inte en enda SEQUENCE")
    outer = _children(body)
    if len(outer) != 3:
        raise AppleJwsError("DER: certifikatet ska ha tbs, algoritm och signatur")
    tbs_item, alg_item, sig_item = outer
    tbs_raw = tbs_item[2]
    tbs = _children(_expect(tbs_item, TAG_SEQUENCE, "tbsCertificate"))
    if tbs and tbs[0][0] == 0xA0:     # [0] EXPLICIT version
        tbs = tbs[1:]
    if len(tbs) < 6:
        raise AppleJwsError("DER: tbsCertificate är för kort")
    serial = _integer(_expect(tbs[0], TAG_INTEGER, "serialNumber"))
    issuer = tbs[2][2]
    validity = _children(_expect(tbs[3], TAG_SEQUENCE, "validity"))
    if len(validity) != 2:
        raise AppleJwsError("DER: validity ska ha två tider")
    subject = tbs[4][2]
    spki = _children(_expect(tbs[5], TAG_SEQUENCE, "subjectPublicKeyInfo"))
    if len(spki) != 2:
        raise AppleJwsError("DER: subjectPublicKeyInfo har fel form")
    key_alg = _children(_expect(spki[0], TAG_SEQUENCE, "nyckelalgoritm"))
    if len(key_alg) != 2 or _oid(_expect(key_alg[0], TAG_OID, "nyckelalgoritm")) != OID_EC_PUBLIC_KEY:
        raise AppleJwsError("certifikatets nyckel är inte en EC-nyckel")
    curve = CURVE_BY_OID.get(_oid(_expect(key_alg[1], TAG_OID, "kurva")))
    if curve is None:
        raise AppleJwsError("certifikatets kurva stöds inte")
    key_bits = _expect(spki[1], TAG_BIT_STRING, "subjectPublicKey")
    if len(key_bits) != 2 + 2 * curve.size or key_bits[0] != 0 or key_bits[1] != 0x04:
        raise AppleJwsError("certifikatets nyckel är inte en okomprimerad EC-punkt")
    public = (int.from_bytes(key_bits[2:2 + curve.size], "big"),
              int.from_bytes(key_bits[2 + curve.size:], "big"))
    if not on_curve(curve, public):
        raise AppleJwsError("certifikatets nyckel ligger inte på kurvan")
    extension_oids = set()
    for item in tbs[6:]:
        if item[0] != 0xA3:            # [3] EXPLICIT extensions
            continue
        for ext in _children(_children(item[1])[0][1]):
            fields = _children(_expect(ext, TAG_SEQUENCE, "extension"))
            if fields:
                extension_oids.add(_oid(_expect(fields[0], TAG_OID, "extnID")))
    sig_alg = _children(_expect(alg_item, TAG_SEQUENCE, "signatureAlgorithm"))
    signature_hash = HASH_BY_SIGNATURE_OID.get(_oid(_expect(sig_alg[0], TAG_OID, "signaturalgoritm"))) if sig_alg else None
    if signature_hash is None:
        raise AppleJwsError("certifikatets signaturalgoritm är inte ECDSA")
    sig_bits = _expect(sig_item, TAG_BIT_STRING, "signatureValue")
    if not sig_bits or sig_bits[0] != 0:
        raise AppleJwsError("DER: signaturen har oanvända bitar")
    rs_tag, rs_body, _ = _tlv(sig_bits, 1)
    rs = _children(rs_body)
    if rs_tag != TAG_SEQUENCE or len(rs) != 2:
        raise AppleJwsError("DER: ECDSA-signaturen är inte SEQUENCE {r, s}")
    signature = (_integer(_expect(rs[0], TAG_INTEGER, "r")), _integer(_expect(rs[1], TAG_INTEGER, "s")))
    return Certificate(der=bytes(der), tbs=bytes(tbs_raw), serial=serial, issuer=bytes(issuer),
                       subject=bytes(subject), not_before=_time(validity[0]), not_after=_time(validity[1]),
                       curve=curve, public=public, signature_hash=signature_hash, signature=signature,
                       extension_oids=frozenset(extension_oids))


def certificate_signed_by(cert: Certificate, issuer: Certificate) -> bool:
    """Är `cert` signerat med `issuer`:s nyckel? Hashen är den certifikatet
    själv anger (Apple: SHA-384), kurvan är utfärdarens."""
    digest = hashlib.new(cert.signature_hash, cert.tbs).digest()
    return ecdsa_verify(issuer.curve, issuer.public, digest, *cert.signature)


# ---- kedjan och JWS:en ------------------------------------------------------

def verify_chain(ders, *, trusted_roots=TRUSTED_ROOTS, at: datetime) -> Certificate:
    """Löv -> mellanliggande -> rot. Returnerar lövet, eller kastar.

    Förtroendet kommer från den PINNADE roten, inte från x5c[2]: den
    mellanliggande måste vara utfärdad av (namn) och signerad av (nyckel)
    ett betrott rotcertifikat. Det är vad ett X.509-trust store gör och vad
    Apples bibliotek gör - och det betyder att en avsändare inte kan byta
    rot genom att skicka med en egen. Vad som står i x5c[2] är
    upplysning; det prövas bara på form och giltighetstid."""
    if len(ders) != 3:
        raise AppleJwsError(f"x5c ska bära exakt tre certifikat, inte {len(ders)}")
    leaf, intermediate, sent_root = (parse_certificate(der) for der in ders)
    anchors = [parse_certificate(bytes(trusted)) for trusted in trusted_roots]
    root = next((anchor for anchor in anchors
                 if intermediate.issuer == anchor.subject and certificate_signed_by(intermediate, anchor)),
                None)
    if root is None:
        raise AppleJwsError("kedjans rot är inte Apple Root CA - G3")
    if leaf.issuer != intermediate.subject:
        raise AppleJwsError("lövcertifikatets utfärdare är inte nästa länk")
    if not certificate_signed_by(leaf, intermediate):
        raise AppleJwsError("lövcertifikatets signatur verifierades inte")
    for cert, name in ((leaf, "löv"), (intermediate, "mellanliggande"), (root, "rot"), (sent_root, "medskickad rot")):
        if not (cert.not_before <= at <= cert.not_after):
            raise AppleJwsError(f"{name}certifikatet gäller inte vid {at.isoformat()}")
    if OID_APPLE_WWDR_CA not in intermediate.extension_oids:
        raise AppleJwsError("mellanliggande certifikat är inte Apples WWDR CA")
    if OID_APPLE_RECEIPT_SIGNING not in leaf.extension_oids:
        raise AppleJwsError("lövcertifikatet är inte App Stores signeringscertifikat")
    return leaf


def b64url_decode(text: str) -> bytes:
    text = (text or "").strip()
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError):
        raise AppleJwsError("ogiltig base64url")


def _json_object(raw: bytes, what: str) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise AppleJwsError(f"{what} är inte JSON")
    if not isinstance(value, dict):
        raise AppleJwsError(f"{what} är inte ett JSON-objekt")
    return value


def signed_date_of(payload: dict):
    """Apples `signedDate` (ms sedan epoch) som datetime, eller None."""
    value = payload.get("signedDate", payload.get("receiptCreationDate"))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def decode_unverified(token: str) -> tuple:
    """(huvud, payload, signatur, signeringsindata) utan att verifiera något.
    Bara för att läsa signedDate innan kedjan prövas - använd aldrig
    payloaden härifrån till något annat."""
    parts = (token or "").split(".")
    if len(parts) != 3 or not all(parts):
        raise AppleJwsError("JWS ska ha tre delar")
    header = _json_object(b64url_decode(parts[0]), "JWS-huvudet")
    payload = _json_object(b64url_decode(parts[1]), "JWS-payloaden")
    signature = b64url_decode(parts[2])
    return header, payload, signature, f"{parts[0]}.{parts[1]}".encode("ascii")


def verify_jws(token: str, *, trusted_roots=TRUSTED_ROOTS, at: datetime | None = None,
               now=None) -> dict:
    """Verifierar en JWS från Apple och returnerar dess payload.

    Kedjans giltighet prövas vid `at`, annars vid payloadens `signedDate`
    (som Apples bibliotek gör), annars nu. Kastar AppleJwsError."""
    header, payload, signature, signing_input = decode_unverified(token)
    if header.get("alg") != "ES256":
        raise AppleJwsError("JWS-algoritmen är inte ES256")
    x5c = header.get("x5c")
    if not isinstance(x5c, list) or not x5c or not all(isinstance(item, str) for item in x5c):
        raise AppleJwsError("JWS-huvudet saknar x5c")
    try:
        ders = [base64.b64decode(item, validate=True) for item in x5c]
    except (ValueError, TypeError):
        raise AppleJwsError("x5c är inte base64")
    if at is None:
        at = signed_date_of(payload) or (now() if now else datetime.now(timezone.utc))
    leaf = verify_chain(ders, trusted_roots=trusted_roots, at=at)
    if leaf.curve is not P256 or len(signature) != 2 * P256.size:
        raise AppleJwsError("JWS-signaturen har fel form för ES256")
    r = int.from_bytes(signature[:P256.size], "big")
    s = int.from_bytes(signature[P256.size:], "big")
    if not ecdsa_verify(P256, leaf.public, hashlib.sha256(signing_input).digest(), r, s):
        raise AppleJwsError("JWS-signaturen verifierades inte")
    return payload
