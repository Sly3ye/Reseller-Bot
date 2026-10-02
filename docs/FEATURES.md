# Feature principali (raccolta & operatività)

> Il layer di Business Intelligence (Deal Score, valutazione, varianti,
> time-to-sale, pipeline) ha un documento dedicato: [DATA-INTELLIGENCE.md](DATA-INTELLIGENCE.md).

### 1. Cecchino Live (Sniper)
Interroga `hades` **ordinando per data** (gli ultimi pubblicati), scarica le
immagini solo per i nuovi e fa l'upsert su `live_opportunities_*`, paginando
all'indietro solo fino al giro precedente (nessun annuncio perso tra un giro e
l'altro). **Tech ogni 15'** con UNA ricerca ampia "iphone" e assegnazione di
ogni annuncio al target del suo modello; **auto ogni 30'** con una ricerca per
target. Dettagli: [ARCHITETTURA.md](ARCHITETTURA.md#copertura-del-tech-ricerca-ampia--inventario).

### 1b. Inventario tech notturno
Giro completo dello stock iPhone attivo per fasce di prezzo (~540 richieste):
prezzi aggiornati per tutti gli annunci e rilevamento dei venduti (verifica
pagina per pagina solo dei candidati). Il primo recupero si lancia a mano con
`scripts/deep_sweep.py`.

### 2. Motore Notturno (Market Intelligence)
Job giornaliero (03:00) che ricalcola la media di mercato per target con la
**regola IQR (1.5× interquartile range)** per scartare i prezzi anomali prima
della media (`filter_price_outliers` in `tasks.py`).

### 3. NLP Parser (regex, zero dipendenze) — auto **e** tech
`nlp_parser.py` estrae dal titolo+descrizione ciò che l'API non dà pulito:
- **Auto**: km/anno di fallback; allestimenti normalizzati per sinonimi (M-Sport…);
  difetti (frizione, grandine, incidentata, fuso…); urgenza (trasferimento, svendo…).
- **Tech/iPhone**: memoria (64→1TB), salute batteria, corredo (scatola, fattura,
  AppleCare, pari-al-nuovo), difetti (schermo/vetro rotto, iCloud bloccato, per ricambi).
- **Esclusione IQR**: gli annunci non-sani non inquinano la media (auto
  incidentata/fusa; iPhone rotti/bloccati/per-ricambi).

### 4. Anti-Akamai via curl_cffi + rotazione impronte
`hades` è dietro Akamai Bot Manager (httpx → 403). Le ricerche usano **curl_cffi**
con impersonazione TLS di un browser reale; il **pool di profili** (safari,firefox)
è ruotato a caso per target → un profilo flaggato non blocca tutto.

### 5. Anti-ripubblicazione via Perceptual Hash (pHash)
Si calcola il **pHash 64-bit** della prima foto; se ricompare sotto un nuovo
`listing_url`, il sistema riconosce la ripubblicazione e **aggiorna il record
esistente** invece di duplicarlo, preservando lo storico prezzi.

### 6. Shadow Dealer detection
Un "privato" con più di 3 annunci attivi contemporanei viene riclassificato
`finto_privato` (`apply_shadow_dealer`) — leva di trattativa diversa.

### 7. Price Drop Alert
Sul calo di prezzo di un annuncio tracciato: vecchio prezzo in `original_price`,
evento in `price_history`, evidenziato nel frontend e notificato su Telegram.

### 8. Garbage Collector (schedulato)
Ogni notte (04:30) verifica se gli annunci attivi sono ancora raggiungibili
(404/410 o redirect fuori) e li marca `venduto_rimosso`. La differenza
`found_at → rimozione` è il **sensore del time-to-sale**.

### 9. Notifiche Telegram
Fine giro Sniper → opportunità nuove sopra soglia + cali di prezzo, con foto,
margine, difetti/urgenza e link. Un bot, chat separate per verticale.
Dedup persistente su `sent_alerts`. Config assente → no-op.

### 10. Monitoraggio salute scraper (Fase 3)
Ogni giro registra esito in `scrape_runs` (ok/degraded/down). Alert Telegram di
**sistema** su transizione down/ripristino (blocco Akamai/Subito) → non si
blocca mai in silenzio. Ogni giro registra anche le chiamate fatte
(`requests`) e i target con annunci persi (`gaps`). Stato leggibile da
`GET /health/scraper`, ritmo corrente incluso (`pacing`).

### 11. Deep Backfill
`scripts/run_backfill.py` ("aspirapolvere"): pagina in profondità l'intero
risultato di ricerca per popolare lo storico di un target, senza scaricare
immagini (le riempirà lo Sniper).

### 12. Resilienza anti-ban (senza proxy)
Un solo IP, quindi niente raffiche: pausa minima globale tra le chiamate a
`hades`, retry con backoff (`tenacity`) solo su errori di rete e 5xx. Su
403/429 lo scraper si ferma per un cooldown crescente e rallenta, invece di
insistere (vedi [ARCHITETTURA.md](ARCHITETTURA.md#ritmo-da-un-solo-ip-niente-proxy)).
Anche il Garbage Collector va a basso parallelismo e si ferma se bloccato.
