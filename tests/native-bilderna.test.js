// Appens egna bilder: ikonen och startskärmen.
//
// `npx cap add ios` lägger in Capacitors egen blå logotyp som appikon. Den
// följer med hela vägen till hemskärmen om ingen byter ut den, och det gör
// ingen förrän någon ser den - projektet byggde och arkiverade en gång med
// Capacitors logotyp utan att något klagade.
//
// Startskärmen bar dessutom kvar den GAMLA paletten. G14 bytte #f6f7f4 mot
// #ECEEEF i capacitor.config.json och manifest.json, men `resources/splash.png`
// rördes inte - den är en bild, inte en färgsträng, så ingen sökning hittade
// den. Resultatet är en söm: iOS visar startskärmen i gammal papperston och
// webbvyn öppnar i ny.
//
// Testet läser PNG-huvudet och den allra första pixeln, utan bildbibliotek.
// Det går: PNG:ens första pixel i första raden saknar både vänstergranne och
// rad ovanför, så varje filtertyp (0-4) lämnar den oförändrad. Den räcker,
// för bakgrunden är en enfärgad yta.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { inflateSync } from "node:zlib";

const rot = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const xcassets = join(rot, "ios/App/App/Assets.xcassets");

// Design D:s papper. Samma värde som --paper i styles.css och som
// backgroundColor i capacitor.config.json - det är hela poängen.
const PAPPER = "#ECEEEF";

// PNG-färgtyp 2 = RGB utan alfakanal. App Store avvisar appikoner med
// alfakanal, och den avvisar dem vid uppladdningen, inte vid granskningen.
const RGB_UTAN_ALFA = 2;

function läsPng(sökväg) {
  const buf = readFileSync(sökväg);
  assert.equal(buf.readUInt32BE(0), 0x89504e47, `${sökväg} är inte en PNG`);

  // IHDR ligger alltid först: längd(4) typ(4) sedan bredd, höjd, djup, färgtyp.
  const bredd = buf.readUInt32BE(16);
  const höjd = buf.readUInt32BE(20);
  const bitdjup = buf[24];
  const färgtyp = buf[25];

  // Samla ihop IDAT-bitarna och packa upp dem.
  const bitar = [];
  let p = 8;
  while (p < buf.length) {
    const längd = buf.readUInt32BE(p);
    const typ = buf.toString("ascii", p + 4, p + 8);
    if (typ === "IDAT") bitar.push(buf.subarray(p + 8, p + 8 + längd));
    if (typ === "IEND") break;
    p += längd + 12;
  }
  const rå = inflateSync(Buffer.concat(bitar));

  // rå[0] är filterbyten för första raden. Pixeln därefter är oförändrad
  // oavsett filter, eftersom den varken har vänstergranne eller rad ovanför.
  const kanaler = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 }[färgtyp];
  const hex =
    "#" +
    [rå[1], rå[2], rå[3]]
      .map((v) => v.toString(16).padStart(2, "0"))
      .join("")
      .toUpperCase();

  return { bredd, höjd, bitdjup, färgtyp, kanaler, förstaPixeln: hex };
}

test("appikonen är Matjakts, inte Capacitors", () => {
  const ikon = läsPng(join(xcassets, "AppIcon.appiconset/AppIcon-512@2x.png"));

  assert.equal(ikon.bredd, 1024, "App Store kräver 1024x1024");
  assert.equal(ikon.höjd, 1024);

  assert.equal(
    ikon.färgtyp,
    RGB_UTAN_ALFA,
    "appikonen har alfakanal - App Store avvisar den vid uppladdningen, " +
      "inte vid granskningen, så felet syns först när bygget redan är klart",
  );

  // Capacitors logotyp är en blå bock på vitt rutnät: hörnpixeln är nästan
  // vit. Matjakts märke är ett mörkgrönt fält som går ut i kanten.
  const [, r, g, b] = ikon.förstaPixeln.match(/#(..)(..)(..)/).map((x, i) => (i ? parseInt(x, 16) : x));
  assert.ok(
    r + g + b < 400,
    `ikonens hörn är ljust (${ikon.förstaPixeln}) - det ser ut som Capacitors ` +
      `standardlogotyp. Kör: npx @capacitor/assets generate --ios --assetPath resources`,
  );
});

test("startskärmen är i design D:s papper, inte den gamla paletten", () => {
  // Både ljus och mörk. Appen renderar ljust oavsett systemläge - mörkt läge
  // ligger bakom ett uttryckligt [data-theme="dark"] och inte bakom
  // prefers-color-scheme (styles.css §9.3) - så en mörk startskärm skulle
  // blinka mörkt och sedan öppna ljust.
  for (const namn of [
    "Default@1x~universal~anyany.png",
    "Default@2x~universal~anyany.png",
    "Default@3x~universal~anyany.png",
    "Default@1x~universal~anyany-dark.png",
    "Default@2x~universal~anyany-dark.png",
    "Default@3x~universal~anyany-dark.png",
  ]) {
    const bild = läsPng(join(xcassets, "Splash.imageset", namn));
    assert.equal(
      bild.förstaPixeln,
      PAPPER,
      `${namn} har bakgrunden ${bild.förstaPixeln}, inte ${PAPPER}. ` +
        `#F6F7F4 är den gamla paletten som G14 bytte bort.`,
    );
  }
});

test("startskärmens bakgrund är samma färg som appen öppnar i", () => {
  // Sömmen: iOS målar backgroundColor bakom startskärmen och webbvyn öppnar
  // i samma färg. Skiljer de sig ser användaren en blink.
  const konfig = JSON.parse(readFileSync(join(rot, "capacitor.config.json"), "utf8"));
  const splash = läsPng(join(xcassets, "Splash.imageset/Default@2x~universal~anyany.png"));

  for (const plattform of ["ios", "android"]) {
    assert.equal(
      konfig[plattform]?.backgroundColor?.toUpperCase(),
      splash.förstaPixeln,
      `capacitor.config.json ${plattform}.backgroundColor skiljer sig från ` +
        `startskärmens bakgrund - det ger en synlig blink vid start`,
    );
  }
});

test("källbilderna i resources/ bär samma papper", () => {
  // Genererade filer skrivs över av nästa `assets generate`. Källan är det
  // som måste vara rätt, annars kommer felet tillbaka.
  for (const namn of ["splash.png", "splash-dark.png"]) {
    const bild = läsPng(join(rot, "resources", namn));
    assert.equal(bild.förstaPixeln, PAPPER, `resources/${namn}`);
    assert.equal(bild.bredd, 2732, `resources/${namn} ska vara 2732x2732`);
  }
  const ikon = läsPng(join(rot, "resources/icon-only.png"));
  assert.equal(ikon.bredd, 1024);
  assert.equal(ikon.färgtyp, RGB_UTAN_ALFA, "resources/icon-only.png har alfakanal");
});
