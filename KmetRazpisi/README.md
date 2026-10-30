# Trenutna različica: 1.3.1

Različica 1.3.1 popravlja zajem: edini začetni vir je uradni seznam SKP, dejanski razpisi pa so povezane strani pod `/zbirke/javne-objave/`. Informativne strani iz starih pregledov ostanejo v bazi, vendar niso več prikazane med razpisi. Ročno dodajanje preveri prisotnost povezave na seznamu SKP.

Različica je prikazana zgoraj desno in ob zagonu v terminalu. Ob njej je stanje prisotnosti API ključa (ne potrjuje veljavnosti ključa). Oznaka načina pri razpisu opisuje zadnjo shranjeno analizo; stari rezultati ostanejo do nove uspešne analize.

# KmetRazpisi – zasebna aplikacija za spremljanje kmetijskih razpisov

Prva delujoča različica za eno mlečno kmetijo. Podatki se hranijo **lokalno** v `kmetrazpisi.sqlite3`.

## Zagon

Potrebujete Python 3.10+ in internetno povezavo za preverjanje virov.

**Windows (PowerShell):**

```powershell
cd KmetRazpisi
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
```

**macOS / Linux:**

```bash
cd KmetRazpisi
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Odprite **http://127.0.0.1:8765**. Zaprete s `Ctrl+C`.

## Kaj že deluje

- Vnaprej izpolnjen, popravljiv profil vaše mlečne kmetije v Ivančni Gorici.
- Lokalna baza SQLite in pregled razpisov.
- Ročno preverjanje štirih virov: GOV.SI javne objave, GOV.SI SKP, občina, LAS STIK.
- Zajem potencialno relevantnih povezav, brez izmišljanja statusov ali rokov.
- Ročni vnos statusa, roka, opisa in pogojev z dokazilom.
- Preverjanje strukturiranih pogojev s profilom; samodejno skrivanje samo ob preverjenem obveznem in fiksno neizpolnjenem pogoju.
- Zgodovina preverjanj in zaznavanje sprememb besedila posamezne strani ob ponovnem prenosu.
- Neobvezna e-poštna obvestila ob novih najdenih povezavah.

## Dnevno preverjanje

Ročni ukaz za preverjanje:

```bash
python app.py scan
```

Na Linuxu lahko v `crontab -e` dodate (zamenjajte poti):

```cron
0 7 * * * cd /ABSOLUTNA/POT/KmetRazpisi && /ABSOLUTNA/POT/KmetRazpisi/.venv/bin/python app.py scan >> monitor.log 2>&1
```

Na Windows uporabite **Task Scheduler / Načrtovalnik opravil**, dnevno ob 7:00, program `.venv\Scripts\python.exe`, argumenta `app.py scan`, začetna mapa pot do projekta.

## E-poštna obvestila (neobvezno)

Pred zagonom nastavite okoljske spremenljivke: `SMTP_HOST`, `SMTP_PORT` (privzeto 587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `ALERT_TO`. Gesla nikoli ne zapisujte v kodo ali v javni repozitorij. Če niso nastavljene, obvestil ni. SMTP mora podpirati STARTTLS.

## Pomembne omejitve

1. **Zajem je osnovni.** Strani lahko spremenijo strukturo, vsebujejo paginacijo ali JavaScript; zajem lahko izpusti objave ali pobere nerelevantne povezave. Vsi najdeni zapisi so zato `nepreverjeno`.
2. **PDF-prilog aplikacija še ne bere samodejno** in ne izlušči pravnih pogojev z AI. Pogoje za zdaj dodate ročno in potrdite z uradnim virom. To je namerna varnostna omejitev prve različice.
3. Spremembe besedila se preverjajo šele, ko v podrobnostih znova kliknete »Preberi besedilo uradne strani«. Dnevni pregled zaznava predvsem nove povezave, ne vseh sprememb prilog.
4. Za javno objavo na internet **ni pripravljena**: nima prijave, HTTPS, zaščite pred CSRF in omejevanja zahtev. Strežnik je zato vezan izključno na `127.0.0.1`. Ne preusmerjajte vrat na internet.
5. Oznaka »pogoji izpolnjeni« velja samo za vnesene in preverjene pogoje, ne za celoten razpis. Za pravno upravičenost je vedno odločilna uradna dokumentacija.
6. Dnevno preverjanje in obvestila delujejo le, če jih zaženete ali nastavite v sistemskem razporejevalniku na prižganem računalniku.

## Varnostne kopije

Redno kopirajte `kmetrazpisi.sqlite3` (najbolje, ko aplikacija ne teče). Profil vsebuje podatke o kmetiji, zato mape ne delite javno.

## Nadgradnje

- Zajem paginacije, podstrani in PDF-prilog, preverjanje sprememb vseh prilog.
- AI izluščenje pogojev z natančnimi citati in obveznim ročnim pregledom.
- Presečni datumi, logika AND/OR, verzioniranje pravil in zgodovina profila po letih.
- Varna prijava, HTTPS in gostovanje, če želite dostop od drugod.
- Razlikovanje razpisov, letnih zbirnih vlog in drugih podpor.

## Nadgradnja analize dokumentacije

Analiza zdaj zahteva OpenAI in PyMuPDF (v `requirements.txt`); način s ključnimi
besedami se ne uporablja kot nadomestilo za analizo. Na Windows pred zagonom
nastavite ključ v okolju PowerShell (vrednost vnesite samo lokalno), spremenljivki
sta `OPENAI_API_KEY` in neobvezna `OPENAI_MODEL` (privzeto `gpt-4.1-mini`).
Ključa ne zapisujte v projekt. Po spremembi okolja znova zaženite strežnik.

PDF strani se shranijo skupaj s citatom in imenom dokumenta. Citati morajo biti
prisotni v viru; PDF citat mora pripadati eni določljivi strani. Preusmeritve se
preverijo pred prenosom. Napaka priloge prepreči zamenjavo prejšnje uspešne analize.
OCR se poskusi s Tesseract in jezikoma `slv+eng`; za skenirane dokumente namestite
Tesseract z obema jezikovnima paketoma. Manjkajoč OCR ima posebno diagnostiko.

Trenutne omejitve: največ 8 PDF-jev, 150 strani na PDF, 12 MB na dokument in
100.000 znakov na analizo. Ob preseganju se analiza ustavi, ne odreže dokumentacije.
Priloge prek vmesnih strani, DOCX in analiza velikih dokumentov po delih še niso
podprti. Tudi uspešna analiza ne zagotavlja, da je AI našel vse pravne pogoje.
Sestavljene in časovno odvisne zahteve sodijo v ročni pregled. Samodejno skrivanje
je začasno izključeno, ker stari model ne beleži vseh zahtevanih izjem in izključitev.
Ročno skrivanje ostaja na voljo. Časovna zgodovina profila, potrjevanje AI-pravil,
samodejno razvrščanje dejanskih razpisov, predpomnjenje AI in celovita avtomatizacija
so še naslednje faze, ne končane funkcije.

Inicializacija stare baze ne briše več zapisov iz drugih virov. Migracija doda le
ime dokumenta in številko strani. Pred nadgradnjo naredite varnostno kopijo baze.
Za razvoj in teste na kopiji lahko nastavite `KMETRAZPISI_DB` na drugo datoteko.

Testi (iz mape KmetRazpisi):

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
```

Na Linuxu uporabite `.venv/bin/python`. Testi uporabljajo umetne PDF-je in
simulirane odgovore OpenAI, brez ključa in omrežja. Preverjajo tudi migracije na
kopiji obstoječe baze. Izvedeni so bili na Linuxu s Python 3.12; izvajanje na
Windows in analiza resničnega razpisa z API ključem še nista preverjena.
