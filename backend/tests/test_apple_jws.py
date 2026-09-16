# -*- coding: utf-8 -*-
"""P02c: verifieraren för Apples signerade data - bevisad från fyra håll.

En egen ECDSA-implementation är bara värd något om den prövas mot sådant
den inte själv har skrivit. Därför fyra sorters bevis, i stigande grad av
oberoende:

  1. Aritmetiken mot RFC 6979:s testvektor (känt k, känd signatur) och mot
     signaturer OpenSSL gjort med nycklar den här koden aldrig sett.
  2. Apples RIKTIGA certifikat: WWDR G6 verifierat mot Apple Root CA - G3,
     som ligger inbäddad i modulen och vars fingeravtryck prövas här.
  3. Apples egna testfixturer (MIT) ur app-store-server-library-python -
     JWS:er deras verifierare godkänner mot deras testrot, inklusive fallet
     där x5c[2] är en omutgåva av roten.
  4. Kedjor och JWS:er byggda i testet, för varje sätt en kedja kan vara
     fel på: för kort, fel rot, rätt namn men fel nyckel, saknad OID,
     utgången, fel algoritm, manipulerad payload, fel signerare.

Inget nät, inga skip. Nycklarna i (4) slumpas vid varje körning.
"""

import base64
import hashlib
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HÄR = Path(__file__).resolve().parent
sys.path.insert(0, str(HÄR.parent))
sys.path.insert(0, str(HÄR))

import apple_fixturer_fran_apple as apple_fixturer  # noqa: E402
import apple_testkedja as kedja  # noqa: E402
from services.billing import apple_jws as jws  # noqa: E402

NU = datetime.now(timezone.utc).replace(microsecond=0)

# Apple Worldwide Developer Relations Certification Authority, OU=G6 - det
# riktiga, hämtat 2026-09-16 från https://www.apple.com/certificateauthority/
# (AppleWWDRCAG6.cer). Publikt; utfärdat av Apple Root CA - G3.
WWDR_G6_DER = base64.b64decode(
    "MIIDFjCCApygAwIBAgIUIsGhRwp0c2nvU4YSycafPTjzbNcwCgYIKoZIzj0EAwMwZzEbMBkGA1UEAwwSQXBwbGUgUm9vdCBDQSAt"
    "IEczMSYwJAYDVQQLDB1BcHBsZSBDZXJ0aWZpY2F0aW9uIEF1dGhvcml0eTETMBEGA1UECgwKQXBwbGUgSW5jLjELMAkGA1UEBhMC"
    "VVMwHhcNMjEwMzE3MjAzNzEwWhcNMzYwMzE5MDAwMDAwWjB1MUQwQgYDVQQDDDtBcHBsZSBXb3JsZHdpZGUgRGV2ZWxvcGVyIFJl"
    "bGF0aW9ucyBDZXJ0aWZpY2F0aW9uIEF1dGhvcml0eTELMAkGA1UECwwCRzYxEzARBgNVBAoMCkFwcGxlIEluYy4xCzAJBgNVBAYT"
    "AlVTMHYwEAYHKoZIzj0CAQYFK4EEACIDYgAEbsQKC94PrlWmZXnXgtxzdVJL8T0SGYngDRGpngn3N6PT8JMEb7FDi4bBmPhCnZ3/"
    "sq6PF/cGcKXWsL5vOteRhyJ45x3ASP7cOB+aao90fcpxSv/EZFbniAbNgZGhIhpIo4H6MIH3MBIGA1UdEwEB/wQIMAYBAf8CAQAw"
    "HwYDVR0jBBgwFoAUu7DeoVgziJqkipnevr3rr9rLJKswRgYIKwYBBQUHAQEEOjA4MDYGCCsGAQUFBzABhipodHRwOi8vb2NzcC5h"
    "cHBsZS5jb20vb2NzcDAzLWFwcGxlcm9vdGNhZzMwNwYDVR0fBDAwLjAsoCqgKIYmaHR0cDovL2NybC5hcHBsZS5jb20vYXBwbGVy"
    "b290Y2FnMy5jcmwwHQYDVR0OBBYEFD8vlCNR01DJmig97bB85c+lkGKZMA4GA1UdDwEB/wQEAwIBBjAQBgoqhkiG92NkBgIBBAIF"
    "ADAKBggqhkjOPQQDAwNoADBlAjBAXhSq5IyKogMCPtw490BaB677CaEGJXufQB/EqZGd6CSjiCtOnuMTbXVXmxxcxfkCMQDTSPxa"
    "rZXvNrkxU3TkUMI33yzvFVVRT4wxWJC994OsdcZ4+RGNsYDyR5gmdr0nDGg=")

