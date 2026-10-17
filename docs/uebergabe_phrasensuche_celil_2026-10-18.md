# Übergabe an Celil: optionale Phrasensuche

Stand: 18.10.2026 (Europe/Berlin). Ausgangscommit: `56ca3d9`.

Hallo Celil,

Berkan hat die Integration der Phrasensuche beauftragt. Sie ist als optionaler Parameter `phrase` in `search_logs` umgesetzt und auf Linux direkt gegen den vorhandenen vollständigen Datenbestand geprüft. Diese Datei wird zusammen mit der Implementierung geteilt.

## Änderung

- `search_logs(..., phrase=True)` verwendet `message @@ phraseto_tsquery(...)` mit gebundenem Suchtext.
- Standard `phrase=False`: bisherige Wortsuche bleibt erhalten.
- Phrasen verlangen benachbarte Tokens in derselben Reihenfolge. Groß-/Kleinschreibung und Satzzeichen folgen dem bestehenden Indexwörterbuch; das ist kein zeichengetreuer Teilstringvergleich.
- Trefferzählung und BM25-Ergebnisliste verwenden denselben Suchmodus und dieselben Filter. Evidence enthält `params.phrase`, den Suchmodus im Scope und die ausgeführte Ergebnisquery.
- Filter, Limits, BM25 und feste Sortierung bei gleichen Scores bleiben erhalten.
- Engineer-Prompt um einen Hinweis auf `phrase=true` bei bekanntem mehrteiligem Meldungstext ergänzt. README und Toolvertrag aktualisiert.
- Loader, Schema, Indizes sowie `count_by`/`trend` sind unverändert. Kein Neuimport und kein Indexneuaufbau nötig. Die Aggregationstools behalten ihre Teilstringsuche und bekommen keinen `phrase`-Parameter.

## Direkt gemessene Referenzzahlen (Linux)

| Abfrage | Treffer |
|---|---:|
| BGL-Phrase `failed to read message prefix` | 5.983 |
| Dieselbe Phrase mit `label=APPREAD` | 5.983 |
| BGL-Label `APPREAD` insgesamt | 5.983 |
| BGL-Wortsuche `ciod` | 350.567 |
| OpenStack-Wortsuche `Error during ComputeManager` | 4.069 |
| Dieselbe OpenStack-Suche als Phrase | 8 |

Damit deckt die geprüfte APPREAD-Phrase im vorhandenen Bestand exakt die APPREAD-Zeilen ab. Das ist ein möglicher Suchbeleg für die Worked Investigation, kein Nachweis der Ursache oder unabhängiger Incidents. Die alte README-Zahl 4.077 wurde durch die direkt gemessenen 4.069 ersetzt. Der historische Ursprung der alten Zahl wurde hier nicht untersucht.

## Übernehmen auf Windows

Im Repository zuerst `git status` prüfen und eigene Änderungen bei Bedarf sichern. Bei sauberem Stand:

```powershell
git pull --ff-only
```

Claude Code vollständig beenden und im Projekt neu starten, damit der MCP-Server die neue Tool-Signatur und den Engineer-Prompt lädt. Registrierung, `.env`, Daten und Abhängigkeiten brauchen wegen dieser Änderung keine Anpassung.

Zum Ausprobieren in Claude:

> Rufe search_logs mit dataset="bgl", text="failed to read message prefix", phrase=true und label="APPREAD" auf. Zeige rows_matched und die Evidence.

Direkter Python-Aufruf (zur Erklärung der Parameter):

```python
search_logs(
    dataset="bgl",
    text="failed to read message prefix",
    label="APPREAD",
    phrase=True,
)
```

## Tests und Grenzen der Abnahme

Auf Linux bestanden:

- 19 bestehende Tests ohne DB; sieben DB-Tests im Standardlauf erwartungsgemäß übersprungen.
- Drei neue lesende Integrationstests in `tests/test_search_phrase.py` gegen den vollständigen lokalen Bestand: Referenzzahlen, Label-Filter, Limits/Truncation/Evidence, BM25-Feld, Standard gegen explizites `phrase=False`, Großschreibung, falsche Wortreihenfolge und gebundener Suchtext mit SQL-Sonderzeichen.
- Python-Kompilierung und `git diff --check`.

Zum gezielten Nachprüfen auf Windows mit dem Python, in dem die Anforderungen installiert sind:

```powershell
$env:LOADER_DB_TESTS = "1"
python -m unittest discover -s tests -p test_search_phrase.py -v
Remove-Item Env:LOADER_DB_TESTS
```

Diese drei Tests sind lesend und erwarten die vollständigen Originaldaten sowie vorhandene Suchindizes. Die älteren vier Loader-DB-Tests wurden in dieser Änderungsrunde nicht erneut ausgeführt. Keine neuen Modellläufe oder vollständige Drei-Rollen-Abnahme; Windows wurde hier nicht getestet. Bitte den gezielten Windows-Gegentest und das Laden des aktualisierten Tools nach dem Neustart bestätigen.

Worked Investigation und andere Abgabeaufgaben sind mit dieser Änderung noch nicht erledigt.
