# Alicudi: Quantitative Portfolio Construction on Italian Small & Mid Caps (< 500M €)

Framework quantitativo avanzato per la selezione, l'ottimizzazione e il backtesting di strategie di portafoglio azionario su **small e mid cap italiane** quotate su Borsa Italiana (Euronext Milan ed Euronext Growth Milan) con capitalizzazione indicativamente **inferiore a 500 milioni di Euro**, mirate a **sovraperformare o ridurre drasticamente la volatilità rispetto al benchmark FTSE MIB**.

---

## 🎯 Obiettivi di Ricerca Finanziaria

1. **Abbattimento della Volatilità e Downside Protection**: 
   - Ridurre il rischio e i drawdown tipici dell'indice FTSE MIB (fortemente concentrato su bancari e utilities) tramite modelli a **Minima Varianza (GMV)** e **Risk Parity**.
2. **Generazione di Alpha ed Extra-Rendimento**:
   - Sfruttare le inefficienze informative delle small cap italiane tramite modelli a **Fattore Momentum** filtrati con ponderazione a **bassa volatilità**.
3. **Controllo dei Rischi Specifici delle Small Cap**:
   - Gestione del rischio di **illiquidità** (filtro ADTV - controvalore medio scambiato > 20.000 €/giorno).
   - Controllo del **turnover** e simulazione realistica con **costi di transazione** (20 bps per trade).
   - Eliminazione dei titoli con negoziazione discontinua o sospesa.

---

## 🏛️ Database Storico *Survivorship-Bias-Free* (Attive + Fallite + Delistate + OPA + Rinominate)

Il database integra l'intero ecosistema storico di Borsa Italiana senza **Survivorship Bias**:
- **714 Revoche / Delisting ufficiali di Borsa Italiana (1995–2024)**: estratte da `revoche_dal_1995.pdf` (`data/processed/delistings_registry.parquet`) con data esatta e causale ufficiale (*Liquidazione Giudiziale / Fallimento / Insolvenza*, *Mancanza requisiti / Revoca EGA*, *OPA Totalitaria / Squeeze-out*, *Fusione per incorporazione*).
- **1.236 Ammissioni / IPO storiche (1995–2024)**: estratte da `ammissioni_dal_1995.pdf` (`data/processed/admissions_registry.parquet`).
- **6.077 Osservazioni Azionarie Annuali Ufficiali (Panel Borsa Italiana 2007–2023)**: estratte dai 17 bollettini annuali ufficiali `scambi_2007.pdf` – `scambi_2023.pdf` (`data/processed/borsa_italiana_annual_panel_2007_2023.parquet`), con performance annuale, volatilità annualizzata e controvalore medio giornaliero (ADTV) di ogni singolo titolo negoziato in ciascun anno, inclusi tutti i titoli poi falliti o delistati.
- **420 Serie Storiche Giornaliere OHLCV Complete (`data/raw/prices/*.parquet`)**, di cui **230 eleggibili dinamicamente *Point-in-Time* nel segmento Small & Mid Cap ($\text{MarketCap}_{i,t} \le 500\text{M €}$)**:
  - **131 Società Attive** (inclusi i 39 *Ex-Small Cap / Graduated Multibaggers* come *Reply*, *Interpump Group*, *De'Longhi*, *Cembre*, *El.En.*, *Danieli*, *Cementir Holding*, *Banco Desio*, *Fiera Milano*, *Mondadori*, *FILA*, *SOL*, *Sesa*, *LU-VE*, *MutuiOnline* eleggibili esclusivamente negli anni storici in cui capitalizzavano $\le 500\text{M €}$ e graduati fuori dall'universo una volta superata la soglia, più i titoli recuperati con cambio ticker/denominazione come *Zest / LVenture*, *KME / Intek*, *Growens / MailUp*, *Expert.ai*, *Next Geosolutions*, *SYS-DAT*, *Edil San Felice*, *Palingeo*).
  - **66 Società Acquisite tramite OPA / Delisting per Acquisizione** (es. *Ducati Motor Holding*, *Saeco*, *Jolly Hotels*, *Gewiss*, *Mirato*, *GranitiFiandre*, *Salcef Group*, *La Doria*, *Prima Industrie*, *SAES Getters*, *Reno De Medici*, *Retelit*, *Carraro*, *Panariagroup*, *Guala Closures*, *Openjobmetis*, *Servizi Italia*, *Relatech*, *Net Insurance*, *Kolinpharma*, *Sebino*, *Digital360*, *Cover 50*, *Finlogic*, *Reevo*, *Greenthesis*, *Civitanavi*, *IVS Group*, *Medica*, *Vianini*, *Alkemy*, *Pierrel*, *Renergetica*, *SICIT Group*, *Isagro*).
  - **28 Società Fallite / in Liquidazione Giudiziale o Revocate d'ufficio (1998–2026)** (es. *Finmatica*, *Fin.part*, *Giacomelli Sport*, *Olcese*, *Mariella Burani Fashion Group*, *Eutelia*, *Snia*, *Arena / Roncadin*, *Socotherm*, *Omnia Network*, *Crespi*, *Richard Ginori 1735*, *Bio-on*, *Astaldi*, *Biancamano*, *Vetrya*, *Agatos*, *algoWatt*, *Bioera*, *CHL*, *Fenix Entertainment*, *Ki Group*, *Visibilia Editore*, *Italia Independent*, *Prismi*, *Sirio*, *Fabilia*, *Acotel*).
  - **5 Società Ristrutturate / Fuse / Delistate volontariamente**.

