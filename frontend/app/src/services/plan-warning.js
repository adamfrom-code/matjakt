// Säg när kraven inte går ihop (U17).
//
// VARFÖR DEN HÄR FINNS. bestMenuCombo returnerar allt den har när
// kandidaterna är färre än antalet middagar - utan ett ord. Den som ber om
// sju middagar och får fem tror att appen är trasig. Den enda text som
// fanns gällde näringsmål; kostkrav och receptutbud var tysta.
//
// ALLERGIER ÄR INTE FÖRHANDLINGSBARA. Förslagen får nämna färre middagar,
// färre ogillade råvaror eller en bredare kosttyp - aldrig att stänga av
// en allergi. Att ens antyda det vore att be någon riskera sin hälsa för
// en vecka mat, och det säger kravet uttryckligen ifrån om.

export const NUTRITION_TEXT =
  "Dina näringsmål matchade för få recept den här veckan, så vi visar de " +
  "närmaste alternativen istället. Testa att justera målen om du vill ha en bättre träff.";

function förslag({ kosttyp, allergener, ogillar }) {
  const ut = ["välja färre middagar"];
  if (ogillar) ut.push("ta bort någon råvara du valt bort");
  // Kosttyp är ett VAL och får föreslås. Allergener är det inte, och
  // nämns bara som en förklaring till varför utbudet är litet.
  if (kosttyp) ut.push("bredda kosttypen");
  return ut;
}

function orsaker({ kosttyp, allergener, ogillar }) {
  const ut = [];
  if (kosttyp) ut.push(kosttyp);
  if (allergener) ut.push(`${allergener} allergi${allergener > 1 ? "er" : ""} att undvika`);
  // "råvara" i plural är "råvaror", inte "råvara" + "or". Första utkastet
  // skrev "9 bortvalda råvaraor" rakt i ansiktet på användaren.
  if (ogillar) ut.push(ogillar > 1 ? `${ogillar} bortvalda råvaror` : "1 bortvald råvara");
  return ut;
}

export function planWarning({ önskade = 0, fick = 0, nutritionShortfall = false,
                              kosttyp = "", allergener = 0, ogillar = 0, utbud = null } = {}) {
  // INGET UTBUD ÄN ÄR INTE SAMMA SAK SOM INGA TRÄFFAR. Under uppstart, innan
  // receptbanken hämtats, är kandidaterna noll av rent tekniska skäl - och
  // då sattes texten "Inga rätter klarar dina krav" i elementet. Den var
  // dold just då, men en skrämmande mening som kan blinka förbi under
  // laddning är fel sorts ärlighet.
  if (utbud === 0) return "";
  // NOLL RÄTTER ÄR DET VÄRSTA FALLET, inte ett undantag att tiga om.
  // Första utkastet lät en tom vecka passera tyst med motiveringen "då är
  // felet ett annat" - och det testet fastställde min egen kod i stället
  // för vad användaren behöver. En tom skärm utan förklaring får appen att
  // se trasig ut just när den i själva verket lyder användarens krav.
  if (önskade > 0 && fick === 0) {
    const varför = orsaker({ kosttyp, allergener, ogillar });
    return (varför.length
      ? `Inga rätter klarar dina krav (${varför.join(", ")}).`
      : "Vi hittade inga rätter till veckan just nu.")
      + ` Prova att ${förslag({ kosttyp, allergener, ogillar }).join(", ")}`
      + `${allergener ? " - dina allergier rör vi inte" : ""}.`;
  }
  if (fick > 0 && fick < önskade) {
    const varför = orsaker({ kosttyp, allergener, ogillar });
    const mening = varför.length
      ? `Dina krav (${varför.join(", ")}) lämnar för få recept för ${önskade} middagar.`
      : `Receptutbudet räcker inte till ${önskade} middagar just nu.`;
    return `${mening} Du fick ${fick}. Prova att ${förslag({ kosttyp, allergener, ogillar }).join(", ")}` +
           `${allergener ? " - dina allergier rör vi inte" : ""}.`;
  }
  if (nutritionShortfall) return NUTRITION_TEXT;
  return "";
}
