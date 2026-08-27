# Leitfaden zur Entwicklung weiterer Berechnungsmodule

Dieser Leitfaden beschreibt den verbindlichen technischen Vertrag für neue
Fachmodule in DIETER. Ziel ist, dass ein Modul dieselbe validierte Berechnung
ohne doppelte Fachlogik über Desktop, Web-API, CLI, JSON-, Text- und PDF-Ausgabe
bereitstellt.

Das Programm liefert ausschließlich überschlägige Vergleichsrechnungen. Ein
neues Modul darf nicht als normgerechte oder prüffähige Bemessung bezeichnet
werden.

## 1. Architektur und Datenfluss

```text
Desktop / Web / CLI
        |
        v
zentrale ModuleRegistry
        |
        v
CalculationModule.run(raw_values, project_metadata)
        |
        +-- input_parameters()
        +-- zentrale Typ-, Bereichs- und Plausibilitätsprüfung
        +-- calculate(validation, project_metadata)
        |
        v
CalculationResult
        |
        +-- Desktop-Ergebnisansicht
        +-- Web-API
        +-- JSON-Export
        +-- Text-Export
        +-- PDF-Bericht
```

Berechnungslogik gehört ausschließlich in das Fachmodell beziehungsweise das
Fachmodul. Registry, CLI, API, Desktopansicht und Reporting stellen Daten dar
oder transportieren sie, rechnen aber keine fachlichen Werte nach.

## 2. Empfohlene Dateien

Für ein einfaches Modul genügt eine Datei:

```text
tunnel_calc/modules/mein_modul.py
tests/test_mein_modul.py
```

Für ein umfangreiches Modul ist folgende Trennung vorgesehen:

```text
tunnel_calc/modules/mein_modul_model.py    # fachliches, UI-unabhängiges Modell
tunnel_calc/modules/mein_modul.py          # Adapter zur gemeinsamen Schnittstelle
tunnel_calc/modules/mein_modul_desktop.py  # optionale spezialisierte Tkinter-Ansicht
tests/test_mein_modul_model.py
tests/test_mein_modul.py
```

Das Fachmodell soll mit Dataclasses, Enums und typisierten Funktionen arbeiten.
Es darf weder Tkinter noch Web-, Export- oder PDF-Code importieren.

## 3. Verbindlicher Modulvertrag

Jedes ausführbare Modul leitet von `CalculationModule` ab und definiert diese
Klassenattribute:

- `module_id`: dauerhafte technische ID in `snake_case`; nach Veröffentlichung
  nicht mehr ändern, weil Registry, API und `.dieter`-Dateien sie verwenden.
- `display_name`: deutscher Anzeigename.
- `description`: kurze fachliche Beschreibung.
- `application_area`: vorgesehener Anwendungsbereich.
- `limitations`: fachliche Grenzen und ausgeschlossene Anwendungen.
- `is_implemented = True`: nur setzen, wenn Berechnung und Tests vollständig sind.
- `sort_order`: ganzzahlige Position im Modulcenter.

Die Registry ruft `validate_contract()` auf. Fehlerhafte Metadaten,
Parameterschlüssel, Wertebereiche, Auswahlwerte oder Standardwerte verhindern
die Registrierung mit einer verständlichen Fehlermeldung.

### Minimaler Adapter

```python
from tunnel_calc.core.models import ProjectMetadata
from tunnel_calc.core.parameters import ParameterDefinition, ValueRange
from tunnel_calc.core.result import (
    CalculationResult,
    CalculationStep,
    Formula,
    ResultItem,
    ResultMessage,
)
from tunnel_calc.core.validation import ValidationResult
from tunnel_calc.modules.base import CalculationModule


class MeinModul(CalculationModule):
    """Überschlägige Beispielberechnung für ..."""

    module_id = "mein_modul"
    display_name = "Mein Modul"
    description = "Berechnet überschlägig ..."
    application_area = "Variantenvergleich für ..."
    limitations = "Kein Ersatz für einen prüffähigen Nachweis; ..."
    is_implemented = True
    sort_order = 50

    def input_parameters(self) -> list[ParameterDefinition]:
        """Definiert alle über die gemeinsame Schnittstelle nutzbaren Eingaben."""
        return [
            ParameterDefinition(
                key="laenge_m",
                name="Länge",
                symbol="L",
                unit="m",
                description="Geometrische Eingangslänge.",
                default=1.0,
                allowed_range=ValueRange(min_value=0.01, max_value=100.0),
                plausible_range=ValueRange(min_value=0.1, max_value=20.0),
            )
        ]

    def calculate(
        self,
        validation: ValidationResult,
        project_metadata: ProjectMetadata,
    ) -> CalculationResult:
        """Führt die fachliche Berechnung mit bereits validierten Werten aus."""
        laenge = float(validation.values["laenge_m"])

        warnings = [
            ResultMessage(message=issue.message, code="PLAUSIBILITY")
            for issue in validation.warnings
        ]

        return CalculationResult(
            module_id=self.module_id,
            module_name=self.display_name,
            description=self.description,
            input_parameters=validation.parameter_values,
            assumptions=["Die Berechnung gilt für ..."],
            formulas=[Formula(label="Ansatz", expression="y = ...")],
            calculation_steps=[
                CalculationStep(
                    title="Berechnung von y",
                    expression=f"y = ... = {laenge:.3f}",
                    result=laenge,
                    unit="m",
                )
            ],
            final_results=[
                ResultItem(
                    name="Ergebniswert",
                    symbol="y",
                    value=laenge,
                    unit="m",
                    description="Überschlägiger Ergebniswert.",
                )
            ],
            warnings=warnings,
            project_metadata=project_metadata,
            application_area=self.application_area,
            limitations=self.limitations,
        )
```

