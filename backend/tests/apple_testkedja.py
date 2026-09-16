# -*- coding: utf-8 -*-
"""Testhjälpare: en egen certifikatkedja i Apples form, och JWS:er signerade
med den.

Apples riktiga signeringsnyckel finns bara hos Apple, så en JWS som
verifieraren ska godkänna måste byggas av oss - med en rot vi själva
kontrollerar och lämnar in som betrodd. Här finns det som behövs: ett
nyckelpar per certifikat, ECDSA-signering, en DER-kodare stor nog för ett
X.509 v3-certifikat, och en JWS-byggare. Kurvaritmetiken lånas från
modulen som prövas; att signerare och verifierare delar den är ofarligt
därför att testsviten OCKSÅ verifierar signaturer gjorda av OpenSSL och
Apples riktiga certifikat, som aldrig sett vår kod.

Inget här är en hemlighet: nycklarna genereras vid varje körning och kastas.
"""

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from services.billing.apple_jws import (OID_APPLE_RECEIPT_SIGNING, OID_APPLE_WWDR_CA, P256, P384,
                                        hash_to_int, scalar_mult)

# ---- nycklar och signering ------------------------------------------------


def keypair(curve=P256):
    """(privat skalär, publik punkt)."""
    private = secrets.randbelow(curve.n - 1) + 1
    return private, scalar_mult(curve, private)


def ecdsa_sign(curve, private: int, digest: bytes, k: int | None = None) -> tuple:
    """(r, s). `k` får anges för kända testvektorer; annars slumpas den."""
    e = hash_to_int(curve, digest)
    while True:
        nonce = k if k is not None else secrets.randbelow(curve.n - 1) + 1
        point = scalar_mult(curve, nonce)
        r = point[0] % curve.n
        s = pow(nonce, -1, curve.n) * (e + r * private) % curve.n
        if r and s:
            return r, s
        if k is not None:
            raise ValueError("k gav r eller s = 0")


# ---- DER-kodning ------------------------------------------------------------


