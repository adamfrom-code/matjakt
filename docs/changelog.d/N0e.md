### Appens egna bilder

Appikonen var **Capacitors blå logotyp**. `npx cap add ios` lägger in den, och
den följer med till hemskärmen om ingen byter ut den — projektet hann bygga
och arkivera en gång utan att något klagade.

Startskärmen bar kvar den gamla paletten. G14 bytte `#f6f7f4` mot `#ECEEEF`
i `capacitor.config.json` och `manifest.json`, men `resources/splash.png`
rördes inte: den är en bild, inte en färgsträng, så ingen sökning hittade
den. Resultatet var en söm — iOS visade startskärmen i gammal papperston och
webbvyn öppnade i ny.

Den mörka startskärmen är nu identisk med den ljusa. Appen renderar ljust
oavsett systemläge, så en mörkgrön startskärm blinkade mörkt och öppnade
ljust. När `prefers-color-scheme` kopplas in (§9.3) ska den genereras om
mot `--paper:#111416`.
