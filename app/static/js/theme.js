(function () {
  var STORAGE_KEY = "haushaltsbuch-theme";

  function currentMode() {
    return document.body.classList.contains("dark") ? "dark" : "light";
  }

  document.addEventListener("DOMContentLoaded", function () {
    var toggle = document.getElementById("theme-toggle");
    if (!toggle) return;

    function syncIcon() {
      var icon = toggle.querySelector("i");
      if (icon) {
        icon.textContent = currentMode() === "dark" ? "light_mode" : "dark_mode";
      }
    }
    syncIcon();

    toggle.addEventListener("click", function () {
      var next = currentMode() === "dark" ? "light" : "dark";
      if (window.ui) {
        window.ui("mode", next);
      } else {
        document.body.classList.remove("light", "dark");
        document.body.classList.add(next);
      }
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch (e) {
        // ignorieren
      }
      syncIcon();
    });
  });
})();
