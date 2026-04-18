# Wind Alert

Notifiche Telegram automatiche quando il vento a San Francesco supera le soglie o quando sta per arrivare un temporale. Gira su **GitHub Actions** (gratis), controlla il meteo ogni 15 minuti, manda solo alert utili (niente spam) e ti fa anche un preavviso di 1-3 ore per avere tempo di ammainare le tende.

**Costo: 0€.** Nessuna carta di credito richiesta.

---

## Cosa ti avvisa

| Evento | Quando |
|---|---|
| WARNING | Raffica ≥ 30 km/h (superamento soglia) |
| CRITICO | Raffica ≥ 50 km/h |
| Cambio repentino | +15 km/h in ~30 min |
| Preavviso | Previste raffiche oltre soglia nelle prossime 1-3 ore |
| Temporale in corso | Codici 95/96/99 (temporale, grandine) |
| Temporale previsto | Temporale in arrivo entro 3 ore |
| Rientro | Vento tornato nella norma dopo un warning |

La deduplica evita che ti arrivino messaggi ogni 15 min: ricevi una notifica quando *cambia qualcosa*, non finché la condizione persiste.

---

## Setup (circa 10 minuti)

### 1. Crea il bot Telegram (2 min)

1. Apri Telegram, cerca `@BotFather`
2. Scrivi `/newbot` e segui le istruzioni (nome e username)
3. Copia il **token** che ti dà (es. `123456:ABC-DEF...`) — lo userai dopo

### 2. Prendi il tuo chat_id (1 min)

1. Cerca `@userinfobot` su Telegram e scrivigli `/start`
2. Ti risponde con il tuo `Id`: è un numero (es. `987654321`). Copialo.
3. **Importante**: manda un qualunque messaggio (anche solo "ciao") al bot che hai creato al punto 1, altrimenti non potrà scriverti.

### 3. Crea il repo GitHub (3 min)

1. Vai su <https://github.com/new>
2. Nome repo: `wind-alert` (o come preferisci)
3. Visibilità: **Public** = minuti Actions illimitati, oppure Private (fino a 2000 min/mese gratis — noi usiamo ~1400, ci sta)
4. Spunta "Add a README file" → clicca **Create repository**

### 4. Carica i file in questa cartella

Nel repo GitHub appena creato, clicca **Add file → Upload files** e carica tutti i file di questa cartella (`wind-alert/`) *mantenendo la struttura*:

```
wind_alert.py
config.json
state.json
.gitignore
.github/workflows/wind-check.yml
README.md
```

**Attenzione alla cartella `.github/workflows/`**: GitHub la considera nascosta nel browser del SO. Il modo più semplice è:
- Clicca **Add file → Create new file**
- Nel nome digita `.github/workflows/wind-check.yml` (le `/` creano le cartelle)
- Incolla il contenuto di `wind-check.yml` di questa cartella
- Commit

Oppure da terminale (se usi git localmente):
```bash
git clone https://github.com/TUO_USER/wind-alert.git
cd wind-alert
# copia qui tutto il contenuto della cartella wind-alert di Claude
git add .
git commit -m "setup wind alert"
git push
```

### 5. Aggiungi i 2 secret (2 min)

Nel repo GitHub: **Settings → Secrets and variables → Actions → New repository secret**

Aggiungi due secret:

| Nome | Valore |
|---|---|
| `TELEGRAM_BOT_TOKEN` | il token del bot dal punto 1 |
| `TELEGRAM_CHAT_ID` | il tuo chat id dal punto 2 |

### 6. Dai il permesso di scrittura a GitHub Actions (30 sec)

Serve perché lo script aggiorna `state.json` tra un run e l'altro:

**Settings → Actions → General → Workflow permissions**
→ seleziona **"Read and write permissions"** → **Save**

### 7. Test manuale (1 min)

Vai sul tab **Actions** del repo → clicca su "Wind Alert Check" → bottone **Run workflow** → **Run workflow**.

Se tutto è OK vedrai il job verde in 20-30 secondi. Se le condizioni correnti superano una soglia, riceverai un Telegram. Altrimenti vedrai nel log `OK - gust=X level=ok`.

Per forzare un messaggio di test: nel file `config.json` abbassa temporaneamente `warning_gust_kmh` a 1, fai commit, lancia il workflow manualmente → ricevi notifica → riporta la soglia a 30.

---

## Come modificare le soglie

Apri `config.json` e cambia i valori. Il formato è:

```json
{
  "thresholds": {
    "warning_gust_kmh": 30,      // soglia gialla
    "critical_gust_kmh": 50,     // soglia rossa
    "sudden_delta_kmh": 15,      // aumento improvviso da segnalare
    "forecast_hours": 3          // orizzonte di preavviso
  },
  "quiet_hours": {
    "enabled": false,            // metti true per silenziare di notte
    "start_hour": 23,            // gli alert CRITICI passano comunque
    "end_hour": 7
  }
}
```

Dopo il commit, il workflow rilegge la config al run successivo.

---

## Note e limiti

**Ritardi GitHub Actions.** I cron schedulati su GitHub possono essere ritardati di qualche minuto durante i picchi di carico. Nella pratica è quasi sempre puntuale, ma se ti aspetti ogni 15 min esatti potresti vedere anche 18-20 min occasionalmente. Per eventi estremi di norma non è critico (le soglie sono già prudenti e c'è il preavviso).

**Disattivazione dopo 60 giorni di inattività.** I workflow schedulati si disattivano se il repo non riceve commit per 60 giorni. Il nostro commit `state.json` ogni 15 min tiene il repo attivo, quindi non è un problema.

**Dati meteo.** Fonte: [Open-Meteo](https://open-meteo.com), modello ICON-D2 + IFS, aggiornamento orario. Posizione: 45.2167° N, 7.65° E.

**Logica anti-spam.** Il bot invia un alert quando lo stato *cambia* (es. da `ok` a `warning`), non ad ogni controllo. I preavvisi hanno un cooldown di 2 ore.

---

## Come cambiare frequenza

Nel file `.github/workflows/wind-check.yml` cambia la riga `cron`:
- `*/15 * * * *` → ogni 15 min
- `*/10 * * * *` → ogni 10 min (usa più minuti del free tier private; su public = gratis illimitato)
- `*/30 * * * *` → ogni 30 min

---

## Debug

**I log dei run** sono nel tab **Actions** del repo GitHub.

**Lo stato interno** (ultimo livello, storico delle letture) è in `state.json`, che viene committato dal bot dopo ogni run.

**Log testuale**: `wind_alert.log` nel repo, si aggiorna a ogni run.

Se qualcosa non va:
1. Tab Actions → apri l'ultimo run → espandi "Run wind check" per vedere l'output
2. Verifica che i secret siano presenti (Settings → Secrets and variables → Actions)
3. Manda manualmente `/start` al tuo bot Telegram (se non l'hai mai fatto, il bot non può scriverti)

---

## Alternativa: eseguire localmente sul Mac

Se un giorno preferisci farlo girare solo sul Mac (sta sempre acceso?), puoi usare `launchd`:

```bash
# plist in ~/Library/LaunchAgents/com.tessuti.windalert.plist
# StartInterval 900 (15 min), ProgramArguments: python3 + path a wind_alert.py
# Esporta TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID come EnvironmentVariables nel plist
launchctl load ~/Library/LaunchAgents/com.tessuti.windalert.plist
```

Ma per quello che descrivi (vuoi l'avviso anche quando sei fuori e il Mac è spento) GitHub Actions è la scelta giusta.
