## Novost 1.6.0 – imenik izvozov predpisov in lokalna ponovna uporaba

Zavihek Predpisi prikazuje shranjene ID-je, imena, različice, datume začetka uporabe
in URL-je uradnih izvozov. URL se zabeleži samodejno ob uspešnem pridobivanju vira
med analizo. Rezervno lahko uporabnik vnese uradni neposredni HTML-URL; ID-ja datoteke
se ne ugiba. Uvoz prenese, razčleni in shrani dejanski predpis, ne le povezave.
GET /api/laws vrne imenik, POST /api/laws/import sprejme url in neobvezni refresh.

Natančno določen shranjeni URL z eno prepoznano različico se lahko uporabi lokalno
brez ponovnega prenosa. Uspešno razrešen pravni sklic se poveže s konkretnim SHA
izvoza in zgoščeno vsebino celotne razpisne dokumentacije. Pri nespremenjeni
ponovitvi se preskoči spletno iskanje in uporabi isti lokalni predpis; razlaga
izbranega člena še vedno uporablja API. Sprememba razpisnih dokumentov prekine
ujemanje povezave; ni samodejnega izbora najnovejše ali časovno veljavne različice.
Več različnih vsebin za isti URL zahteva pregled in ne sproži tihega izbora.
Stari izvozi se ohranijo. Knjižnica je v kmetrazpisi-laws.sqlite3, ohranite jo
poleg glavne baze. To je arhiv posnetkov, ne jamstvo najnovejšega besedila.

Samodejna povezava ID predpisa → HTML-izvoz z vmesniki PISRS še ni potrjena;
prvo odkritje URL-ja uporablja obstoječe iskanje ali podani uradni URL. Neposredni
URL, ki ga je uporabnik posredoval, je v tem okolju še vedno blokiran s HTTP 403.
Preverjeno z dejanskim priloženim HTML-izvozom in simuliranim prenosom, ne z živim
PISRS in OpenAI računom.

## Novost 1.5.1 – preverjeno na dejanskem izvozu PISRS URED8874 NPB5

Dejanski HTML-izvoz razdeli na 36 členov (1–35 in 20.a) ter pravilno izbere
odstavke in točke 9. in 12. člena. PISRS-oznake p.clen ohranijo večvrstične
naslove členov kot celoto. Oznake poglavij in povezave p.priloga se ne pripenjajo
besedilu predhodnega oziroma zadnjega člena. Priloge se ohranijo v metapodatkih.
Izvoz hrani ID URED8874, oznako neuradnega prečiščenega besedila NPB5 in datum
začetka uporabe 20. 3. 2026. To ni samodejna potrditev pravilne časovne različice
za razpis. Preverjeno lokalno na priloženem izvozu brez OpenAI klicev; samodejni
prenos s PISRS še ni potrjen. Migracija lokalne knjižnice doda samo metadata.

## Novost 1.5.0 – razdelitev predpisov brez AI

Modul law_documents.py prebere uradni HTML, DOCX ali besedilni PDF in programsko
razdeli vsebino po členih (tudi 12.a), odstavkih in enostavnih oštevilčenih ali
črkovnih točkah. Omembe členov v stavkih niso obravnavane kot naslovi. Dvoumne
podvojene oznake se zavrnejo, vrzeli v zaporedju opozorijo na potreben pregled.
Skeni, spletni ovoji brez besedila in stari binarni DOC zahtevajo drug uradni izvoz.

Pri razlagi pravnega sklica spletno iskanje najprej poišče URL predpisa. Program
nato prenese predpis in izbere navedene člene; šele izbrano besedilo pošlje modelu
za razlago. Pri navedbi odstavka/točke trenutno vključi celoten zahtevani člen,
da ohrani kontekst in izjeme. Nadaljnji sklici na druge določbe niso samodejno
rekurzivno razrešeni; nejasni pogoji še zahtevajo pregled. Časovna veljavnost ni
samodejno potrjena. Podpora živim PISRS-izvozom še ni preverjena zaradi blokade
HTTP 403 v okolju. Ni potrjenega javnega API-ja PISRS.

