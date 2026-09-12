// Vilken sorts rätt ett recept UTAN foto är - etiketten på reservkortet.
//
// Elva av receptbankens 240 rätter är husmanskost utan licensierad bild. En
// påhittad stockbild vore värre än ingen alls: fel maträtt på fel recept
// läser som en bugg och bryter löftet att allt appen visar är sant. I
// stället får kortet en etikett som säger vad rätten ÄR - härledd ur
// receptets egen metadata, aldrig gissad.
//
// M2 bytte streckikonen mot ett typografiskt kort (src/views/receptbild.js):
// vid 52 px blev en klubba en ballong och en köttbit en kaffeböna, och en
// ikon man måste gissa på är sämre än rättens eget namn. Sorteringen nedan
// överlevde bytet oförändrad - den var aldrig ikonens logik, den var
// rättens.
//
// Ordningen i kindFor är avsiktlig och testad:
//  - taggar och typ före namnet; de är satta av receptkällan
//  - soppa före vego, annars blir en vegetarisk ärtsoppa "grönt" fastän
//    skålen med ånga säger mer om rätten än ett blad gör
//  - kött före vego i namnsökningen, annars blir "bruna bönor med stekt
//    fläsk" vegetarisk på ordet "bönor"
// Känner vi inte igen rätten blir det "standard" - ingen kategori alls, bara
// ordmärket. Att gissa fel kategori är sämre än att inte gissa alls.

export const RECIPE_FALLBACK_KINDS = ["fisk", "kyckling", "kott", "vego", "soppa", "gryta", "standard"];

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
