// Signeringsinställningarna som fick bygget att gå igenom.
//
// Det tog fyra körningar att hitta dem, och varje felmeddelande på vägen
// pekade åt fel håll. Testet finns för att ingen ska behöva gå de fyra
// varven igen - och för att `npx cap add ios` skriver om projektet från
// Capacitors mall om katalogen någonsin tas bort.
//
// DEVELOPMENT_TEAM saknades helt. Utan den svarar xcodebuild "Signing for
// App requires a development team" även med en giltig API-nyckel:
// automatisk signering vet inte VILKET team den ska be Apple om ett
// certifikat för. Team-ID är ingen hemlighet - det syns i varje utgiven
// .ipa - så det hör hemma i projektet.
//
// CODE_SIGN_IDENTITY stod på "iPhone Developer" i BÅDA konfigurationerna.
// Det är Capacitors mallvärde och det gamla namnet på
// utvecklingsidentiteten. Namnet i sig är inte felet - felet vore att sätta
// distributionsidentiteten här för hand, vilket ger "conflicting
// provisioning settings" eftersom automatisk signering inte accepterar en
// manuell identitet. Distributionen bestäms av exportsteget.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const rot = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const pbxproj = readFileSync(
  join(rot, "ios/App/App.xcodeproj/project.pbxproj"),
  "utf8",
);

// Läst ur seedId på bundle-ID:t se.matjakt.app i App Store Connect.
const TEAM = "8MP23RQTPV";

function värden(nyckel) {
  return [...pbxproj.matchAll(new RegExp(`${nyckel} = ([^;]+);`, "g"))].map((m) =>
    m[1].trim().replace(/^"|"$/g, ""),
  );
}

test("projektet vet vilket team det signerar för", () => {
  const team = värden("DEVELOPMENT_TEAM");
  assert.ok(
    team.length >= 2,
    `DEVELOPMENT_TEAM saknas eller står bara på en konfiguration (hittade ${team.length}). ` +
      `Utan den svarar xcodebuild "Signing for App requires a development team" ` +
      `även med en giltig API-nyckel.`,
  );
  for (const t of team) assert.equal(t, TEAM);
});

test("signeringen är automatisk", () => {
  const stil = värden("CODE_SIGN_STYLE");
  assert.ok(stil.length >= 2, "CODE_SIGN_STYLE saknas");
  for (const s of stil) {
    assert.equal(
      s,
      "Automatic",
      "manuell signering kräver att certifikat och profiler finns i " +
        "nyckelringen i förväg; den här maskinen hade inga",
    );
  }
});

test("ingen distributionsidentitet står satt för hand", () => {
  // Att sätta "Apple Distribution" här ser ut som lösningen och är fällan:
  // automatisk signering vägrar en manuellt angiven identitet.
  // -exportArchive med method=app-store-connect signerar om appen ändå.
  for (const id of värden("CODE_SIGN_IDENTITY")) {
    assert.ok(
      !/Distribution/i.test(id),
      `CODE_SIGN_IDENTITY = "${id}" ger "conflicting provisioning settings". ` +
        `Distributionen bestäms av exportsteget, inte av projektet.`,
    );
  }
});

test("bundle-ID:t är det som finns i App Store Connect", () => {
  const id = värden("PRODUCT_BUNDLE_IDENTIFIER");
  assert.ok(id.length >= 2);
  for (const b of id) assert.equal(b, "se.matjakt.app");
});

test("versionen står på båda konfigurationerna", () => {
  // Skiljer de sig signerar arkivet en annan version än den som testats.
  const marknad = värden("MARKETING_VERSION");
  const bygge = värden("CURRENT_PROJECT_VERSION");
  assert.ok(marknad.length >= 2 && bygge.length >= 2);
  assert.equal(new Set(marknad).size, 1, `MARKETING_VERSION skiljer sig: ${marknad}`);
  assert.equal(new Set(bygge).size, 1, `CURRENT_PROJECT_VERSION skiljer sig: ${bygge}`);
});
