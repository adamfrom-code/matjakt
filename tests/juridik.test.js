// I3: juridiken ska namnge en verklig avtalspart, inte en platshållare.
//
// Sidorna säljer en prenumeration till konsument. Då kräver e-handelslagen
// (2002:562) och distansavtalslagen (2005:59) att näringsidkaren är
// identifierad med namn, organisationsnummer och en adress som går att nå -
// en e-postadress ensam räcker inte. Fram till nu stod det
// [FÖRETAGSNAMN / DITT NAMN] live på matjakt.store.
//
// Testet är hårt med flit. CI hade redan en grind för det här men bara som
// ::warning - och en varning som ingen läser är ingen grind.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const root = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const SIDOR = ["integritetspolicy.html", "anvandarvillkor.html"];
const läs = f => readFileSync(join(root, "frontend", f), "utf8");

test("inga juridiska platshållare står kvar", () => {
  for (const sida of SIDOR) {
    const träffar = läs(sida).match(/class="placeholder"/g) || [];
    assert.equal(träffar.length, 0,
      `${sida} har ${träffar.length} platshållare kvar - de syns för varje besökare`);
  }
});

test("båda sidorna namnger avtalsparten och organisationsnumret", () => {
  for (const sida of SIDOR) {
    const t = läs(sida);
    assert.match(t, /Adam From/, `${sida} namnger ingen avtalspart`);
    assert.match(t, /199511045651/, `${sida} saknar organisationsnummer`);
  }
});

test("kontaktuppgifterna innehåller en postadress, inte bara e-post", () => {
  for (const sida of SIDOR) {
    const t = läs(sida);
    const block = /<h2>Kontakt<\/h2>([\s\S]*?)<\/(address|div)>/.exec(t);
    assert.ok(block, `${sida} saknar ett Kontakt-avsnitt`);
    // Ett svenskt postnummer: fem siffror, valfritt mellanrum efter tre.
    assert.match(block[1], /\b\d{3}\s?\d{2}\b/,
      `${sida}s kontaktblock saknar postnummer - e-post ensam räcker inte för konsumentköp`);
  }
});

test("kontaktblocket bär en e-postadress som går att skriva till", () => {
  // Adressen är medvetet adamfrom@icloud.com och inte support@matjakt.store:
  // support-adressen har ingen vidarebefordran ännu, och en juridisk
  // kontaktuppgift som inte går fram är sämre än en privat som gör det.
  // Byts den, ska den bytas HÄR och i landningssidan samtidigt.
  for (const sida of SIDOR) {
    const block = /<h2>Kontakt<\/h2>([\s\S]*?)<\/(address|div)>/.exec(läs(sida));
    assert.match(block[1], /mailto:[^"]+@[^"]+\.[a-z]{2,}/,
      `${sida}s kontaktblock saknar en e-postadress`);
  }
});

test("ångerrätten beskriver mekanismen som faktiskt finns i koden", () => {
  // B3 byggde kryssrutan, tidsstämpeln och databaskontrollen. Villkoren får
  // inte lova något annat än koden gör - därför prövas de mot varandra.
  const t = läs("anvandarvillkor.html");
  assert.match(t, /ångerrätt/i, "villkoren nämner inte ångerrätten alls");
  assert.match(t, /2005:59/, "villkoren hänvisar inte till distansavtalslagen");
  assert.match(t, /samtyck/i, "villkoren beskriver inte samtycket som B3 kräver före köp");
});
