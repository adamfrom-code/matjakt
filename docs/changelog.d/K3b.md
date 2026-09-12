---
paket: K3b
titel: Hälsogrinden hoppades över vid varje merge
---

K3 stängde racet där ny frontend kunde gå live mot gammal backend: efter att
backenden deployats pollar `health-gate` `/api/health` tills `commit` matchar
committen, och först när HELA CI-körningen är grön får Pages publicera.

Grinden var villkorad på `needs.deploy-backend.outputs.triggad == 'true'` —
alltså *"bara om vi startade deployen"*. `RENDER_DEPLOY_HOOK` lades aldrig in
i repots secrets, så flaggan var alltid `false` och grinden hoppades över vid
**varje** merge. Tyst, som `skipped`, vilket ser ut precis som ett jobb som
inte behövdes.

Frontenden deployade alltså utan att någon kontrollerat att backenden var
uppe med samma commit. Racet var öppet igen.

Det som döljer felet är att Render deployar av sig självt — Auto-Deploy
"After CI Checks Pass" står påslaget i dashboarden — så committen når
produktionen ändå. Vi vet bara inte när. Grindens fråga är *"kör driften den
här committen"*, inte *"startade vi en deploy"*, och den frågan är lika
giltig oavsett vem som tryckte på knappen. Villkoret är därför samma som för
`deploy-backend`: varje push till main.

Fail-closed med avsikt: kommer committen inte upp inom åtta minuter blir CI
röd och frontenden står kvar. Gammal frontend mot gammal backend är ett par
som har fungerat.

De fyra befintliga testerna i `test_deploy_ordning.py` var gröna hela tiden —
en överhoppad grind finns i filen, behöver `deploy-backend` och anropar rätt
skript. Det nya testet läser grindens `if:` och kräver att det varken nämner
`triggad` eller saknar `main`. Prövat åt båda hållen: med det gamla villkoret
tillbaka failar det.