# OpenSSL 3.6.4 (macOS, 2026-09-16): `ecparam -genkey`, `dgst -sha256 -sign`
# över meddelandet "matjakt-korstest". Bara publika nycklar och signaturer;
# de privata halvorna kastades.
OPENSSL_MEDDELANDE = b"matjakt-korstest"
OPENSSL_P256_PUB_DER = bytes.fromhex(
    "3059301306072a8648ce3d020106082a8648ce3d03010703420004692b7c53ffab0e1c7c67d66ef7bb02860204a2c72b2944d17c"
    "0aad1513c6415e22de1a5052edd7900f4f242f01fa2ca242970e982a7d9e44ae99fa60e20761fa")
OPENSSL_P256_SIG_DER = bytes.fromhex(
    "3045022043704b3410c1c2a14a3c590c3b171a412809ea9d21cc702b48097ed132a29d6e022100d8acfb339ca7ce5a9a9b25be583f"
    "bb0e6fe5a1d13290234811413991f3feca98")
OPENSSL_P384_PUB_DER = bytes.fromhex(
    "3076301006072a8648ce3d020106052b810400220362000488e3b880e1bd48766b1aa34254bffd82ce75a8055a2b4bf3b07bd35164"
    "b95ecd260010b8888579f88cacbd6fdf1a86d48d46fb20057825cff47b23b40101f974ca283b26a23245435f759251f384f8f75499"
    "b66e8e4b70addc360f39c8336452")
OPENSSL_P384_SIG_DER = bytes.fromhex(
    "3066023100ae3ec4331e507f7dbc2c03a8458ebee9d9cee684a8c49262d5e24b2155120b6d6793c5e51a6965a129d45a6dc37d4e2e"
    "0231009ffbb47cabed98ee695e6d8a4e00a72d6456c41cd732152c1abe00150219809be9d91aea7acc57a5f55d9d6325133d30")


def _spki(der):
    """(kurva, punkt) ur en SubjectPublicKeyInfo - med modulens egen läsare."""
    _, body, _ = jws._tlv(der, 0)
    alg, bits = jws._children(body)
    curve = jws.CURVE_BY_OID[jws._oid(jws._children(alg[1])[1][1])]
    raw = bits[1][2:]
    return curve, (int.from_bytes(raw[:curve.size], "big"), int.from_bytes(raw[curve.size:], "big"))


def _der_sig(der):
    _, body, _ = jws._tlv(der, 0)
    r, s = jws._children(body)
    return jws._integer(r[1]), jws._integer(s[1])


