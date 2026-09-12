---
paket: N0i
titel: Signeringsinställningarna som fick bygget att gå igenom
---

`DEVELOPMENT_TEAM = 8MP23RQTPV` på båda konfigurationerna, och
`CODE_SIGN_IDENTITY` bytt från Capacitors mallvärde `"iPhone Developer"`
till `"Apple Development"`.

Utan team-ID svarar `xcodebuild` *"Signing for App requires a development
team"* även med en giltig API-nyckel — automatisk signering vet inte vilket
team den ska be Apple om ett certifikat för. Team-ID är ingen hemlighet; det
syns i varje utgiven `.ipa`.

Testet vaktar också det motsatta felet: **sätt inte distributionsidentiteten
här.** Det ser ut som lösningen och ger *"conflicting provisioning
settings"* — automatisk signering accepterar ingen manuell identitet.
Distributionen bestäms av exportsteget.