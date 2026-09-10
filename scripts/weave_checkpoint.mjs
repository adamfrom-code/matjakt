// Väver ihop docs/changelog.d/<paket-ID>.md till ett avsnitt i CHECKPOINT.md.
//
//   node scripts/weave_checkpoint.mjs                 visa vad som skulle vävas
//   node scripts/weave_checkpoint.mjs --apply "v1.0"  väv in och arkivera
//
// Varför katalogen finns: CHECKPOINT.md är en enda fil som alla vill skriva i.
// Med många parallella agenter blir den en garanterad konflikt - alla lägger
// sitt stycke på samma rad. En ny fil per paket kan git slå ihop utan att
// fråga någon.
//
// Utan --apply skrivs bara resultatet till stdout. Ett släppverktyg som
// ändrar filer som standard är ett verktyg man inte vågar köra för att titta.
import { existsSync, mkdirSync, readdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const FRAGMENT = join(ROOT, "docs", "changelog.d");
const CHECKPOINT = join(ROOT, "CHECKPOINT.md");

// A1 < A2 < A10 < B1: siffran jämförs som tal, inte som text. Annars hamnar
// A10 mellan A1 och A2 och läsordningen blir en annan än arbetsordningen.
function paketOrdning(a, b) {
  const dela = id => {
    const m = /^([A-Za-z]+)(\d+)([a-z]?)$/.exec(id);
    return m ? [m[1], Number(m[2]), m[3]] : [id, 0, ""];
  };
  const [ba, na, sa] = dela(a), [bb, nb, sb] = dela(b);
  return ba.localeCompare(bb, "sv") || na - nb || sa.localeCompare(sb, "sv");
}

export function läsFragment(katalog = FRAGMENT) {
  if (!existsSync(katalog)) return [];
  return readdirSync(katalog)
    .filter(namn => namn.endsWith(".md") && namn !== "README.md")
    .map(namn => {
      const rå = readFileSync(join(katalog, namn), "utf8");
      const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/.exec(rå);
      if (!m) throw new Error(`${namn}: saknar front matter (--- ... ---). Se docs/changelog.d/README.md`);
      const huvud = {};
      for (const rad of m[1].split(/\r?\n/)) {
        const par = /^([a-zA-ZåäöÅÄÖ_]+):\s*(.*)$/.exec(rad.trim());
        if (par) huvud[par[1]] = par[2].trim().replace(/^["']|["']$/g, "");
      }
      for (const krav of ["paket", "titel"]) {
        if (!huvud[krav]) throw new Error(`${namn}: fältet "${krav}" saknas i front matter`);
      }
      const filId = namn.replace(/\.md$/, "");
      if (huvud.paket !== filId) {
        throw new Error(`${namn}: front matter säger paket "${huvud.paket}" men filen heter "${filId}". ` +
                        `Filnamnet är paketets ID - annars kan två paket skriva i samma fil.`);
      }
      return { fil: namn, ...huvud, text: m[2].trim() };
    })
    .sort((a, b) => paketOrdning(a.paket, b.paket));
}

export function väv(fragment, release) {
  if (!fragment.length) return "";
  const datum = new Date().toISOString().slice(0, 10);
  const rader = [`## ${release} — ${datum}`, "",
                 `${fragment.length} paket.`, ""];
  for (const f of fragment) {
    const pr = f.pr ? ` ([#${f.pr}](https://github.com/adamfrom-code/matjakt/pull/${f.pr}))` : "";
    rader.push(`### ${f.paket} · ${f.titel}${pr}`, "", f.text, "");
  }
  return rader.join("\n").replace(/\n{3,}/g, "\n\n").trimEnd() + "\n";
}

function applicera(avsnitt, fragment, release) {
  const gammal = readFileSync(CHECKPOINT, "utf8");
  // Avsnittet läggs efter H1-rubriken och dess ingress, före första H2:an.
  // Nyast överst: den som öppnar filen vill veta vad som gäller nu.
  const första = gammal.search(/^## /m);
  const [huvud, svans] = första === -1 ? [gammal, ""] : [gammal.slice(0, första), gammal.slice(första)];
  writeFileSync(CHECKPOINT, `${huvud.trimEnd()}\n\n${avsnitt}\n${svans}`, "utf8");

  const arkiv = join(FRAGMENT, "arkiv", release.replace(/[^\w.-]+/g, "-"));
  mkdirSync(arkiv, { recursive: true });
  for (const f of fragment) renameSync(join(FRAGMENT, f.fil), join(arkiv, f.fil));
  return arkiv;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const applyIdx = process.argv.indexOf("--apply");
  const fragment = läsFragment();
  if (!fragment.length) {
    console.error("Inga fragment i docs/changelog.d/ - inget att väva.");
    process.exit(0);
  }
  const release = applyIdx === -1 ? "OVÄVD" : (process.argv[applyIdx + 1] || "").trim();
  if (applyIdx !== -1 && !release) {
    console.error("--apply kräver ett releasenamn: node scripts/weave_checkpoint.mjs --apply \"v1.0\"");
    process.exit(1);
  }
  const avsnitt = väv(fragment, release);
  if (applyIdx === -1) {
    process.stdout.write(avsnitt);
    console.error(`\n(${fragment.length} fragment, inget skrivet. Kör med --apply "<release>" för att väva in.)`);
  } else {
    const arkiv = applicera(avsnitt, fragment, release);
    console.error(`${fragment.length} fragment vävda in i CHECKPOINT.md och arkiverade i ${arkiv}`);
  }
}
