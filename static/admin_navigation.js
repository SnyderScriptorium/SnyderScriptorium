/* Single source of truth for admin dashboard tab navigation. */
(function () {
  "use strict";

  const TABS = ["write", "drafts", "published", "manuscripts", "about", "kwpreview", "stats", "inbox"];

  function showTab(name) {
    if (!TABS.includes(name)) name = "write";

    TABS.forEach((tab) => {
      const section = document.getElementById(tab);
      if (section) section.classList.toggle("hidden", tab !== name);

      const button = document.getElementById("tab-" + tab);
      if (button) {
        button.className = tab === name ? "" : "light";
        button.setAttribute("aria-selected", tab === name ? "true" : "false");
      }
    });

    if (name === "drafts" && typeof window.loadDrafts === "function") window.loadDrafts();
    if (name === "published" && typeof window.loadPublished === "function") window.loadPublished();
    if (name === "manuscripts" && typeof window.loadBooks === "function") window.loadBooks();
    if (name === "about" && typeof window.loadAbout === "function") window.loadAbout();
    if (name === "kwpreview" && typeof window.loadKWPreview === "function") window.loadKWPreview();
    if (name === "stats" && typeof window.loadStats === "function") window.loadStats(window.analyticsPeriod || "30");
    if (name === "inbox" && typeof window.loadInbox === "function") window.loadInbox();
  }

  window.switchTab = showTab;

  window.goHome = function () {
    window.location.href = "/";
  };

  window.logout = function () {
    window.location.href = "/admin/logout";
  };

  function wire() {
    const dashboard = document.getElementById("dashboard");
    if (!dashboard) return;

    document.querySelectorAll(".tabs button[id^='tab-']").forEach((button) => {
      const name = button.id.slice(4);
      if (!TABS.includes(name) || button.dataset.navigationWired === "1") return;
      button.dataset.navigationWired = "1";
      button.type = "button";
      button.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        showTab(name);
      });
    });

    showTab(TABS.find((name) => !document.getElementById(name)?.classList.contains("hidden")) || "write");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire, { once: true });
  } else {
    wire();
  }
})();
