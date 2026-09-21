(function () {
  // Registry aller List.js-Instanzen (Tabellen mit Sortierung/Suche), Key = Container-ID.
  window.hafinLists = window.hafinLists || {};

  // Zentrale Zahlenformatierung fuer alles, was clientseitig (nicht per Jinja-
  // Filter format_currency) gerendert wird - z.B. Chart.js-Tooltips/Achsen oder
  // live nachgerechnete Werte wie der Bargeld-Aufteilen-Restbetrag. Deutsches
  // Format ("," als Dezimal-, "." als Tausendertrennzeichen) inkl. Euro-Zeichen,
  // damit Zahlen App-weit konsistent aussehen, egal ob server- oder clientseitig
  // gerendert.
  var hafinCurrencyFormatter = new Intl.NumberFormat("de-DE", {
    style: "currency",
    currency: "EUR",
  });
  window.hafinFormatCurrency = function (value) {
    return hafinCurrencyFormatter.format(value);
  };
  // Variante ohne Euro-Zeichen, z.B. fuer Chart-Achsenbeschriftungen, wo das
  // Symbol bei vielen Ticks unnoetig Platz braucht.
  var hafinNumberFormatter = new Intl.NumberFormat("de-DE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  window.hafinFormatNumber = function (value) {
    return hafinNumberFormatter.format(value);
  };

  // Laedt per htmx-GET Inhalt in einen Dialog-Container und oeffnet den Dialog erst
  // danach - fuer alle Faelle, in denen ein <dialog> erst bei Bedarf befuellt wird
  // (Kategorie-Loeschbestaetigung, Dashboard-Drilldown in die Buchungsliste). Nutzt
  // htmx.ajax() statt eines deklarativen hx-get+hx-on Kombos, damit das Verhalten
  // nicht von der genauen htmx-Version/Attribut-Syntax abhaengt.
  window.hafinOpenDialog = function (url, dialogId, contentId) {
    htmx.ajax("GET", url, { target: "#" + contentId, swap: "innerHTML" }).then(function () {
      var dialog = document.getElementById(dialogId);
      if (dialog) dialog.showModal();
    });
  };

  // Buchungsdetails-Modal: "Bearbeiten" schaltet erst nach einer bestaetigten
  // Warnung in den Bearbeiten-Modus um (rein clientseitiges Sichtbarkeits-Toggle
  // zwischen #detail-view-section und #detail-edit-form, beide Teil derselben
  // htmx-Antwort - kein extra Request noetig, um den Bearbeiten-Modus zu
  // betreten). Als globale Funktionen definiert (nicht IIFE-lokal in _detail.html),
  // da das Modal bei jedem Oeffnen per htmx-Swap komplett neu gerendert wird.
  window.hafinConfirmEditTransaction = function () {
    var ok = window.confirm(
      "Achtung: Wird diese Buchung geändert, kann sie bei einem erneuten Import " +
      "derselben Quelldaten nicht mehr zuverlässig als bereits vorhanden erkannt " +
      "werden (Datum, Betrag, Verwendungszweck und Auftraggeber/Empfänger werden " +
      "für die Duplikat-Erkennung genutzt) und könnte dadurch versehentlich doppelt " +
      "importiert werden.\n\nTrotzdem bearbeiten?"
    );
    if (!ok) return;
    var view = document.getElementById("detail-view-section");
    var form = document.getElementById("detail-edit-form");
    if (view) view.classList.add("hidden");
    if (form) {
      form.classList.remove("hidden");
      if (window.hafinInitSearchableSelects) window.hafinInitSearchableSelects();
    }
  };
  window.hafinCancelEditTransaction = function () {
    var view = document.getElementById("detail-view-section");
    var form = document.getElementById("detail-edit-form");
    if (form) form.classList.add("hidden");
    if (view) view.classList.remove("hidden");
  };

  // List.js' eingebaute Suche (Version 2.3.1) hat zwei Bugs: (1) sie escaped
  // Regex-Sonderzeichen im Suchstring ("-", "+", ".", ...), vergleicht intern
  // aber trotzdem nur per einfachem indexOf() statt per Regex - das escapte
  // "\-" taucht im echten Text nie auf, daher liefert z.B. "-" nie Treffer;
  // (2) ihre eigene keyup/input-Bindung setzt die Liste beim Leeren des Felds
  // nicht zuverlässig zurück (u.a. beim Klick auf das native <input type=search>-
  // Clear-Icon, das nur ein "input"-, kein "keyup"-Event ausloest, in Kombination
  // mit ihrer eigenen "alreadyCleared"-Sonderbehandlung). Deshalb binden wir hier
  // eine eigene, robuste Suche: einfacher literaler Teilstring-Vergleich, ausgeloest
  // durch ein einzelnes "input"-Event (deckt Tippen, Backspace-bis-leer, Markieren+
  // Entf und den nativen Clear-Button gleichermaßen ab).
  function hafinMakeSearchFn(list) {
    return function (searchString, columns) {
      // searchString durchlief bereits List.js' eigene (fehlerhafte) Escape-Logik -
      // Backslashes vor Regex-Sonderzeichen wieder entfernen, um den literalen
      // Originaltext zurückzubekommen.
      var query = searchString.replace(/\\([-[\]{}()*+?.,\\^$|#])/g, "$1");
      for (var k = 0; k < list.items.length; k++) {
        var item = list.items[k];
        var found = false;
        if (query.length) {
          var values = item.values();
          for (var j = 0; j < columns.length; j++) {
            var col = columns[j];
            if (values.hasOwnProperty(col) && values[col] !== undefined && values[col] !== null) {
              var text = typeof values[col] === "string" ? values[col] : String(values[col]);
              if (text.toLowerCase().indexOf(query) !== -1) {
                found = true;
                break;
              }
            }
          }
        }
        item.found = found;
      }
    };
  }

  // Mobile Sortierung: Auf schmalen Viewports blenden die Karten-Tabellen (.table-stack /
  // .txn-cards, siehe input.css) ihre Kopfzeile aus - damit die Sortierung dort nicht
  // verloren geht, wird aus den sortierbaren Spaltenkoepfen (th.sort[data-sort]) ein
  // Auswahlfeld erzeugt (nur unterhalb md sichtbar), das list.sort() aufruft.
  function hafinAddMobileSort(el, list) {
    var ths = el.querySelectorAll("table.table-stack th.sort, table.txn-cards th.sort");
    if (!ths.length) return;
    var wrapper = ths[0].closest("table").parentElement;
    var select = document.createElement("select");
    select.className = "form-input mb-3 !py-1.5 !text-xs md:hidden";
    select.setAttribute("aria-label", "Sortierung");
    select.add(new Option("Sortieren nach…", ""));
    ths.forEach(function (th) {
      var key = th.getAttribute("data-sort");
      var labelEl = th.querySelector("span span");
      var label = labelEl ? labelEl.textContent.trim() : key;
      select.add(new Option(label + " ↑", key + "|asc"));
      select.add(new Option(label + " ↓", key + "|desc"));
    });
    select.addEventListener("change", function () {
      if (!select.value) return;
      var parts = select.value.split("|");
      list.sort(parts[0], { order: parts[1] });
    });
    wrapper.parentNode.insertBefore(select, wrapper);
  }

  window.hafinInitTable = function (containerId, valueNames, countElementId, emptyElementId) {
    var el = document.getElementById(containerId);
    if (!el) return;
    var existing = window.hafinLists[containerId];
    // Bereits initialisiert UND die Instanz gehoert noch zu einem Container, der
    // wirklich noch im DOM haengt (nicht der Fall z.B. wenn ein Dialog-Inhalt per
    // htmx-innerHTML-Swap komplett neu aufgebaut wurde, aber dieselbe Container-ID
    // wiederverwendet) - dann nicht doppelt initialisieren.
    if (existing && existing.listContainer && document.body.contains(existing.listContainer)) {
      return;
    }
    var list = new List(containerId, { valueNames: valueNames });
    window.hafinLists[containerId] = list;

    hafinAddMobileSort(el, list);

    var searchInput = el.querySelector(".hafin-search-input");
    if (searchInput) {
      var customSearch = hafinMakeSearchFn(list);
      searchInput.addEventListener("input", function () {
        list.search(searchInput.value, customSearch);
      });
    }

    if (countElementId || emptyElementId) {
      var countEl = countElementId ? document.getElementById(countElementId) : null;
      var emptyEl = emptyElementId ? document.getElementById(emptyElementId) : null;
      list.on("updated", function () {
        var n = list.matchingItems.length;
        if (countEl) countEl.textContent = n;
        if (emptyEl) emptyEl.classList.toggle("hidden", n !== 0);
      });
    }
  };

  function reindexAllTables() {
    for (var id in window.hafinLists) {
      var list = window.hafinLists[id];
      if (list && typeof list.reIndex === "function") {
        list.reIndex();
        // reIndex() setzt searched/filtered zurueck und parst die Liste neu, loest
        // dabei aber nicht zuverlaessig List.js' eigenes "updated"-Event aus (das
        // unsere Live-Trefferzahl aktualisiert) - deshalb hier explizit erzwingen,
        // statt uns auf internes reIndex()-Verhalten zu verlassen.
        if (typeof list.update === "function") {
          list.update();
        }
      }
    }
  }

  function initSearchableSelects() {
    var selects = document.querySelectorAll("select[data-searchable]");
    selects.forEach(function (select) {
      if (select.tomselect) return;
      new TomSelect(select, {
        allowEmptyOption: true,
        create: false,
      });
    });
  }
  // Oeffentlich verfuegbar fuer Faelle, in denen neue <select data-searchable>-
  // Elemente per reinem JS (nicht per htmx-Swap) ins DOM eingefuegt werden, z.B.
  // eine per JS geklonte Split-Zeile im Bargeld-Aufteilen-Formular.
  window.hafinInitSearchableSelects = initSearchableSelects;

  document.addEventListener("DOMContentLoaded", initSearchableSelects);

  // Mehrfachauswahl (Buchungsliste): Checkbox im "Ansicht anpassen"-Optionsmenue
  // schaltet ueber den generischen [data-toggle-class]-Handler (weiter unten) die
  // "show-ms"-Klasse auf der Tabelle um (steuert die Sichtbarkeit der Checkbox-Spalte
  // per CSS, siehe .ms-cell in input.css). Aktionsleiste + "Kategorie zuweisen"-Button
  // reagieren rein clientseitig auf die aktuell angehakten Checkboxen.
  function updateBulkAssignButton(checkedCount) {
    var btn = document.getElementById("bulk-assign-btn");
    var select = document.getElementById("bulk-category-select");
    if (!btn || !select) return;
    var count =
      typeof checkedCount === "number"
        ? checkedCount
        : document.querySelectorAll(".ms-checkbox:checked").length;
    btn.disabled = !(count > 0 && select.value !== "");
  }

  function updateBulkBar() {
    var bar = document.getElementById("bulk-action-bar");
    if (!bar) return;
    var checked = document.querySelectorAll(".ms-checkbox:checked");
    var countEl = document.getElementById("bulk-count");
    if (countEl) countEl.textContent = checked.length;
    if (checked.length > 0) {
      bar.classList.remove("hidden");
      bar.classList.add("flex");
    } else {
      bar.classList.add("hidden");
      bar.classList.remove("flex");
    }
    updateBulkAssignButton(checked.length);
  }

  // Zentrales "Ansicht anpassen"-Optionsmenue (z.B. Buchungsliste, siehe transactions/
  // list.html): jede Checkbox mit [data-toggle-class] + [data-toggle-target] schaltet
  // beim Aendern eine CSS-Klasse auf dem referenzierten Zielelement um (z.B. "show-ms"
  // fuer die Mehrfachauswahl-Checkbox-Spalte, "show-transfer-col" fuer die Umbuchungs-
  // spalte) - weitere Optionen lassen sich so ergaenzen, ohne dass der Tabellen-Header
  // mit immer mehr eigenen Buttons zuwaechst. [data-persist-key] merkt den Zustand
  // zusaetzlich fuer die Dauer der Session (sessionStorage) - bewusst KEIN dauerhaftes
  // serverseitiges Speichern, das ist fuer reine Anzeige-Praeferenzen nicht noetig.
  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches(".ms-checkbox")) {
      updateBulkBar();
      return;
    }
    if (e.target.id === "bulk-category-select") {
      updateBulkAssignButton();
      return;
    }
    var opt = e.target.closest && e.target.closest("[data-toggle-class]");
    if (!opt) return;
    var target = document.querySelector(opt.getAttribute("data-toggle-target"));
    var toggleClass = opt.getAttribute("data-toggle-class");
    if (target) {
      target.classList.toggle(toggleClass, opt.checked);
    }
    var persistKey = opt.getAttribute("data-persist-key");
    if (persistKey) {
      try {
        sessionStorage.setItem(persistKey, opt.checked ? "1" : "0");
      } catch (err) {
        // sessionStorage evtl. nicht verfuegbar (z.B. privater Modus) - Optionsstatus
        // geht dann beim Neuladen verloren, Grundfunktion bleibt unberuehrt.
      }
    }
    if (toggleClass === "show-ms" && !opt.checked) {
      // Mehrfachauswahl-Modus verlassen: Auswahl zuruecksetzen, Aktionsleiste ausblenden.
      document.querySelectorAll(".ms-checkbox:checked").forEach(function (cb) {
        cb.checked = false;
      });
      updateBulkBar();
    }
  });

  // Stellt beim Laden der Seite alle [data-persist-key]-Checkboxen (und die davon
  // abhaengige CSS-Klasse) aus sessionStorage wieder her, z.B. "Umbuchungsspalte
  // anzeigen" bleibt so fuer die Dauer der Session aktiv.
  function restorePersistedOptions() {
    document.querySelectorAll("[data-persist-key]").forEach(function (opt) {
      var stored;
      try {
        stored = sessionStorage.getItem(opt.getAttribute("data-persist-key"));
      } catch (err) {
        stored = null;
      }
      if (stored === "1" && !opt.checked) {
        opt.checked = true;
        opt.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
  }
  document.addEventListener("DOMContentLoaded", restorePersistedOptions);

  // Karten-Ansicht (mobil): Klick auf den "Mehr"-Button klappt Konto/Auftraggeber/
  // Umbuchung der jeweiligen Buchungskarte auf/zu (Klasse card-open auf der <tr>).
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-card-toggle]");
    if (!btn) return;
    var row = btn.closest("tr");
    if (!row) return;
    var open = row.classList.toggle("card-open");
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  });

  // Generisches Dropdown-Panel (aktuell das "Ansicht anpassen"-Optionsmenue): Klick auf
  // einen [data-dropdown-toggle]-Button oeffnet/schliesst das per CSS-Selektor referenzierte
  // Panel (Klasse "hafin-dropdown-panel"); Klick ausserhalb oder Escape schliesst es wieder.
  // Generisch statt fest an ein einzelnes Menue gebunden, damit sich weitere Dropdowns
  // (z.B. spaeter auf anderen Seiten) ohne neuen JS-Code ergaenzen lassen.
  document.addEventListener("click", function (e) {
    var toggle = e.target.closest && e.target.closest("[data-dropdown-toggle]");
    if (toggle) {
      var panel = document.querySelector(toggle.getAttribute("data-dropdown-toggle"));
      if (panel) {
        var willOpen = panel.classList.contains("hidden");
        document.querySelectorAll(".hafin-dropdown-panel").forEach(function (p) {
          p.classList.add("hidden");
        });
        panel.classList.toggle("hidden", !willOpen);
        toggle.setAttribute("aria-expanded", willOpen ? "true" : "false");
      }
      return;
    }
    if (!(e.target.closest && e.target.closest(".hafin-dropdown-panel"))) {
      document.querySelectorAll(".hafin-dropdown-panel").forEach(function (p) {
        p.classList.add("hidden");
      });
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      document.querySelectorAll(".hafin-dropdown-panel").forEach(function (p) {
        p.classList.add("hidden");
      });
    }
  });

  // htmx tauscht Zeilen per outerHTML aus (z.B. Kategorie-Zuordnung, Umbuchungs-
  // Bestätigung) - danach müssen sowohl List.js (Sortier-/Suchindex) als auch
  // Tom Select (frisch eingefügte <select>-Elemente) neu synchronisiert werden.
  // Listener bewusst auf "document" statt "document.body": dieses Skript wird im
  // <head> geladen und läuft synchron, bevor <body> existiert - "document" ist
  // dagegen immer vorhanden, und htmx-Events blubbern ohnehin bis dorthin.
  document.addEventListener("htmx:afterSwap", function () {
    reindexAllTables();
    initSearchableSelects();
    updateBulkBar();
  });
})();
