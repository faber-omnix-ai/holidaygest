-- Schema v1. Date: 'AAAA-MM-GG'; istanti: ISO 8601 con offset Europe/Rome.
-- Denaro: centesimi interi. Intervalli di pernottamento: arrivo incluso, partenza esclusa.
-- Ogni entità ha un identificativo interno stabile (id) mai riutilizzato.

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL                -- JSON
);

CREATE TABLE IF NOT EXISTS users (
  id         INTEGER PRIMARY KEY,
  username   TEXT NOT NULL UNIQUE,
  pw_hash    TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- Chiave dati (DEK) cifrata con la password e con il codice di recupero.
CREATE TABLE IF NOT EXISTS keyring (
  id               INTEGER PRIMARY KEY CHECK (id = 1),
  wrapped_pw       TEXT NOT NULL,
  wrapped_recovery TEXT NOT NULL,
  created_at       TEXT NOT NULL
);

-- ===== Prenotazioni e calendario =====
CREATE TABLE IF NOT EXISTS bookings (
  id                  INTEGER PRIMARY KEY,
  ref                 TEXT NOT NULL UNIQUE,
  status              TEXT NOT NULL CHECK (status IN
                       ('bozza','opzione','opzione_scaduta','confermata','in_corso','conclusa','annullata','no_show')),
  booker_name         TEXT NOT NULL,
  booker_phone        TEXT,
  booker_email        TEXT,
  source_text         TEXT,             -- provenienza: solo testo libero
  arrival             TEXT NOT NULL,    -- occupazione pianificata
  departure           TEXT NOT NULL,    -- (esclusa)
  checkin_time        TEXT,
  checkout_time       TEXT,
  guests_expected     INTEGER NOT NULL DEFAULT 1,
  pricing_mode        TEXT NOT NULL DEFAULT 'totale' CHECK (pricing_mode IN ('totale','per_notte')),
  nightly_cents       INTEGER NOT NULL DEFAULT 0,
  base_cents          INTEGER NOT NULL DEFAULT 0,   -- totale concordato (modalità 'totale')
  deposit_cents       INTEGER NOT NULL DEFAULT 0,   -- cauzione richiesta
  option_expires_at   TEXT,
  linked_booking_id   INTEGER REFERENCES bookings(id),
  tourism_type        TEXT,
  transport           TEXT,
  booking_channel     TEXT,
  prep_status         TEXT NOT NULL DEFAULT 'da_preparare'
                       CHECK (prep_status IN ('da_preparare','in_preparazione','pronto')),
  turnover_ack        INTEGER NOT NULL DEFAULT 0,   -- cambio stesso giorno accettato esplicitamente
  tax_refusal_note    TEXT,
  notes               TEXT,
  cancelled_at        TEXT,
  cancel_reason       TEXT,
  no_show_at          TEXT,
  checked_out_at      TEXT,
  version             INTEGER NOT NULL DEFAULT 1,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  CHECK (departure > arrival)
);
CREATE INDEX IF NOT EXISTS ix_bookings_dates ON bookings(arrival, departure);

-- Extra e sconti espliciti sul corrispettivo (mai l'imposta).
CREATE TABLE IF NOT EXISTS price_items (
  id           INTEGER PRIMARY KEY,
  booking_id   INTEGER NOT NULL REFERENCES bookings(id),
  kind         TEXT NOT NULL CHECK (kind IN ('extra','sconto')),
  description  TEXT NOT NULL,
  amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0)
);

CREATE TABLE IF NOT EXISTS blocks (
  id         INTEGER PRIMARY KEY,
  start      TEXT NOT NULL,
  end_excl   TEXT NOT NULL,
  kind       TEXT NOT NULL CHECK (kind IN ('manutenzione','uso_personale','altro')),
  reason     TEXT NOT NULL,
  version    INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  CHECK (end_excl > start)
);

-- Chiusure amministrative/statistiche ROSS: distinte dai blocchi di calendario.
CREATE TABLE IF NOT EXISTS closures (
  id         INTEGER PRIMARY KEY,
  start      TEXT NOT NULL,
  end_excl   TEXT NOT NULL,
  note       TEXT,
  created_at TEXT NOT NULL,
  CHECK (end_excl > start)
);

-- ===== Ospiti e permanenze =====
CREATE TABLE IF NOT EXISTS guests (
  id                  INTEGER PRIMARY KEY,
  booking_id          INTEGER NOT NULL REFERENCES bookings(id),
  position            INTEGER NOT NULL DEFAULT 0,
  guest_type          TEXT NOT NULL CHECK (guest_type IN ('16','17','18','19','20')),
  leader_guest_id     INTEGER REFERENCES guests(id),
  surname             TEXT NOT NULL,
  name                TEXT NOT NULL,
  sex                 TEXT CHECK (sex IN ('M','F')),
  birth_date          TEXT,
  birth_state_code    TEXT,
  birth_comune_code   TEXT,
  birth_province      TEXT,
  citizenship_code    TEXT,
  res_state_code      TEXT,
  res_comune_code     TEXT,
  res_place_text      TEXT,
  doc_enc             TEXT,             -- JSON cifrato (AES-GCM): tipo, numero, luogo rilascio
  -- permanenza prevista (default = prenotazione) ed effettiva (individuale)
  planned_arrival     TEXT,
  planned_departure   TEXT,
  presence            TEXT NOT NULL DEFAULT 'prevista'
                       CHECK (presence IN ('prevista','presente','partita','non_arrivata')),
  stay_arrival        TEXT,
  stay_arrival_time   TEXT,
  stay_departure      TEXT,
  continues_guest_id  INTEGER REFERENCES guests(id),  -- stesso ospite nel soggiorno collegato precedente
  tax_status          TEXT NOT NULL DEFAULT 'ordinario',
  exemption_doc_ok    INTEGER NOT NULL DEFAULT 0,
  exemption_for_guest INTEGER REFERENCES guests(id),  -- accompagnatore di ...
  data_origin         TEXT NOT NULL DEFAULT 'manuale' CHECK (data_origin IN ('manuale','documento')),
  field_flags         TEXT NOT NULL DEFAULT '{}',
  verified_at         TEXT,
  alloggiati_status   TEXT NOT NULL DEFAULT 'da_preparare',
  alloggiati_note     TEXT,
  doc_purged_at       TEXT,
  anonymized_at       TEXT,
  version             INTEGER NOT NULL DEFAULT 1,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_guests_booking ON guests(booking_id);

-- ===== Movimenti economici (mai caselle "pagato") =====
-- direction: entrata (incasso), uscita (restituzione/rimborso), terzi (imposta gestita da terzi, documentata)
CREATE TABLE IF NOT EXISTS movements (
  id           INTEGER PRIMARY KEY,
  uid          TEXT NOT NULL UNIQUE,     -- chiave di idempotenza generata dall'interfaccia
  booking_id   INTEGER NOT NULL REFERENCES bookings(id),
  direction    TEXT NOT NULL CHECK (direction IN ('entrata','uscita','terzi')),
  amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
  op_date      TEXT NOT NULL,
  method       TEXT NOT NULL,
  causale      TEXT NOT NULL,
  reference    TEXT,
  reverses_id  INTEGER REFERENCES movements(id),   -- storno tracciato
  reversed_by  INTEGER REFERENCES movements(id),
  created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS allocations (
  id           INTEGER PRIMARY KEY,
  movement_id  INTEGER NOT NULL REFERENCES movements(id),
  category     TEXT NOT NULL CHECK (category IN ('soggiorno','imposta','cauzione')),
  amount_cents INTEGER NOT NULL CHECK (amount_cents > 0)
);

-- ===== Imposta di soggiorno =====
CREATE TABLE IF NOT EXISTS tax_rules (
  id            INTEGER PRIMARY KEY,
  comune        TEXT NOT NULL,
  category      TEXT NOT NULL,
  valid_from    TEXT NOT NULL,
  valid_to      TEXT NOT NULL,
  rate_cents    INTEGER NOT NULL,
  max_nights    INTEGER,
  minor_rule    TEXT NOT NULL CHECK (minor_rule IN ('da_chiarire','meno_di_12','fino_a_12_compresi')),
  exemptions    TEXT NOT NULL,          -- JSON lista codici
  seasonality   TEXT NOT NULL DEFAULT '[]',
  source        TEXT NOT NULL,
  verified_on   TEXT NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('da_verificare','approvata','revocata')),
  notes         TEXT,
  locked        INTEGER NOT NULL DEFAULT 0,  -- usata in conteggi consolidati: non modificabile
  created_at    TEXT NOT NULL,
  approved_at   TEXT
);

CREATE TABLE IF NOT EXISTS tax_assessments (
  id            INTEGER PRIMARY KEY,
  booking_id    INTEGER NOT NULL REFERENCES bookings(id),
  status        TEXT NOT NULL CHECK (status IN ('consolidato','superato')),
  total_cents   INTEGER NOT NULL,
  detail        TEXT NOT NULL,          -- righe per ospite e notte (nessun dato documentale)
  rule_ids      TEXT NOT NULL,
  reason        TEXT,
  supersedes_id INTEGER REFERENCES tax_assessments(id),
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS remittances (
  id           INTEGER PRIMARY KEY,
  uid          TEXT NOT NULL UNIQUE,
  year         INTEGER NOT NULL,
  quarter      INTEGER NOT NULL CHECK (quarter BETWEEN 1 AND 4),
  amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
  paid_on      TEXT NOT NULL,
  method       TEXT,
  reference    TEXT,
  note         TEXT,
  created_at   TEXT NOT NULL
);

-- Quietanze imposta: numerazione annuale mai riutilizzata, annullamento tracciato.
CREATE TABLE IF NOT EXISTS tax_receipts (
  id            INTEGER PRIMARY KEY,
  year          INTEGER NOT NULL,
  number        INTEGER NOT NULL,
  issued_on     TEXT NOT NULL,
  booking_id    INTEGER NOT NULL REFERENCES bookings(id),
  amount_cents  INTEGER NOT NULL,
  detail        TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'emessa' CHECK (status IN ('emessa','annullata')),
  cancel_reason TEXT,
  cancelled_at  TEXT,
  created_at    TEXT NOT NULL,
  UNIQUE (year, number)
);

-- Adempimenti periodici con stati indipendenti
CREATE TABLE IF NOT EXISTS obligations (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL,   -- comunicazione_trimestrale | dichiarazione_annuale
  period      TEXT NOT NULL,   -- es. 2026-T1, 2026
  status      TEXT NOT NULL,   -- da_fare | dichiarata
  declared_on TEXT,
  reference   TEXT,
  note        TEXT,
  updated_at  TEXT NOT NULL,
  UNIQUE (kind, period)
);

-- Chiusure di periodo: riepilogo identificabile, mai riscritto
CREATE TABLE IF NOT EXISTS period_closures (
  id            INTEGER PRIMARY KEY,
  kind          TEXT NOT NULL CHECK (kind IN ('mese','trimestre','anno')),
  period        TEXT NOT NULL,
  snapshot      TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('chiuso','superato')),
  supersedes_id INTEGER REFERENCES period_closures(id),
  reason        TEXT,
  created_at    TEXT NOT NULL
);

-- ===== Esportazioni =====
-- stati lotto: generato | caricamento_dichiarato | esito_registrato | da_correggere | superato
CREATE TABLE IF NOT EXISTS export_batches (
  id            INTEGER PRIMARY KEY,
  kind          TEXT NOT NULL CHECK (kind IN ('alloggiati','ross')),
  created_at    TEXT NOT NULL,
  period_from   TEXT,
  period_to     TEXT,
  file_name     TEXT NOT NULL,
  sha256        TEXT NOT NULL,
  item_count    INTEGER NOT NULL,
  profile       TEXT NOT NULL,        -- versione tracciato e tabelle
  checks        TEXT NOT NULL,        -- esito controlli locali (senza dati personali)
  status        TEXT NOT NULL DEFAULT 'generato',
  declared_at   TEXT,
  outcome_at    TEXT,
  outcome_note  TEXT,
  official_ref  TEXT,
  superseded_reason TEXT
);

-- item: ospite (Alloggiati) o giornata (ROSS); fingerprint = hash del contenuto, non il contenuto
CREATE TABLE IF NOT EXISTS export_items (
  id           INTEGER PRIMARY KEY,
  batch_id     INTEGER NOT NULL REFERENCES export_batches(id),
  guest_id     INTEGER,
  ross_day     TEXT,
  fingerprint  TEXT NOT NULL,
  outcome      TEXT,                  -- accettato | scartato | NULL (non registrato)
  outcome_note TEXT
);

CREATE TABLE IF NOT EXISTS ross_pending_deletions (
  id         INTEGER PRIMARY KEY,
  idswh      TEXT NOT NULL,
  tipo       TEXT NOT NULL,
  arrivo     TEXT NOT NULL,
  created_at TEXT NOT NULL,
  sent_batch INTEGER
);

-- Segnalazioni di rettifica (dati già comunicati o consolidati modificati)
CREATE TABLE IF NOT EXISTS corrections (
  id          INTEGER PRIMARY KEY,
  target      TEXT NOT NULL,   -- alloggiati | ross | imposta | periodo | quietanza
  entity      TEXT NOT NULL,
  entity_id   INTEGER NOT NULL,
  booking_id  INTEGER,
  reason      TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'aperta' CHECK (status IN ('aperta','gestita')),
  resolution  TEXT,
  created_at  TEXT NOT NULL,
  resolved_at TEXT
);

-- Allegati (ricevute ufficiali, ricevute di versamento): file cifrati in /allegati
CREATE TABLE IF NOT EXISTS attachments (
  id           INTEGER PRIMARY KEY,
  kind         TEXT NOT NULL,
  ref_table    TEXT,
  ref_id       INTEGER,
  filename     TEXT NOT NULL,
  mime         TEXT NOT NULL,
  stored_name  TEXT NOT NULL,
  size         INTEGER NOT NULL,
  sha256       TEXT NOT NULL,
  delete_after TEXT,
  created_at   TEXT NOT NULL
);

-- Registro eventi: solo azioni e identificativi, mai dati personali.
CREATE TABLE IF NOT EXISTS audit (
  id        INTEGER PRIMARY KEY,
  at        TEXT NOT NULL,
  action    TEXT NOT NULL,
  entity    TEXT,
  entity_id INTEGER,
  detail    TEXT
);

-- Manutenzione (schema v2): lavori da fare, avanzamento fino alla risoluzione. Stesso testo di db.MAINTENANCE_SQL.
CREATE TABLE IF NOT EXISTS maintenance_jobs (
  id          INTEGER PRIMARY KEY,
  title       TEXT NOT NULL,
  description TEXT,
  priority    TEXT NOT NULL DEFAULT 'normale' CHECK (priority IN ('urgente','normale','bassa')),
  due_date    TEXT,
  status      TEXT NOT NULL DEFAULT 'da_fare' CHECK (status IN ('da_fare','in_corso','risolto','annullato')),
  contractor  TEXT,
  quote_cents INTEGER,
  cost_cents  INTEGER,
  resolved_at TEXT,
  version     INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS maintenance_notes (
  id      INTEGER PRIMARY KEY,
  job_id  INTEGER NOT NULL REFERENCES maintenance_jobs(id),
  at      TEXT NOT NULL,
  kind    TEXT NOT NULL CHECK (kind IN ('nota','stato','modifica','allegato')),
  text    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_maintenance_notes_job ON maintenance_notes(job_id);

-- Manutenzione (schema v3): apparecchi, rubrica delle ditte, lavori periodici. Stesso testo di db.ASSETS_SQL.
CREATE TABLE IF NOT EXISTS maintenance_contractors (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  specialty  TEXT,
  phone      TEXT,
  email      TEXT,
  notes      TEXT,
  active     INTEGER NOT NULL DEFAULT 1,
  version    INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS maintenance_assets (
  id             INTEGER PRIMARY KEY,
  name           TEXT NOT NULL,
  category       TEXT,
  brand          TEXT,
  model          TEXT,
  location       TEXT,
  purchased_on   TEXT,
  warranty_until TEXT,
  notes          TEXT,
  active         INTEGER NOT NULL DEFAULT 1,
  version        INTEGER NOT NULL DEFAULT 1,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);
ALTER TABLE maintenance_jobs ADD COLUMN asset_id INTEGER REFERENCES maintenance_assets(id);
ALTER TABLE maintenance_jobs ADD COLUMN contractor_id INTEGER REFERENCES maintenance_contractors(id);
ALTER TABLE maintenance_jobs ADD COLUMN recur_months INTEGER CHECK (recur_months IS NULL OR recur_months BETWEEN 1 AND 120);
ALTER TABLE maintenance_jobs ADD COLUMN prev_job_id INTEGER REFERENCES maintenance_jobs(id);
ALTER TABLE maintenance_jobs ADD COLUMN next_job_id INTEGER REFERENCES maintenance_jobs(id);
CREATE INDEX IF NOT EXISTS ix_maintenance_jobs_asset ON maintenance_jobs(asset_id);
CREATE INDEX IF NOT EXISTS ix_maintenance_jobs_contractor ON maintenance_jobs(contractor_id);