class Aritmetiken(unittest.TestCase):
    def test_rfc_6979_p256_vektorn(self):
        # RFC 6979 A.2.5, P-256/SHA-256, meddelandet "sample": känd privat
        # nyckel, känt k, känd signatur. Stämmer r, s OCH den publika nyckeln
        # är kurvparametrarna, punktaritmetiken och hash->heltal rätt.
        d = 0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721
        k = 0xA6E3C57DD01ABE90086538398355DD4C3B17AA873382B0F24D6129493D8AAD60
        self.assertEqual(jws.scalar_mult(jws.P256, d), (
            0x60FED4BA255A9D31C961EB74C6356D68C049B8923B61FA6CE669622E60F29FB6,
            0x7903FE1008B8BC99A41AE9E95628BC64F2F1B20C2D7E9F5177A3C294D4462299))
        r, s = kedja.ecdsa_sign(jws.P256, d, hashlib.sha256(b"sample").digest(), k=k)
        self.assertEqual(r, 0xEFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716)
        self.assertEqual(s, 0xF7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8)
        self.assertTrue(jws.ecdsa_verify(jws.P256, jws.scalar_mult(jws.P256, d),
                                         hashlib.sha256(b"sample").digest(), r, s))

    def test_openssl_p256_signatur_verifieras(self):
        curve, public = _spki(OPENSSL_P256_PUB_DER)
        self.assertIs(curve, jws.P256)
        r, s = _der_sig(OPENSSL_P256_SIG_DER)
        self.assertTrue(jws.ecdsa_verify(curve, public, hashlib.sha256(OPENSSL_MEDDELANDE).digest(), r, s))
        self.assertFalse(jws.ecdsa_verify(curve, public, hashlib.sha256(b"annat meddelande").digest(), r, s))
        self.assertFalse(jws.ecdsa_verify(curve, public, hashlib.sha256(OPENSSL_MEDDELANDE).digest(), r, s + 1))

    def test_openssl_p384_signatur_verifieras(self):
        curve, public = _spki(OPENSSL_P384_PUB_DER)
        self.assertIs(curve, jws.P384)
        r, s = _der_sig(OPENSSL_P384_SIG_DER)
        self.assertTrue(jws.ecdsa_verify(curve, public, hashlib.sha384(OPENSSL_MEDDELANDE).digest(), r, s))
        self.assertFalse(jws.ecdsa_verify(curve, public, hashlib.sha384(b"x").digest(), r, s))

    def test_signaturvarden_utanfor_intervallet_avvisas(self):
        curve, public = _spki(OPENSSL_P256_PUB_DER)
        digest = hashlib.sha256(OPENSSL_MEDDELANDE).digest()
        for r, s in ((0, 1), (1, 0), (curve.n, 1), (1, curve.n)):
            self.assertFalse(jws.ecdsa_verify(curve, public, digest, r, s))
        self.assertFalse(jws.ecdsa_verify(curve, (1, 2), digest, 1, 1), "en punkt utanför kurvan")


class ApplesRiktigaCertifikat(unittest.TestCase):
    def test_den_inbaddade_roten_ar_apple_root_ca_g3(self):
        self.assertEqual(hashlib.sha256(jws.APPLE_ROOT_CA_G3_DER).hexdigest(), jws.APPLE_ROOT_CA_G3_SHA256)
        root = jws.parse_certificate(jws.APPLE_ROOT_CA_G3_DER)
        self.assertIs(root.curve, jws.P384)
        self.assertEqual(root.signature_hash, "sha384")
        self.assertEqual(root.not_before.date().isoformat(), "2014-04-30")
        self.assertEqual(root.not_after.date().isoformat(), "2039-04-30")
        self.assertEqual(root.issuer, root.subject, "roten är självutfärdad")
        self.assertTrue(jws.certificate_signed_by(root, root))

    def test_wwdr_g6_ar_utfardat_och_signerat_av_roten(self):
        root = jws.parse_certificate(jws.APPLE_ROOT_CA_G3_DER)
        wwdr = jws.parse_certificate(WWDR_G6_DER)
        self.assertEqual(wwdr.issuer, root.subject)
        self.assertTrue(jws.certificate_signed_by(wwdr, root))
        self.assertIn(jws.OID_APPLE_WWDR_CA, wwdr.extension_oids)
        self.assertEqual(wwdr.not_after.date().isoformat(), "2036-03-19")

    def test_ett_manipulerat_wwdr_g6_avvisas(self):
        root = jws.parse_certificate(jws.APPLE_ROOT_CA_G3_DER)
        wwdr = jws.parse_certificate(WWDR_G6_DER)
        # En byte i det signerade innehållet (giltighetstiden) ändrad.
        trasig = bytearray(WWDR_G6_DER)
        index = WWDR_G6_DER.index(b"210317203710Z")
        trasig[index + 1] = ord("2")
        self.assertFalse(jws.certificate_signed_by(jws.parse_certificate(bytes(trasig)), root))