Pridobljena besedila in njihove razdelitve se shranjujejo v ločeno lokalno bazo
kmetrazpisi-laws.sqlite3 (pot nastavljiva s KMETRAZPISI_LAW_DB). Različne zgoščene
vsebine se ohranijo ločeno; stare različice se ne prepišejo. Vsak vir se pred
uporabo znova pridobi, zato predpomnilnik še ne odpravlja prenosa. Tudi ta baza
je lokalni podatek, ki ga pri posodobitvah ohranite. Vrednost version_label iz
samodejnega prenosa je nepreverjena, ne pravna potrditev veljavnosti.

Preizkus brez OpenAI in brez interneta:

```powershell
.venv\Scripts\python law_documents.py predpis.html --source-url "https://pisrs.si/URADNI-VIR" --version "preverjena oznaka izvoza" --article 12 --paragraph 2
```

`--point a` izbere točko, `--database druga-pot.sqlite3` drugo lokalno knjižnico.
Naslov v primeru je označba za dejanski uradni URL, ne delujoča povezava do predpisa.

## Novost 1.4.3 – vir pogoja se določi po preverjenem citatu

Če AI navede napačen URL, se citat preveri v dejansko prenesenih dokumentih
trenutnega sklopa. Če se ujema samo z enim dokumentom, se uporabi njegov pravi
URL in ime; pri PDF-ju se še vedno zahteva določljiva stran. Nobena AI-povezava
se zaradi tega ne odpira. Neobstoječi, prazni ali dvoumni citati gredo v en
ponovni poskus in nato med opozorila nepopolne analize; ne ustavijo drugih
sklopov. Če ni nobenega potrjenega pogoja, se analiza še vedno konča z napako.

## Novost 1.4.2 – združljivost spletnega iskanja in vse priloge

Pri HTTP 400, povezanem s tools/web_search, pravno iskanje najprej poskusi orodje
web_search brez strežniškega filtra in nato web_search_preview. Model se ne
zamenja samodejno. Za preview se URL-ji preverijo iz citiranih povezav odgovora;
pravilo uradne domene in neposrednega preverjanja citata ostane obvezno.
Napake avtentikacije in omejitve porabe se ne ponavljajo s tem mehanizmom.
Če model ne podpira nobene različice, je sklic še vedno označen kot nerazrešen;
OPENAI_LEGAL_MODEL omogoča izbiro modela z ustrezno podporo.

Odstranjena je omejitev osmih prilog: obdelajo se vse najdene dovoljene PDF- in
DOCX-priloge razpisa, razen skupnih meril. Ostanejo omejitve velikosti posamezne
priloge in strani. Več prilog pomeni daljšo analizo in višjo API-porabo.
Preverjeno s simuliranimi API-odgovori in regresijskimi testi, ne z živim API-ključem.

## Novost 1.4.1 – samo dejanske zahteve in neposredni naslovi

AI razvršča pogoje upravičenosti, obveznosti, pragove, postopkovna navodila in
informacije. Dovoljenja, kot je »lahko vloži več vlog«, se izločijo. Tehnična
navodila za vnos vlog se ne obravnavajo kot vir pogojev upravičenosti.
Razlage potrjenih določb in pridobljenih prilog se vključijo v naslov pogoja;
ločenega okvirja »Kaj pogoj pomeni v praksi« ni več. Viri, citati in opozorila
ostanejo pod naslovom. Priloge v DOCX se lahko preberejo poleg PDF-jev. Če
priloga manjka ali citat ni potrjen, naslov to jasno pove in vsebina se ne ugiba.
HTTP-napaka pravnega iskanja izpiše tudi kodo/parameter napake, brez ključa.

Priloženi razpis IRP15.2 ima štiri strani in ne navaja minimalnega praga točk.
Ne sme podedovati praga 45 točk iz drugega razpisa. Morebitna dodatna zahteva v
sklicevani uredbi ostaja nepreverjena, dokler predpis ni uspešno pridobljen.
Spremembe so preverjene z dejanskim PDF-jem ter simuliranimi AI-odgovori;
produkcijski pravni web_search še ni potrjen.

## Novost 1.4.0 – razlage pravnih sklicev; brez skupnih meril

