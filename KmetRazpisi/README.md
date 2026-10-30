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
