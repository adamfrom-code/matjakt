// Kör ett Python-skript med den tolk som finns på den här maskinen.
//
//   node scripts/py.mjs backend/api_server.py
//   node scripts/py.mjs -m compileall -q backend
//
// VARFÖR. npm-skripten anropade `python`, och det namnet finns inte överallt:
// macOS har bara `python3` sedan Apple tog bort Python 2, medan Windows och
// CI:s setup-python ger `python`. Samma package.json kan alltså inte hårdkoda
// vare sig det ena eller det andra - `npm run frontend` dog med "python:
// command not found" på Macen medan det fungerade på Windows.
//
// Ordningen är python3 först: där båda finns pekar python3 alltid på Python 3,
// medan `python` historiskt kunnat vara Python 2. Hittas ingen tolk avslutar
// vi med ett begripligt fel i stället för ett nakent ENOENT.

import { spawnSync } from "node:child_process";

const KANDIDATER = ["python3", "python"];

function hittaTolk() {
  for (const namn of KANDIDATER) {
    // --version är ofarligt och svarar snabbt; finns inte binären får vi
    // error (ENOENT) i stället för en statuskod.
    const test = spawnSync(namn, ["--version"], { stdio: "ignore" });
    if (!test.error && test.status === 0) return namn;
  }
  return null;
}

const tolk = hittaTolk();
if (!tolk) {
  console.error(`Hittade ingen Python-tolk (letade efter: ${KANDIDATER.join(", ")}).`);
  console.error("Installera Python 3.10 eller senare och se till att den ligger i PATH.");
  process.exit(127);
}

// --env KEY=VALUE före skriptnamnet sätter miljövariabler portabelt. Utan det
// måste launch.json välja skal - `$env:X='1'; ...` på PowerShell mot `X=1 ...`
// på sh - och en sådan rad startar bara på den ena plattformen.
const argv = process.argv.slice(2);
const env = { ...process.env };
while (argv[0] === "--env") {
  const par = argv[1] ?? "";
  const delare = par.indexOf("=");
  if (delare < 1) {
    console.error(`--env vill ha KEY=VALUE, fick: ${par}`);
    process.exit(2);
  }
  env[par.slice(0, delare)] = par.slice(delare + 1);
  argv.splice(0, 2);
}

const resultat = spawnSync(tolk, argv, { stdio: "inherit", env });
if (resultat.error) {
  console.error(`Kunde inte starta ${tolk}: ${resultat.error.message}`);
  process.exit(127);
}
// Signalavslut (t.ex. Ctrl+C på en dev-server) har status null - då är 130 det
// som skalet självt hade rapporterat, inte 0.
process.exit(resultat.status === null ? 130 : resultat.status);
