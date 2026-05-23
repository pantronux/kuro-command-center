(function () {
  const doc = document;
  const body = doc.body;

  function closeFloating() {
    doc.querySelectorAll(".floating-menu").forEach((node) => node.classList.add("hidden"));
  }

  function closeOverlays() {
    doc.querySelectorAll(".drawer, .modal").forEach((node) => node.classList.add("hidden"));
  }

  function openById(id) {
    const target = doc.getElementById(id);
    if (!target) return;
    if (target.classList.contains("floating-menu")) {
      closeFloating();
    }
    target.classList.remove("hidden");
  }

  function setView(name) {
    body.dataset.view = name;
    doc.querySelectorAll("[data-view]").forEach((node) => {
      node.classList.toggle("is-active", node.dataset.view === name);
    });
    doc.querySelectorAll(".mode-toggle button").forEach((button) => {
      const target = button.dataset.viewLink || "";
      button.classList.toggle("active", target === name || (name === "welcome" && target === "chat"));
    });
  }

  doc.addEventListener("click", (event) => {
    const openButton = event.target.closest("[data-open]");
    if (openButton) {
      event.preventDefault();
      openById(openButton.dataset.open);
      return;
    }

    const viewButton = event.target.closest("[data-view-link]");
    if (viewButton) {
      event.preventDefault();
      closeFloating();
      setView(viewButton.dataset.viewLink);
      return;
    }

    const closeButton = event.target.closest("[data-close]");
    if (closeButton) {
      event.preventDefault();
      closeFloating();
      closeOverlays();
      return;
    }

    const pillButton = event.target.closest("[data-toggle-pill]");
    if (pillButton) {
      event.preventDefault();
      const pill = doc.querySelector(`[data-pill="${pillButton.dataset.togglePill}"]`);
      if (pill) pill.classList.toggle("hidden");
      closeFloating();
      return;
    }

    if (event.target.closest("[data-toggle-admin]")) {
      body.dataset.admin = body.dataset.admin === "true" ? "false" : "true";
      event.target.textContent = body.dataset.admin === "true" ? "Admin On" : "Admin Off";
      closeFloating();
      return;
    }

    if (event.target.classList.contains("drawer") || event.target.classList.contains("modal")) {
      closeOverlays();
      return;
    }

    if (!event.target.closest(".floating-menu") && !event.target.closest("[data-open]")) {
      closeFloating();
    }
  });

  doc.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeFloating();
      closeOverlays();
    }
  });

  doc.querySelectorAll(".chat-row").forEach((row) => {
    row.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      openById("rename-modal");
    });
  });
})();
