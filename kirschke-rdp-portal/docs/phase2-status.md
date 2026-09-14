# Status der nicht integrierten Cloud-Module (Phase 2/3)

Stand: 11.09.2026. Gilt für Portal 0.2.12 / Agent 1.3.0.

## Worum es geht

Rund 5 700 Zeilen Entra-, Graph- und SharePoint-Code liegen im Repository, sind
aber **kein Bestandteil des laufenden Pilotbetriebs**. Sie werden vom aktiven
Programmstart nicht erreicht und haben **keine Tests**. Diese Seite hält fest,
welche Module das sind, was an ihnen nachweislich defekt ist und wie damit
umzugehen ist — damit niemand sie für einsatzbereit hält.

## Betroffene Module

| Modul | Zeilen | Status |
| --- | --- | --- |
| `portal_app/auth/entra_auth.py` | 686 | nicht integriert, **defekt** (siehe unten) |
| `portal_app/graph/client.py` | 908 | nicht integriert, ungetestet |
| `portal_app/graph/sharepoint.py` | 1 249 | nicht integriert, ungetestet |
| `portal_app/graph/mock_graph.py` | 99 | Testdouble ohne Test |
| `workstation_agent/graph/client.py` | 1 045 | nicht integriert, ungetestet |
| `workstation_agent/graph/sharepoint.py` | 338 | nicht integriert, ungetestet |
| `workstation_agent/outbox/handler.py` | 641 | nicht integriert, ungetestet |
| `workstation_agent/commands/handler.py` | 472 | **unerreichbar**, siehe Remote-Befehle |

## Bekannter Defekt: Der Entra-Token-Cache ist nicht lauffähig

`portal_app/auth/entra_auth.py` kann in der vorliegenden Form keinen Token
speichern. `msal.SerializableTokenCache.serialize()` liefert einen `str`,
`TokenCache.set()` ruft darauf `cache.copy()` auf:

```
set(serialize())   -> AttributeError: 'str' object has no attribute 'copy'
deserialize(get()) -> TypeError: the JSON object must be str, bytes or
                      bytearray, not dict
```

Der Fehler besteht in beide Richtungen. Jeder Tokenerwerb würde beim Schreiben
des Caches abbrechen.

**Dies ist absichtlich nicht behoben.** Die Schnittstelle ändert sich bei der
Integration ohnehin, und eine Reparatur ohne Tests würde nur den Eindruck von
Funktionsfähigkeit erzeugen. Bei der Aktivierung von Phase 2 ist dieser Bereich
mit Tests neu aufzusetzen.

## Weitere offene Punkte bei einer Aktivierung

* **Tokens liegen im Klartext.** Der Cache schreibt unverschlüsseltes JSON mit
  Standard-ACL. Auf Windows gehört das über DPAPI abgesichert
  (`msal-extensions`), bevor echte Refresh-Tokens darin landen.
* **Der Device-Flow hat keine Oberfläche.** Verifizierungs-URL und Code gehen
  jetzt ins Log statt nach stdout — ein fensterloses Portal hat keine Konsole.
  Für den echten Betrieb braucht der Code einen Dialog.
* **Keine Prüfung gegen echte Graph-Antworten.** Die Konverter in
  `sharepoint.py` sind nie gegen eine reale Liste gelaufen.

## Remote-Adminbefehle

`workstation_agent/commands/handler.py` ist **vollständig unerreichbar**: außer
dem eigenen `__init__.py` importiert es nichts. `service.py::_check_admin_commands`
ist mit schriftlicher Begründung deaktiviert, und
`tests/test_pilot_regressions.py` sichert ab, dass nichts daraus aufgerufen wird.

Vor einer Wiederaktivierung fehlen laut dem Kommentar im Code drei Dinge:
eine geprüfte Befehlsautorisierung, ein belastbarer Anspruchsnachweis und ein
Schutz gegen Wiedereinspielung. Der Abmeldepfad über den Statuskanal
(`shared/status_pipe.py` + `workstation_agent/session_control.py`) löst genau
diese drei Punkte und ist die Vorlage, an der sich eine Neufassung orientieren
sollte.

## Regel für Änderungen

Wer eines dieser Module anfasst, schreibt **zuerst** einen Test dafür. Ohne Test
ist jede Änderung daran nicht überprüfbar — genau so ist der oben beschriebene
Defekt unentdeckt geblieben.