def _length(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def tlv(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _length(len(content)) + content


def der_sequence(*items: bytes) -> bytes:
    return tlv(0x30, b"".join(items))


def der_set(*items: bytes) -> bytes:
    return tlv(0x31, b"".join(items))


def der_integer(value: int) -> bytes:
    body = value.to_bytes((value.bit_length() + 8) // 8, "big", signed=True)
    return tlv(0x02, body)


def der_oid(text: str) -> bytes:
    parts = [int(p) for p in text.split(".")]
    out = bytes([parts[0] * 40 + parts[1]])
    for part in parts[2:]:
        chunk = bytes([part & 0x7F])
        part >>= 7
        while part:
            chunk = bytes([0x80 | (part & 0x7F)]) + chunk
            part >>= 7
        out += chunk
    return tlv(0x06, out)


def der_utf8(text: str) -> bytes:
    return tlv(0x0C, text.encode("utf-8"))


def der_utc_time(moment: datetime) -> bytes:
    return tlv(0x17, moment.strftime("%y%m%d%H%M%SZ").encode("ascii"))


def der_bit_string(content: bytes) -> bytes:
    return tlv(0x03, b"\x00" + content)


def der_octet_string(content: bytes) -> bytes:
    return tlv(0x04, content)


def der_explicit(number: int, content: bytes) -> bytes:
    return tlv(0xA0 | number, content)


def der_name(common_name: str) -> bytes:
    return der_sequence(der_set(der_sequence(der_oid("2.5.4.3"), der_utf8(common_name))))


CURVE_OID = {P256: "1.2.840.10045.3.1.7", P384: "1.3.132.0.34"}
SIGNATURE_OID = {P256: "1.2.840.10045.4.3.2", P384: "1.2.840.10045.4.3.3"}
SIGNATURE_HASH = {P256: "sha256", P384: "sha384"}


def der_spki(curve, public) -> bytes:
    point = b"\x04" + public[0].to_bytes(curve.size, "big") + public[1].to_bytes(curve.size, "big")
    return der_sequence(der_sequence(der_oid("1.2.840.10045.2.1"), der_oid(CURVE_OID[curve])),
                        der_bit_string(point))


def der_ecdsa_signature(r: int, s: int) -> bytes:
    return der_sequence(der_integer(r), der_integer(s))


# ---- certifikat ----------------------------------------------------------------


class Cert:
    """Ett certifikat med sin egen nyckel. `der` är det som går in i x5c."""

    def __init__(self, common_name, *, curve, issuer=None, extension_oids=(), not_before=None,
                 not_after=None, serial=None, keys=None):
        self.common_name = common_name
        self.curve = curve
        # `keys` = (privat, publik) för att ge ut ett NYTT certifikat på en
        # befintlig nyckel - så som Apples fixtur bär en omutgåva av roten.
        self.private, self.public = keys if keys is not None else keypair(curve)
        signer = issuer if issuer is not None else self
        now = datetime.now(timezone.utc).replace(microsecond=0)
        # Giltiga en månad bakåt: kedjan prövas vid payloadens signedDate,
        # och testerna signerar ibland "för några dagar sedan".
        self.not_before = not_before or (now - timedelta(days=30))
        self.not_after = not_after or (now + timedelta(days=365))
        self.serial = serial if serial is not None else secrets.randbelow(2 ** 62) + 1
        extensions = der_sequence(*(der_sequence(der_oid(oid), der_octet_string(b"\x05\x00"))
                                    for oid in extension_oids))
        tbs = der_sequence(
            der_explicit(0, der_integer(2)),                     # v3
            der_integer(self.serial),
            der_sequence(der_oid(SIGNATURE_OID[signer.curve])),
            der_name(signer.common_name),
            der_sequence(der_utc_time(self.not_before), der_utc_time(self.not_after)),
            der_name(common_name),
            der_spki(curve, self.public),
            *( [der_explicit(3, extensions)] if extension_oids else [] ),
        )
        digest = hashlib.new(SIGNATURE_HASH[signer.curve], tbs).digest()
        r, s = ecdsa_sign(signer.curve, signer.private, digest)
        self.der = der_sequence(tbs, der_sequence(der_oid(SIGNATURE_OID[signer.curve])),
                                der_bit_string(der_ecdsa_signature(r, s)))


def apple_like_chain(*, leaf_oids=(OID_APPLE_RECEIPT_SIGNING,), intermediate_oids=(OID_APPLE_WWDR_CA,),
                     leaf_curve=P256, leaf_not_after=None):
    """(löv, mellanliggande, rot) i samma form som Apples: roten och den
    mellanliggande på P-384 med SHA-384, lövet på P-256."""
    root = Cert("Test Root CA", curve=P384)
    intermediate = Cert("Test WWDR CA", curve=P384, issuer=root, extension_oids=intermediate_oids)
    leaf = Cert("Test App Store Signing", curve=leaf_curve, issuer=intermediate,
                extension_oids=leaf_oids, not_after=leaf_not_after)
    return leaf, intermediate, root


# ---- JWS ---------------------------------------------------------------------


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def sign_jws(payload: dict, chain, *, alg="ES256", x5c=None, signer=None) -> str:
    """En JWS i Apples form. `chain` är (löv, mellanliggande, rot); x5c och
    signeraren kan bytas ut för att bygga trasiga exemplar."""
    leaf = chain[0]
    signer = signer or leaf
    header = {"alg": alg, "x5c": x5c if x5c is not None else [base64.b64encode(c.der).decode("ascii") for c in chain]}
    head = b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    body = b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    digest = hashlib.sha256(f"{head}.{body}".encode("ascii")).digest()
    r, s = ecdsa_sign(signer.curve, signer.private, digest)
    size = signer.curve.size
    return f"{head}.{body}.{b64url(r.to_bytes(size, 'big') + s.to_bytes(size, 'big'))}"


def ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)