`run()` darf nicht überschrieben werden. Die Basisklasse übernimmt dort die
zentrale Validierung, ruft `calculate()` auf und prüft anschließend den
Ergebnisvertrag.

## 4. Eingabeparameter richtig definieren

`input_parameters()` muss bei jedem Aufruf dieselbe geordnete Liste liefern.
Die Reihenfolge steuert Formulare und Berichte.

Jede `ParameterDefinition` benötigt:

- einen eindeutigen, stabilen `key` in `snake_case`;
- deutschen Namen, Formelzeichen, Einheit und Beschreibung;
- einen passenden `ParameterType` (`FLOAT`, `INTEGER`, `TEXT`, `BOOLEAN`);
- nach Möglichkeit einen fachlich sinnvollen Standardwert;
- einen harten `allowed_range` für unzulässige Werte;
- optional einen engeren `plausible_range` für nicht blockierende Warnungen;
- bei Auswahlen `choices=(("interner_wert", "Deutsche Anzeige"), ...)`.

Einheiten werden als Text am Wert geführt. Vorhandene Konstanten aus
`tunnel_calc/core/units.py` sollen wiederverwendet werden. Dimensionslose Werte
erhalten die Einheit `"-"`; eine leere Einheit ist nicht zulässig.

Wichtige Unterschiede:

- Ein Fehler im zulässigen Bereich blockiert die Berechnung.
- Eine Verletzung des Plausibilitätsbereichs erzeugt eine Warnung und lässt die
  Berechnung zu.
- `allow_negative=False` ist der Standard. Negative Werte müssen fachlich
  ausdrücklich freigegeben werden.
- Dezimalpunkt und Dezimalkomma werden bei numerischen Eingaben akzeptiert.
- Komplexe Tabellen können über einen dokumentierten `TEXT`-Parameter an das
  Fachmodell übergeben werden; Parsing und fachliche Prüfung liegen nicht in der
  Oberfläche.

Abhängigkeiten zwischen mehreren Parametern lassen sich nicht allein durch
`ValueRange` prüfen. Solche Regeln gehören in eine typisierte Modellvalidierung.
Ein fachlicher Modellfehler wird im Moduladapter in einen
`InputValidationError` mit `ValidationIssue` übersetzt. Erwartbare Eingabefehler
dürfen nicht als ungefangene `ValueError` bis zur Oberfläche gelangen.

## 5. Ergebnisvertrag und Berichtsfähigkeit

`calculate()` muss genau ein `CalculationResult` zurückgeben. Folgende Inhalte
sind fachlich erforderlich:

- alle validierten `input_parameters` in unveränderter Reihenfolge;
- sichtbare fachliche `assumptions`;
- verwendete `formulas`;
- nachvollziehbare `calculation_steps` mit eingesetzten Werten und Einheiten;
- relevante `intermediate_results`;
- mindestens ein fachliches `final_results`-Element;
- Plausibilitäts- und fachliche Warnungen in `warnings`;
- unveränderte `project_metadata`;
- `application_area` und `limitations` des Moduls;
- der zentrale Haftungs- und Anwendungshinweis.

Fehler verhindern normalerweise bereits die Berechnung und werden als
`InputValidationError` ausgegeben. `CalculationResult.errors` ist für Fehler
gedacht, die als Bestandteil eines bewusst erzeugten Teilergebnisses berichtet
werden müssen. Warnungen und Fehler dürfen nicht vermischt werden.

Vor der Rückgabe an eine Oberfläche prüft die Basisklasse unter anderem
Modul-ID, Modulname, Parameterreihenfolge, Einheiten und JSON-Serialisierbarkeit.
Damit ist dasselbe Ergebnis ohne Sonderkonvertierung für Web, JSON, Text und PDF
nutzbar. Fachobjekte wie Enums oder Dataclasses müssen vor Aufnahme in
`ResultItem.value` in einfache serialisierbare Werte überführt werden.

## 6. Registrierung und automatische Anbindungen

Das fertige Modul wird in `tunnel_calc/app/registry.py` importiert und in
`create_default_registry()` instanziiert:

```python
registry.register_many(
    [
        # bestehende Module ...
        MeinModul(),
    ]
)
```

Danach funktionieren ohne weiteren Fachcode:

