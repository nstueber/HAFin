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

  // Mehrfachauswahl (Buchungsliste): Toggle-Button schaltet die "show-ms"-Klasse
  // auf der Tabelle um (steuert die Sichtbarkeit der Checkbox-Spalte per CSS,
  // siehe .ms-cell in input.css). Aktionsleiste + "Kategorie zuweisen"-Button
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

  // Dieselben Klassen wie der aktive Zustand des "Nur unkategorisierte"-Buttons
  // (siehe transactions/list.html), damit beide Toggle-Buttons konsistent aussehen.
  var MULTISELECT_ACTIVE_CLASSES = ["!border-accent", "!text-accent"];

  document.addEventListener("click", function (e) {
    var toggle = e.target.closest && e.target.closest("[data-multiselect-toggle]");
    if (!toggle) return;
    var table = document.querySelector(toggle.getAttribute("data-multiselect-toggle"));
    if (!table) return;
    table.classList.toggle("show-ms");
    var active = table.classList.contains("show-ms");
    toggle.classList.toggle(MULTISELECT_ACTIVE_CLASSES[0], active);
    toggle.classList.toggle(MULTISELECT_ACTIVE_CLASSES[1], active);
    if (!active) {
      // Modus verlassen: Auswahl zuruecksetzen, Aktionsleiste ausblenden.
      document.querySelectorAll(".ms-checkbox:checked").forEach(function (cb) {
        cb.checked = false;
      });
      updateBulkBar();
    }
  });

  document.addEventListener("change", function (e) {
    if (e.target.matches && e.target.matches(".ms-checkbox")) {
      updateBulkBar();
    } else if (e.target.id === "bulk-category-select") {
      updateBulkAssignButton();
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
