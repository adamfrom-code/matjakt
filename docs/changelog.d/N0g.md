### Distributionspasset

`scripts/ios_testflight.sh` arkiverar och laddar upp till TestFlight i ett
kommando. Systerskript till `ios_mac_pass.sh`, som gör simulatorpasset.

De tre App Store Connect-värdena läses ur miljön, aldrig ur argument —
argument syns i `ps` för varje användare på maskinen. Skriptet vägrar starta
om `.p8`-filen ligger inuti repot, och nyckelns innehåll skrivs aldrig ut.

`ios/ExportOptions.plist` är spårad med flit: den innehåller ingen hemlighet
och den som klonar repot ska kunna bygga utan att gissa sig till innehållet.