| Schnittstelle | Anbindung |
| --- | --- |
| Registry und Modulcenter | automatisch über `create_default_registry()` |
| CLI | automatisch über Parameterdefinitionen und `CalculationResult` |
| Web-API | automatisch über `tunnel_calc/web/api.py` |
| generische Desktopmaske | automatisch, wenn keine Spezialansicht zugeordnet ist |
| JSON-Export | automatisch über `CalculationResult.to_dict()` |
| Text-Export | automatisch über die strukturierte Ergebnisliste |
| Standard-PDF | automatisch über die strukturierte Ergebnisliste |

Die Weboberfläche und die generische Desktopmaske dürfen keine zusätzliche
Berechnungsformel erhalten. Wenn eine Eingabe dort nicht darstellbar ist, wird
die gemeinsame Parameter- oder UI-Schnittstelle erweitert und getestet.

## 7. Optionale spezialisierte Desktopansicht

Eine spezialisierte Tkinter-Ansicht ist nur für fachlich notwendige Tabellen,
Diagramme oder Interaktionen erforderlich. Sie bleibt ein Adapter zum selben
Fachmodell.

Konventionen:

- Datei `tunnel_calc/modules/mein_modul_desktop.py`;
- öffentliche Funktion `embed(parent, on_back)`;
- die zurückgegebene Ansicht besitzt bei `.dieter`-Unterstützung
  `load_project_state(data)` und eine korrespondierende Speicherlogik;
- Berechnen-Schaltflächen rufen das Fachmodell oder `MeinModul.run()` auf;
- PDF-Code erhält strukturierte Ergebnisdaten, keine Rohwerte aus Widgets;
- Farben, Logo und Symbol stammen aus den zentralen Desktop-/Asset-Vorgaben.

Die Ansicht wird in `tunnel_calc/desktop/app.py` importiert und in
`TunnelCalcDesktop._open_module()` anhand der stabilen `module_id` zugeordnet.
Ohne Zuordnung öffnet sich automatisch `GenericModuleWindow`.

## 8. Platzhaltermodule

Ein noch nicht fachlich implementiertes Modul leitet von
`StubCalculationModule` ab. Es definiert Metadaten und gegebenenfalls spätere
Eingabeparameter, aber keine Dummyformel. `is_implemented` bleibt `False`; der
Aufruf endet kontrolliert mit `ModuleNotImplementedError`.

Ein Platzhalter wird erst in die Standard-Registry aufgenommen, wenn er im
Modulcenter tatsächlich angezeigt werden soll. Pseudo-Fachberechnungen zum
Füllen einer Karte sind ausgeschlossen.

## 9. Verbindliche Tests

Mindestens folgende Tests gehören zu jedem neuen Modul:

1. Standardfall mit unabhängig nachgerechneten Erwartungswerten.
2. Fachlich relevanter zweiter Berechnungsfall.
3. Untere und obere Randwerte.
4. Fehler für fehlende, falsch typisierte und unzulässige Eingaben.
5. Warnung außerhalb des Plausibilitätsbereichs.
6. Abhängige Eingaberegeln des Fachmodells.
7. Vollständigkeit von Annahmen, Formeln, Rechenschritten und Einheiten.
8. Übernahme der Projektmetadaten.
9. Registry-Reihenfolge beziehungsweise Registrierung.
10. Bei Spezialansicht: Öffnen, Berechnen, Zurücknavigation, minimale
    Fenstergröße und Laden/Speichern von Projekteingaben.

`tests/test_module_interfaces.py` ist der gemeinsame Integrationstest. Er führt
jedes registrierte Modul mit seinen Standardwerten aus und prüft Registry,
Web-Serialisierung sowie JSON-, Text- und PDF-Ausgabe. Deshalb müssen
registrierte ausführbare Module konsistente Standardwerte besitzen.

Tests aus dem Projektstamm starten:

```powershell
python -m unittest discover -s tests
```

Für einen schnellen Modultest:

```powershell
python -m unittest tests.test_mein_modul tests.test_module_interfaces
```

Bestehende Tests dürfen nicht entfernt oder abgeschwächt werden, um fachliche
oder technische Fehler zu verdecken.

## 10. Definition of Done

Ein neues Modul gilt erst als integriert, wenn alle Punkte erfüllt sind:

- Fachquelle, Formel und sämtliche Annahmen sind im Code dokumentiert.
- Fachmodell und Moduladapter sind typisiert und frei von UI-Abhängigkeiten.
- Alle Eingaben besitzen Einheiten, Grenzen und verständliche Beschreibungen.
- Harte Fehler und Plausibilitätswarnungen sind getrennt.
- Ergebnis enthält Eingaben, Annahmen, Formeln, Rechenweg, Ergebnisse und
  Einheiten.
- Der Hinweis auf die überschlägige Vergleichsrechnung bleibt enthalten.
- Modul ist genau einmal in der Standard-Registry registriert.
- Generische oder spezialisierte Desktopansicht funktioniert.
- Web-API, CLI, JSON, Text und PDF verwenden das identische Ergebnisobjekt.
- Modul-, Modell-, Randwert- und Schnittstellentests sind grün.
- Es wurde keine Fachlogik in Oberfläche, API oder Reporting dupliziert.

