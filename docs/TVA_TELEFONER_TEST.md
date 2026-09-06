# Två telefoner, två konton — testplan för hushållet

Att köra efter att PR:en är öppnad och innan hushållet släpps skarpt.
Automatiken täcker att reglerna HÅLLER; det här passet täcker det den inte
kan svara på: hur det **känns**, och hur lång fördröjningen faktiskt är.

Räkna med 20–30 minuter.

## Innan du börjar

| | |
|---|---|
| Telefon A | Adam, eget konto |
| Telefon B | testkonto (t.ex. `adam+sara@…`) |
| Nät | båda på mobildata, inte samma wifi — det är så familjen faktiskt handlar |
| Bygge | samma version på båda; kontrollera versionsraden i Konto |

Hushållet synkas var 20:e sekund **när appen är synlig**, plus direkt efter
varje egen ändring och när appen kommer tillbaka från bakgrunden. Den
förväntade fördröjningen är därför **0–20 sekunder**, inte omedelbar.
Skriv upp vad du faktiskt ser — det är hela poängen med det här passet.

## Steg

Kryssa av, och notera fördröjning där det står _(tid)_.

### 1. Invite

- [ ] A: Konto → Mitt hushåll → skriv namn → **Skapa hushåll**
- [ ] A: **Bjud in** → dela länken till telefon B (SMS är den realistiska vägen)
- [ ] B: öppna länken **utan att vara inloggad först**
- [ ] B: står det *"Adam har bjudit in dig till …"* med bara ett namn och en knapp?
- [ ] B: logga in / skapa konto → **Gå med**
- [ ] A: syns den nya medlemmen i medlemslistan? _(tid: ____ s)_

> Länken gäller i 72 timmar och **en gång**. Prova gärna att öppna samma
> länk igen på B — den ska säga att inbjudan inte gäller längre.

### 2. Gemensam vecka

- [ ] A: skapa en vecka
- [ ] B: öppna Vecka — samma middagar? _(tid: ____ s)_
- [ ] B: byt en rätt (Byt rätt → någon avsikt)
- [ ] A: syns bytet? _(tid: ____ s)_

### 3. Lägga till en vara

- [ ] B: Handla → *Lägg till vara* → t.ex. `kaffe`
- [ ] A: dyker kaffet upp i listan? _(tid: ____ s)_
- [ ] A: hamnar det under rätt rubrik (Skafferi)?

### 4. Har hemma

- [ ] A: tryck **Har hemma** på en vara
- [ ] A: försvinner den ur listan och dyker upp under *Klart*?
- [ ] A: ligger den i Skafferi/Kyl?
- [ ] B: ser B samma sak? _(tid: ____ s)_

### 5. Köpt

- [ ] B: tryck **Köpt** på tre varor i rad
- [ ] A: går antalet kvar ner med tre? _(tid: ____ s)_
- [ ] A: ligger de tre i skafferiet?
- [ ] A: får A **en** notis om tre varor — inte tre notiser?

### 6. Ångra

- [ ] A: tryck **Har hemma** på en vara och sedan **Ångra** i remsan
- [ ] A: är varan tillbaka i listan?
- [ ] A: är den **borta** ur skafferiet igen?
- [ ] Gör om det på en vara som **redan fanns** i skafferiet innan: efter
      Ångra ska den ligga kvar hemma. Detta är det viktigaste steget i hela
      planen — här får familjens riktiga vara inte försvinna.

### 7. Skafferi

- [ ] B: Skafferi → **+ Lägg till** → sök `mjölk`
- [ ] B: går det att välja både en riktig produkt och *"generell vara"*?
- [ ] B: visar den riktiga produkten bild, märke och förpackning?
- [ ] B: visar den generella varan **inget påhittat märke**?
- [ ] A: syns tillägget? _(tid: ____ s)_
- [ ] A: justera antalet med − / + → syns det hos B? _(tid: ____ s)_

### 8. Bakgrund och återkomst

- [ ] A: lägg appen i bakgrunden (hemknapp), vänta 2 minuter
- [ ] B: gör tre ändringar under tiden
- [ ] A: öppna appen igen — kommer alla tre ändringarna? _(tid: ____ s)_
- [ ] A: känns det som att appen "hämtar ikapp" eller som att den redan visste?

### 9. Båda ändrar samtidigt

- [ ] Räkna ner från tre och tryck samtidigt:
      A markerar **en vara** som Köpt, B markerar **en annan** som Har hemma
- [ ] Båda ändringarna kvar hos båda? _(tid: ____ s)_
- [ ] Upprepa på **samma** vara: en av er vinner — men raden ska finnas kvar
      med en av de två statusarna, aldrig försvinna

### 10. Lämna

- [ ] B: Konto → Mitt hushåll → **Lämna hushållet**
- [ ] B: är veckan/listan/skafferiet borta från B:s vy?
- [ ] A: finns allt kvar hos A?
- [ ] B: slutar notiserna?

## Att skriva ner efteråt

```
Upplevd synkfördröjning:   snabbast ___ s   långsammast ___ s   typiskt ___ s
Kändes det snabbt nog?     ja / nej
Något som kändes trasigt:
Något som kändes onödigt:
```

## Kända begränsningar (inte buggar)

- **Ingen push ännu.** Notiser visas som en remsa i appen när den är öppen.
  Push till låst skärm kommer när APNs/FCM är på plats; eventlagret är redan
  byggt för det.
- **20 sekunders poll.** En ändring kan ta upp till 20 sekunder när den andra
  telefonen ligger still med appen öppen. Direkt efter en egen ändring, och
  vid återkomst från bakgrunden, hämtas det direkt.
- **Ett hushåll per konto.** Att gå med i ett nytt kräver att man lämnar det
  gamla först.
- **Offline:** appen fungerar på den egna enhetens data, men ändringar syns
  hos den andra först när nätet är tillbaka.

## Om något går fel

Notera vilket steg, vilken telefon, och vad du såg i stället. Serverloggen
på Render har begäranden med tidsstämpel — en ändring som aldrig kom fram
syns som ett `POST /api/household/...` utan efterföljande `GET
/api/household/sync` hos den andra.