class ApplesTestfixturer(unittest.TestCase):
    """MIT-licensierade testdata ur Apples referensbibliotek - se
    apple_fixturer_fran_apple.py."""

    def setUp(self):
        self.testrot = (base64.b64decode(apple_fixturer.TESTCA_DER_B64),)

    def test_apples_fixturer_verifieras_mot_deras_testrot(self):
        payload = jws.verify_jws(apple_fixturer.TEST_NOTIFICATION, trusted_roots=self.testrot)
        self.assertEqual(payload["notificationType"], "TEST")
        self.assertEqual(payload["data"]["bundleId"], "com.example")
        self.assertEqual(jws.verify_jws(apple_fixturer.TRANSACTION_INFO, trusted_roots=self.testrot)["environment"],
                         "Sandbox")
        self.assertEqual(jws.verify_jws(apple_fixturer.RENEWAL_INFO, trusted_roots=self.testrot)["signedDate"],
                         1672956154000)
        # Fel bundle-id är INTE ett kedjefel - det dömer nästa lager.
        self.assertEqual(jws.verify_jws(apple_fixturer.WRONG_BUNDLE_ID, trusted_roots=self.testrot)["data"]["bundleId"],
                         "com.example.wrong")

    def test_x5c_med_en_omutgava_av_roten_godtas_som_hos_apple(self):
        # testNotification bär en rot med samma namn och nyckel som testCA
        # men annat serienummer. Förtroendet kommer från vår pinnade rot,
        # inte från byten i x5c[2] - så det ska gå igenom, precis som i
        # Apples egen svit.
        header = json.loads(jws.b64url_decode(apple_fixturer.TEST_NOTIFICATION.split(".")[0]))
        medskickad = jws.parse_certificate(base64.b64decode(header["x5c"][2]))
        pinnad = jws.parse_certificate(self.testrot[0])
        self.assertNotEqual(medskickad.der, pinnad.der)
        self.assertEqual(medskickad.public, pinnad.public)

    def test_fixturen_utan_x5c_avvisas(self):
        with self.assertRaisesRegex(jws.AppleJwsError, "x5c"):
            jws.verify_jws(apple_fixturer.MISSING_X5C_HEADER_CLAIM, trusted_roots=self.testrot)

    def test_apples_fixturer_avvisas_mot_apples_riktiga_rot(self):
        # Deras testrot är inte Apple Root CA - G3. Standardinställningen
        # litar bara på den riktiga.
        with self.assertRaisesRegex(jws.AppleJwsError, "rot"):
            jws.verify_jws(apple_fixturer.TEST_NOTIFICATION)