Skupne datoteke »Merila« so izločene že pred prenosom PDF-ja in pred analizo.
Minimalni prag se še išče v samem razpisu. Pri pogojih s sklicem na člen aplikacija
uporabi OpenAI Responses web_search, omejen na PISRS, Uradni list in EUR-Lex.
Nato uradni vir neposredno prenese ter preveri citat. Le preverjene citate opremi
z razumljivo razlago v razdelku »Kaj pogoj pomeni v praksi«. Izvirni citat razpisa
ostane viden. Nedosegljiv vir, nepodprt model ali nepotrjen citat pomenijo jasno
nerazrešen sklic, ne ugibanja. Pravni pogoji vedno ostanejo za ročni pregled.
To ni potrditev, da so razrešeni vsi nadaljnji sklici ali prava časovna različica.

Potreben je model z Responses web_search (nastavljiv z OPENAI_LEGAL_MODEL), API
ključ in omrežni dostop do api.openai.com ter uradnih pravnih domen. Iskanje ima
ločeno API-porabo; za vsak različen citat pogoja se lahko opravi dodaten klic.
Vrednosti profila kmetije se pri tem ne pošiljajo, pošlje se citat in kontekst
razpisne dokumentacije. SPA ali zaščiteni viri brez dostopnega besedila lahko
preprečijo preverjanje citata. Pridobivanje pravnih virov in njihova razlaga sta
preverjena s simuliranimi odgovori, ne s produkcijskim ključem. Migracija baze
samo doda stolpec legal_resolution in ne briše podatkov. Stare analize ponovite.

## Novost 1.3.9 – preverjeno na priloženih dejanskih PDF-jih

Razčlenjevalnik prepozna ločeni vrstici številke razdelka in naslova IRP v merilih
brez zaznamkov. Sklic lahko temelji tudi na polnem imenu intervencije v naslovu
razpisa, ne le na kodi IRP. Pred uporabo meril se primerja navedena različica v
povezavi razpisa z različico naslovnice oziroma imena datoteke; neujemanje prepreči
uporabo točkovnika z jasnim opozorilom. Kasnejše spremembe razpisa zahtevajo pregled.
Izrecna oblika »vstopni prag ... %, ki znaša X točk« se prebere neposredno s citatom
in stranjo, brez izračuna iz odstotka. Druge oblike še obravnava AI. Različnih pragov
se ne združuje; spremembe lahko spremenijo veljavni prag.
Priloženi razpis na strani 4 navaja 45 točk ter povezavo na EKSRP_8_P-v2, priložena
merila pa imajo naslovnico 11. spremembe. Aplikacija teh različic ne sme enačiti.

## Novost 1.3.8 – izvor pogojev in izbora meril

Vsak samodejno izluščeni pogoj prikazuje ime izvornega dokumenta kot povezavo,
številko strani, citat in ime PDF-datoteke. Imena prilog se pri novem zajemu ne
krajšajo več. Pod analizo je prikaz »Zakaj so izbrane te tabele oziroma razdelki
meril?«: sklic, izvorni dokument navodila, strani in dobesedni citat, nato izbrane
strani ciljnega dokumenta meril. Stare analize brez teh metapodatkov zahtevajo
ponovno analizo; manjkajoči podatki se ne izmišljajo. Nova migracija baze ni potrebna.

## Novost 1.3.7 – dvostopenjsko iskanje meril

Pred analizo točkovnikov AI iz ostalih dokumentov izlušči izrecne sklice na
intervencijo, razdelek ali tabelo. Sklic mora imeti citat iz teh dokumentov.
Program nato lokalno išče ustrezne naslove v PDF-zaznamkih oziroma oštevilčenih
naslovih in AI-ju pošlje le izbrane strani, skupna pravila ter razrešene številčne
sklice. Zaznamki ali naslovi brez jasnih meja pomenijo neznan izbor.
Celoten dokument meril se zaradi neuspelega izbora NE pošlje AI-ju: preskoči se z
opozorilom NEPOPOLNA ANALIZA in zahtevo za ročni pregled. PDF se še vedno prenese
in lokalno prebere za iskanje; to ni OpenAI poraba. Prva stopnja zahteva dodatne
API-klice na ostale dokumente. Veljavno različico in uporabo sklopa še preverite.
Minimalni prag se samo izlušči, če je izrecno naveden; ne izračunava se iz tabel.

## Novost 1.3.6 – minimalni prag točk

