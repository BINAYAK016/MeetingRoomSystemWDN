"use strict";

(() => {
  const form = document.getElementById("booking-wizard");
  const picker = document.getElementById("booking-attendee-picker");
  const configNode = document.getElementById("booking-ui-config");
  if (!form || !picker || !configNode) return;
  let config;
  try { config = JSON.parse(configNode.textContent); } catch { return; }
  if (!config.attendee_suggestions_url || !form.classList.contains("booking-enhanced")) return;
  const source = form.elements.namedItem("attendees");
  const query = document.getElementById("attendee-query");
  const options = document.getElementById("attendee-suggestions");
  const message = document.getElementById("attendee-picker-message");
  const organizerField = form.elements.namedItem("organizer_email");
  const initialOrganizer = document.getElementById("booking-organizer-label").textContent.trim();
  const organizer = () => (organizerField?.value.trim() || (config.staff ? config.actor_email : initialOrganizer)).toLowerCase();
  const addresses = () => Array.from(new Set(source.value.split(/[\s,;]+/).filter(Boolean).map(email => email.toLowerCase())));
  const validator = document.createElement("input");
  validator.type = "email";
  let timer = null;
  let controller = null;
  let generation = 0;
  let choices = [];
  let active = -1;

  function announce(text = "", error = false) {
    message.textContent = text;
    message.classList.toggle("field-error", error);
    query.setAttribute("aria-invalid", String(error));
  }
  function close() {
    options.hidden = true;
    query.setAttribute("aria-expanded", "false");
    query.removeAttribute("aria-activedescendant");
    active = -1;
  }
  function invalidate() {
    clearTimeout(timer);
    controller?.abort();
    generation += 1;
    choices = [];
    close();
  }
  function save(items) {
    source.value = items.join("\n");
    source.dispatchEvent(new Event("input", {bubbles: true}));
  }
  function add(text = query.value) {
    const incoming = text.split(/[\s,;]+/).filter(Boolean).map(email => email.toLowerCase());
    if (!incoming.length) return true;
    invalidate();
    for (const email of incoming) {
      validator.value = email;
      if (email.length > 254 || !validator.checkValidity()) {
        announce("Choose a colleague from the suggestions, or enter a complete email address.", true);
        query.focus();
        return false;
      }
    }
    const existing = addresses();
    const combined = Array.from(new Set([...existing, ...incoming])).filter(email => email !== organizer());
    if (combined.length > 50) {
      announce("You can invite at most 50 people by email.", true);
      query.focus();
      return false;
    }
    save(combined);
    const added = combined.filter(email => !existing.includes(email)).length;
    query.value = "";
    invalidate();
    announce(added ? `${added} attendee${added === 1 ? "" : "s"} added.` : "Already included in this meeting.");
    return true;
  }
  function select(index) {
    const choice = choices[index];
    if (!choice) return;
    add(choice.email);
    query.focus();
  }
  function highlight(index) {
    active = index;
    Array.from(options.children).forEach((option, i) => option.setAttribute("aria-selected", String(i === active)));
    const selected = options.children[active];
    if (selected) {
      query.setAttribute("aria-activedescendant", selected.id);
      selected.scrollIntoView({block: "nearest"});
    }
  }
  async function suggest(prefix, sequence) {
    controller = new AbortController();
    try {
      const response = await fetch(`${config.attendee_suggestions_url}?${new URLSearchParams({q: prefix})}`, {credentials: "same-origin", headers: {Accept: "application/json"}, cache: "no-store", signal: controller.signal});
      if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) throw new Error("directory");
      const data = await response.json();
      if (sequence !== generation || query.value.trim() !== prefix) return;
      if (!data.ok || !Array.isArray(data.results)) throw new Error("directory");
      const selected = addresses();
      choices = data.results.filter(person => typeof person.email === "string" && !selected.includes(person.email.toLowerCase()) && person.email.toLowerCase() !== organizer());
      options.replaceChildren(...choices.map((person, index) => {
        const option = document.createElement("button");
        option.type = "button";
        option.id = `attendee-option-${index}`;
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", "false");
        option.tabIndex = -1;
        const name = document.createElement("strong");
        name.textContent = person.name || person.email;
        const email = document.createElement("span");
        email.textContent = person.email;
        option.append(name, email);
        option.addEventListener("click", () => select(index));
        return option;
      }));
      active = -1;
      options.hidden = !choices.length;
      query.setAttribute("aria-expanded", String(Boolean(choices.length)));
      announce(choices.length ? `${choices.length} colleague${choices.length === 1 ? "" : "s"} found. Choose one, or use arrow keys and Enter.` : "No matching colleagues. You can add a complete email address.");
    } catch (error) {
      if (error.name === "AbortError" || sequence !== generation) return;
      close();
      announce("Suggestions are unavailable. You can still add a complete email address.");
    }
  }
  query.addEventListener("input", () => {
    invalidate();
    announce();
    const prefix = query.value.trim();
    if (prefix.length < 2 || prefix.length > 100 || /[\s,;]/.test(prefix)) return;
    const sequence = generation;
    timer = setTimeout(() => suggest(prefix, sequence), 200);
  });
  query.addEventListener("keydown", event => {
    if (["ArrowDown", "ArrowUp"].includes(event.key) && !options.hidden && choices.length) {
      event.preventDefault();
      highlight(event.key === "ArrowDown" ? (active + 1) % choices.length : (active < 0 ? choices.length - 1 : (active - 1 + choices.length) % choices.length));
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (active >= 0 && !options.hidden) select(active); else add();
    } else if (event.key === "Escape") invalidate();
  });
  document.getElementById("attendee-add").addEventListener("click", () => { add(); query.focus(); });
  document.getElementById("booking-attendee-chips").addEventListener("click", event => {
    const button = event.target.closest("[data-remove-attendee]");
    if (!button) return;
    save(addresses().filter(email => email !== button.dataset.removeAttendee));
    announce("Attendee removed.");
    query.focus();
    invalidate();
  });
  document.addEventListener("pointerdown", event => { if (!picker.contains(event.target)) close(); });
  picker.addEventListener("focusout", event => { if (!picker.contains(event.relatedTarget)) close(); });
  form.addEventListener("booking:commit-attendees", event => { if (!add()) event.preventDefault(); });
  window.addEventListener("pageshow", () => { invalidate(); announce(); });
  form.classList.add("attendee-picker-enhanced");
  document.getElementById("booking-attendee-source").hidden = true;
  picker.hidden = false;
  source.dispatchEvent(new Event("input", {bubbles: true}));
})();
