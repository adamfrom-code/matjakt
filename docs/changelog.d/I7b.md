---
paket: I7b
titel: Sexton händelsenamn tappades tyst — nu läses listan ur appen
---

`_handle_analytics_event` svarar `400 Okänt event` på allt som inte står i
`ANALYTICS_EVENTS`, och `trackEvent()` i appen sväljer varje fel med flit —
mätning får aldrig fälla ett klick. Summan av de två är att ett namn som
glidit isär försvinner **tyst**: knappen fungerar, siffran blir aldrig till,
och ingenting i appen säger ifrån.

I7 lagade precis det här felet för tre vyer och skrev en kommentar om det i
koden. Det hade hänt igen, på sexton ställen.

## Vad som saknades

Fyra genvägar, som alla byggdes för att kunna mätas och sedan inte gick att
utvärdera — man såg att raden ritades ut, aldrig att någon tryckte på den:

| Namn | Mäter |
|---|---|
| `byte_avsikt_last` | låst bytesavsikt trycktes → betalväggen; vilken avsikt som säljer Premium |
| `hushall_fran_handla` | "Handlar ni ihop? Dela listan" på Handla → hushållspanelen |
| `postnummer_fran_handla` | "Ange postnummer för priserna i din butik" på Handla → veckoarket |
| `veckotyp_fran_vecka` | "Vill du ha en familjevecka i stället?" på Vecka → planjämförelsen |

Och tolv till som ingen letat efter, båda av samma sort som I7:s tre: ett
namn som byggs av en variabel och därför inte står som text någonstans.
`setView("settings")` skickade **`view_settings`** från den dag G11 gav
Inställningar en egen flik. Inställningsskärmen skickar dessutom
`installning_<rad>` för **var och en av sina elva rader** — `personer`,
`hushall`, `kost`, `budget`, `middagar`, `butik`, `postnummer`, `konto`,
`prenumeration`, `notiser`, `integritet`. Skärmen samlar inställningarna på
ett ställe just för att det ska gå att se vilka som faktiskt används. Den
mätte ingenting alls.

## Vad som gäller nu

Alla sexton står i `ANALYTICS_EVENTS`, var och en med en kommentar om vad den
mäter.

Men den viktiga delen är att listan inte längre hänger på att någon minns.
`backend/tests/test_analytics_handelsenamn.py` **läser namnen ur
`frontend/app/`** och kräver att varje namn appen skickar finns i listan.
Kontrollen går bara åt ett håll: `checkout_avbruten` och `mail_klick` har
medvetet sina namn i listan innan de har någon avsändare (se I7), och de
flesta händelserna i betalsteget skickas av servern.

Tre saker gör att kontrollen inte kan bli grön av att den tappat greppet om
källan, vilket är hela skillnaden mot att bara läsa strängar:

- **Argumenten läses tecken för tecken**, inte med ett uttryck som gissar på
  närmaste parentes. Definitionen `function trackEvent(name)` räknas inte som
  en avsändare, standardvärdena `trackEvent: () => {}` i vymodulerna inte
  heller.
- **Ett anrop testet inte kan tyda failar** i stället för att hoppas över.
  Annars vore det fritt fram att smyga förbi kontrollen med en ny sorts
  argument — vilket är precis vad de två dynamiska avsändarna gjorde.
- **De dynamiska namnen expanderas mot värdemängden i källan**: vyerna ur
  `setView()`/`goToView()` och bottennavets `data-view`, raderna ur
  `rad({ id: ... })`. Båda avläsningarna har ett golv, så en avläsning som
  slutat matcha fäller testet i stället för att tyst räkna noll namn.

Och kontrollen stannar inte vid att läsa en mängd. Samma fil startar servern
och **postar varje namn appen skickar** till `/api/analytics/event`, med krav
på 200. Det var 400:an som tappade siffran, och ett test som bara jämför
strängar hade fortsatt vara grönt om vägen fick en andra grind. Ett påhittat
namn måste fortfarande ge 400 — att laga glappet får inte bli att öppna vägen
för fritext.

Prövat: utan fixen listar den statiska kontrollen alla sexton namnen med fil
och radnummer, och HTTP-kontrollen svarar `400 Okänt event` på var och en —
samma rad som stod i produktionsloggen. Med en trasig vyavläsning fäller
golvet; med en okänd inflikning i mallen fäller kontrollen och säger var
avläsningen ska läggas till.
