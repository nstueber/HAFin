(function () {
  var STORAGE_KEY = "haushaltsbuch-theme";

  document.addEventListener("DOMContentLoaded", function () {
    var toggle = document.getElementById("theme-toggle");
    if (!toggle) return;

    toggle.addEventListener("click", function () {
      var isDark = document.documentElement.classList.toggle("dark");
      try {
        localStorage.setItem(STORAGE_KEY, isDark ? "dark" : "light");
      } catch (e) {
        // ignorieren
      }
    });
  });
})();
