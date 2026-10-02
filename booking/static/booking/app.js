"use strict";

// Native forms remain functional without JavaScript. Prevent repeated submissions.
document.addEventListener("submit", (event) => {
  const form = event.target;
  if (form.method.toLowerCase() !== "post") return;
  if (form.dataset.submitting === "true") {
    event.preventDefault();
    return;
  }
  form.dataset.submitting = "true";
  form.setAttribute("aria-busy", "true");
  form.querySelectorAll("button[type=submit], button:not([type])").forEach((button) => {
    button.dataset.originalText = button.textContent;
    button.textContent = "Please wait…";
    button.disabled = true;
  });
});

window.addEventListener("pageshow", () => {
  document.querySelectorAll("form[data-submitting]").forEach((form) => {
    delete form.dataset.submitting;
    form.removeAttribute("aria-busy");
    form.querySelectorAll("button[data-original-text]").forEach((button) => {
      button.textContent = button.dataset.originalText;
      button.disabled = false;
    });
  });
});

document.querySelectorAll(".app-nav a, .staff-nav a").forEach((link) => {
  if (new URL(link.href).pathname === window.location.pathname) {
    link.setAttribute("aria-current", "page");
  }
});
