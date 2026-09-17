(function () {
  // Registry aller List.js-Instanzen (Tabellen mit Sortierung/Suche), Key = Container-ID.
  window.hafinLists = window.hafinLists || {};

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

  // htmx tauscht Zeilen per outerHTML aus (z.B. Kategorie-Zuordnung, Umbuchungs-
  // Bestätigung) - danach müssen sowohl List.js (Sortier-/Suchindex) als auch
  // Tom Select (frisch eingefügte <select>-Elemente) neu synchronisiert werden.
  // Listener bewusst auf "document" statt "document.body": dieses Skript wird im
  // <head> geladen und läuft synchron, bevor <body> existiert - "document" ist
  // dagegen immer vorhanden, und htmx-Events blubbern ohnehin bis dorthin.
  document.addEventListener("htmx:afterSwap", function () {
    reindexAllTables();
    initSearchableSelects();
  });
})();
