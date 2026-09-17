(function () {
  // Registry aller List.js-Instanzen (Tabellen mit Sortierung/Suche), Key = Container-ID.
  window.hafinLists = window.hafinLists || {};

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

  window.hafinInitTable = function (containerId, valueNames) {
    var el = document.getElementById(containerId);
    if (!el || window.hafinLists[containerId]) return;
    window.hafinLists[containerId] = new List(containerId, { valueNames: valueNames });
  };

  function reindexAllTables() {
    for (var id in window.hafinLists) {
      var list = window.hafinLists[id];
      if (list && typeof list.reIndex === "function") {
        list.reIndex();
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

  document.addEventListener("click", function (e) {
    var toggle = e.target.closest && e.target.closest("[data-multiselect-toggle]");
    if (!toggle) return;
    var table = document.querySelector(toggle.getAttribute("data-multiselect-toggle"));
    if (!table) return;
    table.classList.toggle("show-ms");
    if (!table.classList.contains("show-ms")) {
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