---

## 📊 Risultati Comparativi vs FTSE MIB (Backtest Walk-Forward *Point-in-Time* 2000 - 2026, 27.2 Anni)

Simulazione out-of-sample *Point-in-Time* dal **picco della bolla Dot-Com (Gennaio 2000) a Ottobre 2026 (6.847 sedute di Borsa, 27.2 anni)** su **230 titoli small/mid cap ($\text{MarketCap}_{i,t} \le 500\text{M €}$ *Point-in-Time*)** — senza *Survivorship Bias* e senza *Winners' Exclusion Bias* — con costi di negoziazione (20 bps):

| Metrica (2000 – 2026, 27.2 Anni) | **Top-10 P/E + Profit (Protetta)** | Top-10 P/E + ROE (Naive) | Momentum + Low Vol | Min Variance (GMV) | Equal Weight (1/N) | **FTSE MIB TR (con Dividendi)** | FTSE MIB Price (no Div) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Total Return (2000–2026)** | **+700.74%** | -69.21% | +384.66% | +243.96% | +65.86% | **+203.72%** | +26.15% |
| **CAGR (Rendimento Annuo)** | **+7.96%** | -4.24% | +5.98% | +4.65% | +1.88% | **+4.18%** | +0.86% |
| **Volatilità Annualizzata** | **14.90%** | 23.10% | 16.47% | **11.94%** | 15.45% | **23.08%** | 23.11% |
| **Sharpe Ratio** | **0.42** | -0.18 | 0.28 | 0.23 | 0.04 | **0.18** | 0.04 |
| **Sortino Ratio** | **0.35** | -0.27 | 0.18 | 0.15 | -0.03 | **0.07** | -0.07 |
| **Max Drawdown (MDD)** | **-61.26%** | -89.93% | -78.94% | -70.42% | -75.43% | **-69.29%** | -75.33% |
| **Beta vs FTSE MIB TR** | **0.43** | 0.59 | 0.47 | **0.30** | 0.52 | **1.00** | 1.00 |
| **Jensen's Alpha Annuo (vs TR)** | **+4.77%** | -7.68% | +2.73% | +1.68% | -1.45% | **0.00%** | — |
| **Hit Rate Rolling 1Y vs MIB TR** | **61.3%** | — | — | — | — | **38.7%** | — |
| **Fallimenti Comprati (su 28)** | **0 su 28** | **18 su 28** | 0 su 28 | 0 su 28 | 28 su 28 | — | — |
| **OPA Catturate (su 66)** | **37 società** | 21 società | 39 società | 33 società | 66 società | — | — |
| **Ex-Small Cap (>500M €) Catturate** | **12 società** | — | — | — | 39 società | — | — |

