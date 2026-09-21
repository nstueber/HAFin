# Drittkomponenten und Lizenzen

Das Haushaltsbuch selbst steht unter der [MIT-Lizenz](https://github.com/nstueber/HAFin/blob/main/LICENSE) (Copyright (c) 2026 Nico Stueber).
Es verwendet die folgenden Drittkomponenten, die jeweils unter ihren eigenen Lizenzen stehen.

## Oberfläche (Browser)

| Komponente | Version | Lizenz | Copyright | Einbindung |
|---|---|---|---|---|
| [htmx](https://htmx.org) | 1.9.12 | 0BSD (Zero-Clause BSD) | – (der Lizenztext nennt keinen Rechteinhaber) | lokal ausgeliefert (`app/static/js/htmx.min.js`) |
| [List.js](https://listjs.com) | 2.3.1 | MIT | 2011–2018 Jonny Strömberg | Laden vom CDN (cdnjs) |
| [Tom Select](https://tom-select.js.org) | 2.6.2 | Apache License 2.0 | 2013–2015 Brian Reavis und Mitwirkende des Projekts [orchidjs/tom-select](https://github.com/orchidjs/tom-select) | Laden vom CDN (jsDelivr) |
| [Chart.js](https://www.chartjs.org) | 4.4.4 | MIT | 2014–2024 Chart.js Contributors | Laden vom CDN (jsDelivr) |
| [Tailwind CSS](https://tailwindcss.com) | 4.3.3 | MIT | Tailwind Labs, Inc. | beim Bauen des Images zu CSS kompiliert (Lizenzhinweis steht im erzeugten Stylesheet) |
| [Heroicons](https://heroicons.com) | – | MIT | Tailwind Labs, Inc. | als Inline-SVG in `app/templates/_icons.html` |
| [Material Design Icons](https://pictogrammers.com/library/mdi/) (Pictogrammers) | – | Apache License 2.0 | Pictogrammers | nur als Namensverweis (`mdi:cash-multiple`) für das Seitenleisten-Symbol in Home Assistant; das Symbol wird von Home Assistant dargestellt, nicht mitgeliefert |
| [Inter](https://rsms.me/inter/) (Schriftart, Rasmus Andersson) | – | SIL Open Font License 1.1 | The Inter Project Authors | steht zuerst in der Schriftenliste, wird aber **nicht** mitgeliefert – sie wird nur verwendet, wenn sie auf dem Gerät installiert ist |

## Server (Python)

| Komponente | Version | Lizenz | Copyright |
|---|---|---|---|
| [FastAPI](https://fastapi.tiangolo.com) | 0.115.6 | MIT | 2018 Sebastián Ramírez |
| [SQLModel](https://sqlmodel.tiangolo.com) | 0.0.42 | MIT | 2021 Sebastián Ramírez |
| [SQLAlchemy](https://www.sqlalchemy.org) (von SQLModel benötigt) | 2.0.x | MIT | 2005–2026 SQLAlchemy authors and contributors |
| [Starlette](https://www.starlette.io) (von FastAPI benötigt) | 0.41.x | BSD-3-Clause | 2018 Encode OSS Ltd. |
| [Pydantic](https://docs.pydantic.dev) (von FastAPI/SQLModel benötigt) | 2.x | MIT | 2017 bis heute Pydantic Services Inc. und Mitwirkende |
| [Jinja2](https://jinja.palletsprojects.com) | 3.1.5 | BSD-3-Clause | 2007 Pallets |
| [Uvicorn](https://www.uvicorn.org) | 0.34.0 | BSD-3-Clause | 2017 bis heute Encode OSS Ltd. |
| [python-multipart](https://github.com/Kludex/python-multipart) | 0.0.20 | Apache License 2.0 | 2012 Andrew Dunham |
| [charset-normalizer](https://github.com/jawah/charset_normalizer) | 3.5.1 | MIT | 2025 TAHRI Ahmed R. |
| [Python-Markdown](https://python-markdown.github.io) (Darstellung dieser Seite) | 3.10.3 | BSD-3-Clause | 2007, 2008 The Python Markdown Project |

Die Versionsangaben entsprechen `haushaltsbuch/requirements.txt` und den eingebundenen Skript-URLs; die
Lizenztexte liegen den jeweiligen Projekten bei (Links in der Tabelle).

## Lizenztexte der mitgelieferten Komponenten

### htmx – Zero-Clause BSD

Permission to use, copy, modify, and/or distribute this software for
any purpose with or without fee is hereby granted.

THE SOFTWARE IS PROVIDED “AS IS” AND THE AUTHOR DISCLAIMS ALL
WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES
OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE
FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY
DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN
AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT
OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

### Heroicons und Tailwind CSS – MIT

Copyright (c) Tailwind Labs, Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
