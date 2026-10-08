"use strict";

// Native forms remain functional without JavaScript. The dialog adds confirmation.
const confirmation = document.getElementById("action-confirmation");
let pendingForm = null;
let pendingSubmitter = null;
if (confirmation) {
  document.getElementById("confirmation-cancel").addEventListener("click", () => confirmation.close());
  confirmation.addEventListener("close", () => {
    pendingForm = null;
    pendingSubmitter = null;
  });
  document.getElementById("confirmation-proceed").addEventListener("click", () => {
    const form = pendingForm;
    const submitter = pendingSubmitter;
    confirmation.close();
    if (!form) return;
    form.dataset.confirmed = "true";
    form.requestSubmit(submitter || undefined);
    delete form.dataset.confirmed;
  });
}

// Prevent repeated submissions after the user confirms a valid form.
document.addEventListener("submit", (event) => {
  if (event.defaultPrevented) return;
  const form = event.target;
  if (form.method.toLowerCase() !== "post") return;
  if (form.dataset.submitting === "true") {
    event.preventDefault();
    return;
  }
  if (form.dataset.confirm && form.dataset.confirmed !== "true") {
    if (confirmation && typeof confirmation.showModal === "function") {
      event.preventDefault();
      pendingForm = form;
      pendingSubmitter = event.submitter;
      document.getElementById("confirmation-message").textContent = form.dataset.confirm;
      document.getElementById("confirmation-proceed").textContent = event.submitter?.textContent || "Continue";
      confirmation.showModal();
      return;
    }
    if (!window.confirm(form.dataset.confirm)) {
      event.preventDefault();
      return;
    }
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
