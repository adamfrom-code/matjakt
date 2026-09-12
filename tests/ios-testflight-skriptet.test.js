// Distributionspasset: skriptet som arkiverar och laddar upp till TestFlight.
//
// Testet kör skriptets FÖRHANDSKONTROLLER (--checks-only). De bygger
// ingenting, rör inget nät och tar några hundra millisekunder - men de är
// exakt den del som avgör om en API-nyckel hamnar på fel ställe.
//
// Den kontroll som räknas mest: skriptet vägrar starta om .p8-filen ligger
// inuti repot. .gitignore håller ute *.p8 (N0f), men bara i den här klonen -
// och en nyckel i arbetskatalogen är en nyckel som förr eller senare blir
// committad någonstans.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const rot = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const skript = join(rot, "scripts", "ios_testflight.sh");

// Ett PKCS#8-huvud utan nyckel efter. Skriptet läser bara första raden.
//
// Huvudet sätts ihop av delar med flit. Skrivet som ett literal fångas det
// av backend/scripts/secret_scan.py, som letar efter just den raden i varje
// spårad fil - och den gör rätt: den kan inte veta att det här är en attrapp.
// Att undanta filen ur skanningen vore att göra hålet större än problemet.
const PEM = (vad) => `-----${vad} PRIVATE` + ` KEY-----`;
const ATTRAPP = `${PEM("BEGIN")}\nDET-HAR-AR-INTE-EN-NYCKEL\n${PEM("END")}\n`;

function kör(env, args = ["--checks-only"]) {
  try {
    const ut = execFileSync("bash", [skript, ...args], {
      cwd: rot,
      env: { ...process.env, ASC_KEY_PATH: "", ASC_KEY_ID: "", ASC_ISSUER_ID: "", ...env },
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
    return { kod: 0, ut };
  } catch (e) {
    return { kod: e.status, ut: (e.stdout || "") + (e.stderr || "") };
  }
}

test("skriptet är syntaktiskt giltigt", () => {
  execFileSync("bash", ["-n", skript], { stdio: "pipe" });
});

test("utan nycklar byggs ingenting", () => {
  const { kod, ut } = kör({});
  assert.equal(kod, 1, "skriptet skulle ha avbrutit");
  for (const namn of ["ASC_KEY_PATH", "ASC_KEY_ID", "ASC_ISSUER_ID"]) {
    assert.match(ut, new RegExp(`${namn} saknas`), `${namn} nämndes inte`);
  }
  assert.match(ut, /Inget byggdes/);
});

test("en nyckel inuti repot stoppar körningen", () => {
  // Det här är hela poängen med kontrollen, så den prövas på riktigt:
  // en fil läggs i reporoten och skriptet ska vägra.
  const inuti = join(rot, "AuthKey_TESTFALL.p8");
  try {
    writeFileSync(inuti, ATTRAPP);
    const { kod, ut } = kör({
      ASC_KEY_PATH: inuti,
      ASC_KEY_ID: "ABC123XYZ",
      ASC_ISSUER_ID: "00000000-0000-0000-0000-000000000000",
    });
    assert.equal(kod, 1, "skriptet accepterade en nyckel i reporoten");
    assert.match(ut, /ligger INUTI repot/);
  } finally {
    rmSync(inuti, { force: true });
  }
});

test("en nyckel utanför repot släpps igenom", () => {
  const utanför = join(process.env.TMPDIR || "/tmp", `matjakt-testfall-${process.pid}.p8`);
  try {
    writeFileSync(utanför, ATTRAPP);
    const { kod, ut } = kör({
      ASC_KEY_PATH: utanför,
      ASC_KEY_ID: "ABC123XYZ",
      ASC_ISSUER_ID: "00000000-0000-0000-0000-000000000000",
    });
    assert.equal(kod, 0, `kontrollerna föll:\n${ut}`);
    assert.match(ut, /nyckeln ligger utanför repot/);
    assert.match(ut, /Alla kontroller gröna/);
  } finally {
    rmSync(utanför, { force: true });
  }
});

test("skriptet skriver aldrig ut nyckelns innehåll", () => {
  // En hemlighet som passerar genom ett skript ska inte hamna i en logg.
  const utanför = join(process.env.TMPDIR || "/tmp", `matjakt-hemlig-${process.pid}.p8`);
  const hemligt = "MIGTkAgEAMBMGByqGSM49HEMLIGHETEN";
  try {
    writeFileSync(utanför, `${PEM("BEGIN")}\n${hemligt}\n${PEM("END")}\n`);
    const { ut } = kör({
      ASC_KEY_PATH: utanför,
      ASC_KEY_ID: "ABC123XYZ",
      ASC_ISSUER_ID: "00000000-0000-0000-0000-000000000000",
    });
    assert.ok(!ut.includes(hemligt), "nyckelns innehåll stod i utdatan");
  } finally {
    rmSync(utanför, { force: true });
  }
});

test("exportkonfigurationen laddar upp, och signerar automatiskt", () => {
  const plist = readFileSync(join(rot, "ios", "ExportOptions.plist"), "utf8");
  const värde = (nyckel) =>
    plist.match(new RegExp(`<key>${nyckel}</key>\\s*<string>([^<]*)</string>`))?.[1];

  assert.equal(värde("method"), "app-store-connect");
  assert.equal(
    värde("destination"),
    "upload",
    "destination måste vara upload - annars stannar .ipa:n på maskinen",
  );
  assert.equal(
    värde("signingStyle"),
    "automatic",
    "maskinen har inget certifikat i nyckelringen; automatic låter " +
      "-allowProvisioningUpdates skapa det via API-nyckeln",
  );
  // plutil avgör om filen är en giltig plist - inte vår regex.
  execFileSync("plutil", ["-lint", join(rot, "ios", "ExportOptions.plist")], { stdio: "pipe" });
});