Analiza posebej išče izrecno navedene minimalne skupne pragove za izbor vloge.
V podrobnostih razpisa so prikazani ločeno s citatom, stranjo, opisom sklopa in
opozorilom za človeško potrditev. Najmanj X in več kot X sta različni zahtevi.
Različni pragovi se ne seštevajo in ne združujejo samodejno; manjkajoč prag je
neznan, ne nič točk. AI ne sme sklepati iz točkovnih tabel ali OMD točk.
Kontekst spletne objave pomaga omejiti razlago na konkretni razpis, vendar
veljavnost razdelka skupnih meril še zahteva ročni pregled. Izbor strani skupnih meril je previden: ob eni jasni oznaki IRP v osnovni
dokumentaciji in ustreznih PDF-zaznamkih se ohranijo ustrezni razdelek, mejne in
skupne strani. Pri več oznakah, manjkajočih zaznamkih ali dodatnih sklicih se
prebere celoten dokument z opozorilom. Različico in sklop je treba potrditi ročno. Možne točke kmetije niso izračunane;
minimalni prag ni uporabljen za samodejno skrivanje. Stare analize ponovite.

## Novost 1.3.5 – napredek analize

Analiza iz vmesnika teče v ozadju. Vrstica napredka prikazuje fazo prenosa PDF-jev,
trenutni AI-sklop, dokument in strani, ponovni poskus citatov ter zaključek.
Odstotek temelji na fazah in številu sklopov; ni ocena preostalega časa.
Med posameznim prenosom, branjem PDF-ja in API klicem lahko ostane nespremenjen.
Po ponovnem odprtju razpisa se prikaz poveže z analizo, ki še teče.
Dvojni klik ne zažene dodatne vzporedne analize istega razpisa; hkrati tečeta največ
dve analizi. Strežnik mora ostati zagnan. Ponovni zagon prekine tekoča opravila;
že shranjeni podatki ostanejo. API: POST `/api/tender/<id>/analyze-start` in
GET `/api/tender/<id>/analysis-progress`. Stari sinhroni endpoint je ohranjen.

## Novost 1.3.4 – nepopolni rezultati z diagnostiko

Nepotrjen citat po enem ponovnem poskusu ne ustavi več drugih sklopov. Shranijo se
samo pogoji, katerih citati so potrjeni, ob njih pa trajna oznaka NEPOPOLNA ANALIZA
z dokumentom, sklopom in razlogom izločitve. Nepotrjeni pogoji niso uporabljeni
pri presoji. Če ni nobenega potrjenega pogoja, se analiza konča z napako.
Omrežne napake, neveljavni podatki in neprebrane priloge še vedno ustavijo analizo.
Delni rezultat ni dokaz, da kmetija izpolnjuje vse pogoje. Prejšnje opozorilo o
ustavitvi pri vsaki napaki citata je za to različico nadomeščeno s tem vedenjem.

## Novost 1.3.3 – preverjanje citatov

Primerjava citatov upošteva Unicode ligature, mehke vezaje, presledke in besede,
prelomljene z vezajem med vrsticami v PDF-ju. Ne uporablja približnega ujemanja.
Če AI vrne nepotrjen ali dvoumen citat, aplikacija isti sklop poskusi analizirati
še enkrat z navodilom za dobesedne citate. To pomeni največ en dodaten plačljiv
klic na tak sklop. Ob ponovni napaki se analiza ustavi in ohrani prejšnji rezultat.
S tem ni zagotovljeno, da bo vsak dokument uspešno analiziran.

## Novost 1.3.2 – daljši PDF-ji

Odpravljena je omejitev 150 strani. PDF do 1.000 strani se v celoti prebere in
analizira v sklopih do 10 strani oziroma 24.000 znakov. Sosednji sklopi se po
možnosti prekrivajo za eno stran. Predolge strani in spletno besedilo se razdelijo
v prekrivajoča besedilna okna. Citati ohranijo izvirno številko strani, enaki pogoji
iz prekrivajočih sklopov se združijo. Napaka katerega koli sklopa ustavi shranjevanje
celotne nove analize; prejšnji rezultat ostane. Že opravljeni API klici so kljub
poznejši napaki plačljivi. Dolgi dokumenti zato potrebujejo več časa in več API
klicev. Pogoji ostajajo nepotrjeni, ker se izjeme lahko nahajajo v drugih sklopih.

# Trenutna različica: 1.6.0

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

Trenutne omejitve: 1.000 strani na PDF, 12 MB na dokument. Ob preseganju se analiza ustavi, ne odreže dokumentacije.
Priloge prek vmesnih strani in DOCX še niso
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
