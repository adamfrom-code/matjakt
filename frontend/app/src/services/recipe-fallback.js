// Vilken sorts rätt ett recept UTAN foto ska visa som ikon.
//
// 31 av receptbankens 240 rätter är husmanskost utan licensierad bild. En
// påhittad stockbild vore värre än ingen alls: fel maträtt på fel recept
// läser som en bugg och bryter löftet att allt appen visar är sant. I
// stället får kortet en ikon som säger vad rätten ÄR - härlett ur receptets
// egen metadata, aldrig gissat.
//
// Ordningen i kindFor är avsiktlig och testad:
//  - taggar och typ före namnet; de är satta av receptkällan
//  - soppa före vego, annars blir en vegetarisk ärtsoppa "grönt" fastän
//    skålen med ånga säger mer om rätten än ett blad gör
//  - kött före vego i namnsökningen, annars blir "bruna bönor med stekt
//    fläsk" vegetarisk på ordet "bönor"
// Känner vi inte igen rätten blir det "standard" - den neutrala karotten.
// Att gissa fel kategori är sämre än att inte gissa alls.

export const RECIPE_FALLBACK_KINDS = ["fisk", "kyckling", "kott", "vego", "soppa", "gryta", "standard"];

// Karotten är grundmarkeringen. Fyra sorter har en egen form som faktiskt
// läser som det den föreställer; kött och kyckling delar karotten med
// varsin ton och etikett. Anledningen är enkel: en klubba och en köttbit
// blev inte läsbara i den här streckstilen vid 52 px - de såg ut som en
// ballong respektive en kaffeböna - och en ikon man måste gissa på är
// sämre än en ren neutral. Ton och text bär skillnaden i stället.
const KAROTT = '<path d="M14 48h36M18 44a14 14 0 0 1 28 0M32 20v10M27 20h10"/>';

export const RECIPE_FALLBACK_ART = {
  fisk: '<path d="M8 32c8-10 18-16 28-16s18 7 21 16c-3 9-11 16-21 16S16 42 8 32Z"/><path d="M8 32 18 24v16Z"/><circle cx="44" cy="27" r="2.2"/>',
  kyckling: KAROTT,
  kott: KAROTT,
  vego: '<path d="M32 54V30"/><path d="M32 32c0-11 9-20 22-20 0 13-9 22-22 22Z"/><path d="M32 42c0-8-7-15-17-15 0 10 8 16 17 16Z"/>',
  soppa: '<path d="M10 30h44a22 22 0 0 1-22 22 22 22 0 0 1-22-22Z"/><path d="M24 21c0-4 4-5 4-8M32 19c0-4 4-5 4-8M40 21c0-4 4-5 4-8"/>',
  gryta: '<path d="M14 28h36v8a18 18 0 0 1-18 18 18 18 0 0 1-18-18Z"/><path d="M8 28h48M22 21c0-4 4-7 10-7s10 3 10 7"/>',
  standard: KAROTT,
};

export const RECIPE_FALLBACK_LABEL = {
  fisk: "Fisk", kyckling: "Kyckling", kott: "Kött", vego: "Grönt",
  soppa: "Soppa", gryta: "Gryta", standard: "Matjakt",
};

const NAME_HINTS = [
  ["fisk", /lax|torsk|sill|fisk|räk|skaldjur|musslor|makrill|strömming/i],
  ["kyckling", /kyckling|fågel|kalkon|flygande jacob/i],
  ["kott", /kött|biff|fläsk|karré|korv|isterband|stek|bacon|skinka|lamm|palt|pudding/i],
  ["gryta", /gryta|stroganoff|wok|curry|gratäng|form|pannkaka/i],
  ["vego", /vego|vegetarisk|halloumi|kikärt|linser|bön|tofu|falafel/i],
];

export function kindFor(recipe) {
  const tags = (recipe?.tags || recipe?.taggar || []).map(tag => String(tag).toLowerCase());
  const typ = String(recipe?.typ || "").toLowerCase();
  const namn = String(recipe?.namn || "");
  if (tags.includes("fisk") || typ.includes("fisk")) return "fisk";
  if (tags.includes("kyckling") || typ.includes("kyckling")) return "kyckling";
  if (typ.includes("soppor") || typ.includes("soppa") || /soppa|minestrone/i.test(namn)) return "soppa";
  if (tags.includes("vegetariskt") || tags.includes("vego") || typ.includes("vegetarisk")) return "vego";
  if (typ.includes("gryt")) return "gryta";
  if (tags.includes("kott") || typ.includes("kött")) return "kott";
  for (const [kind, pattern] of NAME_HINTS) if (pattern.test(namn)) return kind;
  return "standard";
}