class EgenKedja(unittest.TestCase):
    def setUp(self):
        self.chain = kedja.apple_like_chain()
        self.roots = (self.chain[2].der,)
        self.payload = {"notificationType": "TEST", "signedDate": kedja.ms(NU)}

    def test_en_giltig_kedja_och_jws_verifieras(self):
        token = kedja.sign_jws(self.payload, self.chain)
        self.assertEqual(jws.verify_jws(token, trusted_roots=self.roots), self.payload)

    def test_roten_maste_vara_betrodd(self):
        token = kedja.sign_jws(self.payload, self.chain)
        with self.assertRaisesRegex(jws.AppleJwsError, "rot"):
            jws.verify_jws(token)                       # bara Apples rot är betrodd

    def test_en_falsk_rot_med_ratt_namn_men_fel_nyckel_avvisas(self):
        # Samma CN som vår rot, en annan nyckel, och ett mellanliggande
        # signerat av bedragaren. x5c ser rätt ut; nyckeln gör det inte.
        falsk_rot = kedja.Cert("Test Root CA", curve=jws.P384)
        falsk_inter = kedja.Cert("Test WWDR CA", curve=jws.P384, issuer=falsk_rot,
                                 extension_oids=(jws.OID_APPLE_WWDR_CA,))
        falskt_lov = kedja.Cert("Test App Store Signing", curve=jws.P256, issuer=falsk_inter,
                                extension_oids=(jws.OID_APPLE_RECEIPT_SIGNING,))
        token = kedja.sign_jws(self.payload, (falskt_lov, falsk_inter, falsk_rot))
        with self.assertRaisesRegex(jws.AppleJwsError, "rot"):
            jws.verify_jws(token, trusted_roots=self.roots)

    def test_en_omutgava_av_roten_i_x5c_godtas(self):
        root = self.chain[2]
        omutgava = kedja.Cert(root.common_name, curve=jws.P384, keys=(root.private, root.public))
        self.assertNotEqual(omutgava.der, root.der)
        token = kedja.sign_jws(self.payload, (self.chain[0], self.chain[1], omutgava))
        self.assertEqual(jws.verify_jws(token, trusted_roots=self.roots)["notificationType"], "TEST")

    def test_tva_certifikat_ar_for_fa_och_fyra_for_manga(self):
        leaf, inter, root = self.chain
        for x5c in ([leaf, inter], [leaf, inter, root, root]):
            token = kedja.sign_jws(self.payload, self.chain,
                                   x5c=[base64.b64encode(c.der).decode() for c in x5c])
            with self.assertRaisesRegex(jws.AppleJwsError, "tre certifikat"):
                jws.verify_jws(token, trusted_roots=self.roots)

    def test_mellanliggande_utan_wwdr_oid_avvisas(self):
        chain = kedja.apple_like_chain(intermediate_oids=())
        token = kedja.sign_jws(self.payload, chain)
        with self.assertRaisesRegex(jws.AppleJwsError, "WWDR"):
            jws.verify_jws(token, trusted_roots=(chain[2].der,))

    def test_lov_utan_signerings_oid_avvisas(self):
        chain = kedja.apple_like_chain(leaf_oids=())
        token = kedja.sign_jws(self.payload, chain)
        with self.assertRaisesRegex(jws.AppleJwsError, "signeringscertifikat"):
            jws.verify_jws(token, trusted_roots=(chain[2].der,))

    def test_ett_utganget_lov_avvisas_och_signeddate_ar_klockan(self):
        chain = kedja.apple_like_chain(leaf_not_after=NU - timedelta(days=1))
        roots = (chain[2].der,)
        with self.assertRaisesRegex(jws.AppleJwsError, "gäller inte"):
            jws.verify_jws(kedja.sign_jws({"signedDate": kedja.ms(NU)}, chain), trusted_roots=roots)
        # Samma kedja, en payload signerad medan lövet gällde: Apples
        # bibliotek prövar kedjan vid signedDate, och det gör vi också.
        gammal = {"signedDate": kedja.ms(NU - timedelta(days=3))}
        self.assertEqual(jws.verify_jws(kedja.sign_jws(gammal, chain), trusted_roots=roots), gammal)

    def test_fel_algoritm_avvisas(self):
        token = kedja.sign_jws(self.payload, self.chain, alg="HS256")
        with self.assertRaisesRegex(jws.AppleJwsError, "ES256"):
            jws.verify_jws(token, trusted_roots=self.roots)

    def test_manipulerad_payload_avvisas(self):
        head, body, sig = kedja.sign_jws(self.payload, self.chain).split(".")
        annan = kedja.b64url(json.dumps({**self.payload, "notificationType": "SUBSCRIBED"}).encode())
        with self.assertRaisesRegex(jws.AppleJwsError, "verifierades inte"):
            jws.verify_jws(f"{head}.{annan}.{sig}", trusted_roots=self.roots)

    def test_signatur_fran_en_annan_nyckel_avvisas(self):
        annan = kedja.Cert("Annan", curve=jws.P256)
        token = kedja.sign_jws(self.payload, self.chain, signer=annan)
        with self.assertRaisesRegex(jws.AppleJwsError, "verifierades inte"):
            jws.verify_jws(token, trusted_roots=self.roots)

    def test_ett_lov_pa_p384_duger_inte_for_es256(self):
        chain = kedja.apple_like_chain(leaf_curve=jws.P384)
        token = kedja.sign_jws(self.payload, chain)
        with self.assertRaisesRegex(jws.AppleJwsError, "fel form"):
            jws.verify_jws(token, trusted_roots=(chain[2].der,))

    def test_trasig_form_avvisas_utan_undantag_av_annan_sort(self):
        for token in ("", "a.b", "a.b.c.d", "!!.!!.!!", "e30.e30.e30"):
            with self.assertRaises(jws.AppleJwsError):
                jws.verify_jws(token, trusted_roots=self.roots)
        head = kedja.b64url(json.dumps({"alg": "ES256", "x5c": ["inte base64 %%%"]}).encode())
        with self.assertRaises(jws.AppleJwsError):
            jws.verify_jws(f"{head}.e30.AAAA", trusted_roots=self.roots)
        with self.assertRaises(jws.AppleJwsError):
            jws.parse_certificate(b"\x30\x03\x02\x01")     # avhuggen DER


if __name__ == "__main__":
    unittest.main()