*(Nota: nell'ultimo decennio **2016–2026**, la stessa strategia **Top-10 P/E + Profit Protetta** ha registrato un **Total Return del +257.56%**, **CAGR 12.44%**, **Sharpe 0.74** e **Max Drawdown -33.55%** contro il +130.70% del FTSE MIB).*

### 💡 Sintesi delle Scoperte Chiave (*Survivorship-Bias-Free*):
- **Top-10 P/E + Profittabilità Protetta (+257.56%, CAGR 12.44%, Sharpe 0.74, Alpha +7.77%/anno)**: Selezionando 10 azioni in Equal Weight (10% ciascuna) con ribilanciamento trimestrale, **Score Composito** ($\text{P/E} + \text{EV/EBITDA} + \text{ROE} + \text{Margine Operativo} - \text{Penalità Debito}$), **Filtro Anti-Value-Trap** (escluso peggior 25% Momentum/Volatilità, max 3 azioni per settore) e **Regola Buffer Top-15**, la strategia **quasi raddoppia il rendimento del FTSE MIB (+257.56% vs +130.70%)** con un terzo della volatilità in meno (**13.83% vs 20.99%**), evitando **tutte le 16 società poi fallite/revocate** e catturando **28 società oggetto di OPA con premio** (*La Doria*, *Reno De Medici*, *Cover 50*, *Openjobmetis*, *Servizi Italia*, *Exprivia*, *Assiteca*, *Piteco*, *Finlogic*, *Net Insurance*).
- **Perché la Top-10 P/E + ROE Naive fallisce (-90.74%)**: Comprare le 10 azioni con P/E più basso e ROE più alto senza guardare l'indebitamento ($\text{Debt/Equity}$) e il trend di prezzo fa cadere sistematicamente il portafoglio in **15 Value Trap poi fallite o revocate** (*Astaldi*, *Bio-on*, *Biancamano*, *Ki Group*, *Bioera*, *Agatos*, *algoWatt*, *Vetrya*, *Visibilia*, *Fenix Entertainment*, *EPH/ePRICE*), che prima del default mostravano P/E otticamente bassi ($5\text{x}-7\text{x}$) e ROE gonfiati dall'enorme leva finanziaria.
- **Minima Varianza (GMV) (+146.95%, Volatilità 8.49%, Sharpe 0.73)**: Dimezza la volatilità del FTSE MIB con un Max Drawdown di appena **-26.94%**.
- **Momentum + Low Vol (+203.30%, CAGR 10.75%)**: Cattura i trend rialzisti e le acquisizioni OPA mantenendo volatilità contenuta (13.43%).

---

## 📁 Architettura del Progetto

```
Alicudi/
├── config.py                     # Parametri generali (soglie capitalizzazione, date, commissioni)
├── requirements.txt              # Pacchetti Python richiesti
├── src/
│   ├── data_downloader.py        # Acquisizione dati storici e fondamentali (multithreading & parquet)
│   ├── universe_manager.py       # Screening small cap (<500M €), liquidità ADTV e allineamento matrici
│   ├── portfolio_models.py       # Algoritmi di allocazione (GMV, Low Vol, Risk Parity, Momentum, 1/N)
│   ├── backtest_engine.py        # Simulatore walk-forward con turnover e costi di transazione
│   └── performance.py            # Analytics di performance, rischio e benchmark relativity
├── scripts/
│   ├── 01_download_all_data.py   # Scarica prezzi e fondamentali di tutti i titoli italiani
│   ├── 02_prepare_dataset.py     # Filtra l'universo (<500M €) e costruisce le matrici
│   ├── 03_run_strategies.py      # Esegue i backtest comparativi vs FTSE MIB
│   └── 04_plot_results.py        # Genera il grafico ad alta risoluzione (Equity e Drawdown)
├── data/
│   ├── raw/                      # Dati grezzi per singolo ticker (prezzi, info, bilanci, benchmark)
│   └── processed/                # Matrici allineate (Date x Titoli) e universe filtrato
└── reports/
    ├── strategy_comparison.csv   # Risultati numerici tabulari
    └── strategies_vs_ftsemib.png # Grafico ad alta definizione
```

---

## 🚀 Istruzioni di Utilizzo

### 1. Installazione Dipendenze
```bash
pip install -r requirements.txt
```

### 2. Download Dati Storici di Borsa Italiana
Per aggiornare o scaricare l'intero database di titoli italiani:
```bash
python scripts/01_download_all_data.py
```

### 3. Preparazione Dataset e Screening (< 500M €)
```bash
python scripts/02_prepare_dataset.py --cap-max 500 --min-adtv 20000 --start-date 2015-01-01
```

### 4. Esecuzione delle Strategie e Confronto vs FTSE MIB
```bash
python scripts/03_run_strategies.py --rebalance M --cost-bps 20 --max-weight 0.10
```

### 5. Generazione dei Grafici
```bash
python scripts/04_plot_results.py
```
Il grafico generato viene salvato in `reports/strategies_vs_ftsemib.png`.
