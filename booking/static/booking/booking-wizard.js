"use strict";

(() => {
  const form = document.getElementById("booking-wizard");
  const configNode = document.getElementById("booking-ui-config");
  if (!form || !configNode) return;
  let config;
  try { config = JSON.parse(configNode.textContent); } catch { return; }
  if (!config?.availability_url) return;

  const field = (name) => form.elements.namedItem(name);
  const get = (id) => document.getElementById(id);
  const date = field("date");
  const start = field("start_time");
  const end = field("end_time");
  const roomField = field("room");
  const recurrence = field("recurrence");
  const until = field("until_date");
  const override = field("override_reason");
  const guestCompany = field("guest_company_name");
  const attendees = field("attendees");
  const extraGuests = field("external_attendee_count");
  const organizerField = field("organizer_email");
  const initialOrganizer = get("booking-organizer-label").textContent.trim();
  const panes = Array.from(form.querySelectorAll("[data-wizard-pane]"));
  const stepButtons = Array.from(form.querySelectorAll(".booking-stepper [data-wizard-goto]"));
  const roomOptions = get("booking-room-options");
  const next = get("booking-step-next");
  const back = get("booking-step-back");
  const submit = get("booking-submit");
  const error = get("booking-wizard-error");
  const manualTimes = get("booking-manual-times");
  const minuteValue = (value) => /^\d{2}:\d{2}(?::\d{2})?$/.test(value) ? Number(value.slice(0, 2)) * 60 + Number(value.slice(3, 5)) : NaN;
  const clockValue = (minutes) => minutes >= 0 && minutes < 1440 ? `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}` : "";
  const displayTime = (value) => {
    const mins = minuteValue(value);
    if (!Number.isFinite(mins)) return "Choose time";
    const hours = Math.floor(mins / 60);
    return `${String(hours % 12 || 12).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")} ${hours >= 12 ? "PM" : "AM"}`;
  };
  const displayDate = (value, short = false) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return "Choose date";
    return new Intl.DateTimeFormat("en-GB", {timeZone: "UTC", weekday: short ? "short" : "long", day: "numeric", month: short ? "short" : "long", year: "numeric"}).format(new Date(`${value}T00:00:00Z`));
  };
  const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const icon = (name) => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "booking-icon");
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `#booking-${name}`);
    svg.append(use);
    return svg;
  };
  const setText = (id, value) => { get(id).textContent = value || "Not specified"; };
  let currentStep = 1;
  let reachedStep = 1;
  let duration = minuteValue(end.value) - minuteValue(start.value);
  let preferredDuration = Number.isFinite(duration) && duration > 0 ? duration : Number(config.minimum_minutes);
  let customDuration = ![30, 60, 90, 120].includes(duration);
  let timePage = 0;
  let availability = null;
  let roomData = [];
  let controller = null;
  let generation = 0;
  let timer = null;
  let requestPromise = null;
  let requestKey = "";
  let navigating = false;
  let verifiedSubmit = false;
  const opening = minuteValue(config.opens_at);
  const closing = minuteValue(config.closes_at);
  const increment = Number(config.slot_minutes);
  const overrideActive = () => Boolean(config.staff && override?.value.trim());
  const isExternal = () => ["external", "mixed"].includes(field("meeting_type").value);
  const organizer = () => (organizerField?.value.trim() || (config.staff ? config.actor_email : initialOrganizer) || initialOrganizer).toLowerCase();
  const addresses = () => Array.from(new Set(attendees.value.split(/[\s,;]+/).filter(Boolean).map(email => email.toLowerCase())));
  const headcount = () => 1 + addresses().filter(email => email !== organizer()).length + (Number.parseInt(extraGuests.value, 10) || 0);
  const selectedRoom = () => roomData.find(room => String(room.id) === roomField.value);

  function updateApprovalPolicy() {
    const room = selectedRoom();
    const editing = Boolean(config.booking_id);
    let text = "Choose a room to see whether your booking needs staff approval.";
    if (config.staff && !editing) {
      text = "New staff bookings are approved immediately. Confirmation emails are queued after saving.";
    } else if (room) {
      if (config.staff && form.dataset.bookingStatus === "approved") {
        text = "Your changes keep this staff-managed booking approved.";
      } else if (room.requires_approval) {
        text = editing && config.staff
          ? "This pending request still needs approval from the Staff desk after you save changes."
          : "This room requires staff approval. New or changed requests hold the room while Front Desk reviews them.";
      } else {
        text = "This room does not require staff approval. New or changed bookings are approved automatically, and confirmation emails are queued after saving.";
      }
      if (editing) text += " Saving without changes keeps the current booking status.";
    }
    text += ` Check in through your email within ${config.check_in_minutes} minutes of the approved start time.`;
    setText("booking-approval-policy", text);
    setText("booking-review-policy", `${text} Room availability and approval settings are checked again when you submit.`);
    get("booking-submit-label").textContent = editing ? "Save booking changes" : config.staff || room?.requires_approval === false ? "Confirm booking" : "Submit booking request";
  }

  function clearError() { error.hidden = true; error.textContent = ""; }
  function showError(message, target = null) {
    error.textContent = message;
    error.hidden = false;
    error.tabIndex = -1;
    if (target) {
      const targetPane = target.closest("[data-wizard-pane]");
      if (targetPane && targetPane.hidden) displayStep(Number(targetPane.dataset.wizardPane), false);
      if (target.closest("#booking-manual-times")) { customDuration = true; manualTimes.hidden = false; }
      if (target.closest("details")) target.closest("details").open = true;
      target.focus();
    } else error.focus();
  }
  function query() {
    const params = new URLSearchParams({date: date.value, start_time: start.value, end_time: end.value, recurrence: recurrence?.value || "none"});
    if (recurrence?.value !== "none" && until?.value) params.set("until_date", until.value);
    if (config.booking_id) params.set("booking_id", String(config.booking_id));
    if (overrideActive()) params.set("override_reason", override.value.trim());
    return params;
  }
  function scheduleReady() {
    return Boolean(date.value && start.value && end.value && (!recurrence || recurrence.value === "none" || until.value));
  }
  function durationControls() {
    form.querySelectorAll("[data-duration]").forEach(button => {
      const value = button.dataset.duration;
      const mins = Number(value);
      button.disabled = value !== "custom" && !overrideActive() && (mins < config.minimum_minutes || mins > config.maximum_minutes || mins % increment !== 0);
      button.setAttribute("aria-pressed", String(value === "custom" ? customDuration : !customDuration && mins === preferredDuration));
    });
    manualTimes.hidden = !(customDuration || overrideActive());
  }
  function renderTimeSlots(reset = false) {
    const slots = [];
    const needed = Number.isFinite(duration) && duration > 0 ? duration : preferredDuration;
    for (let minute = opening; minute < closing; minute += increment) slots.push(minute);
    if (reset) {
      const index = slots.indexOf(minuteValue(start.value));
      timePage = index < 0 ? 0 : Math.floor(index / 12);
    }
    const pageCount = Math.max(1, Math.ceil(slots.length / 12));
    timePage = Math.min(timePage, pageCount - 1);
    get("time-page-previous").disabled = timePage === 0;
    get("time-page-next").disabled = timePage >= pageCount - 1;
    get("time-page-label").textContent = `${timePage + 1} / ${pageCount}`;
    const localParts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {timeZone: "Asia/Kathmandu", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23"}).formatToParts(new Date()).map(part => [part.type, part.value]));
    const localDate = `${localParts.year}-${localParts.month}-${localParts.day}`;
    const nowMinute = Number(localParts.hour) * 60 + Number(localParts.minute);
    get("booking-time-slots").replaceChildren(...slots.slice(timePage * 12, timePage * 12 + 12).map(minute => {
      const button = make("button", "", displayTime(clockValue(minute)));
      button.type = "button";
      button.dataset.start = clockValue(minute);
      button.setAttribute("aria-pressed", String(minute === minuteValue(start.value)));
      button.disabled = date.value < localDate || date.value === localDate && minute <= nowMinute || !overrideActive() && minute + needed > closing;
      return button;
    }));
  }
  function updateScheduleLabel() {
    duration = minuteValue(end.value) - minuteValue(start.value);
    if (Number.isFinite(duration) && duration > 0) preferredDuration = duration;
    const durationText = Number.isFinite(duration) && duration > 0 ? ` (${duration >= 60 && duration % 60 === 0 ? `${duration / 60} hour${duration === 60 ? "" : "s"}` : `${duration} min`})` : "";
    setText("selected-time-label", start.value && end.value ? `${displayTime(start.value)} – ${displayTime(end.value)}${durationText}` : "Choose a start time");
    setText("selected-date-label", date.value ? displayDate(date.value, true) : "");
    if (recurrence) {
      const repeats = recurrence.value !== "none";
      get("booking-until-field").hidden = !repeats;
      until.required = repeats;
    }
    durationControls();
    renderTimeSlots();
  }
  function unknownRooms(message, loading = false) {
    availability = null;
    form.querySelectorAll(".booking-room-card").forEach(card => {
      delete card.dataset.available;
      delete card.dataset.capacityExceeded;
      card.querySelector("input").disabled = true;
      card.querySelector(".booking-room-status").textContent = loading ? "Checking…" : "Choose time";
      card.querySelector(".booking-room-conflict").textContent = "";
    });
    get("availability-summary").textContent = message;
    roomOptions.setAttribute("aria-busy", String(loading));
  }
  function createRoomCard(room) {
    const card = make("label", "booking-room-card");
    const radio = make("input");
    radio.type = "radio";
    radio.name = "room_choice";
    const info = make("span", "booking-room-info");
    info.append(make("strong"), make("span", "booking-room-location"), make("span", "booking-room-seats"), make("span", "booking-room-facilities"), make("span", "booking-room-approval"));
    const state = make("span", "booking-room-state");
    state.append(make("span", "booking-room-status"), make("span", "booking-room-conflict"));
    card.append(radio, make("span", "booking-room-photo"), info, state);
    card.dataset.roomId = String(room.id);
    return card;
  }
  function renderRooms(rooms) {
    const old = new Map(Array.from(roomOptions.querySelectorAll(".booking-room-card")).map(card => [card.dataset.roomId, card]));
    const cards = rooms.map(room => {
      const card = old.get(String(room.id)) || createRoomCard(room);
      card.dataset.roomId = String(room.id);
      card.dataset.roomCapacity = String(room.capacity);
      card.dataset.roomName = room.name;
      card.dataset.roomLocation = room.location;
      card.dataset.roomFloor = room.floor;
      card.dataset.available = String(room.available);
      const radio = card.querySelector("input");
      radio.value = String(room.id);
      radio.setAttribute("aria-label", `${room.name} at ${room.location}, floor ${room.floor}`);
      card.querySelector(".booking-room-info > strong").textContent = room.name;
      card.querySelector(".booking-room-location").textContent = `${room.location} · Floor ${room.floor}`;
      card.querySelector(".booking-room-seats").replaceChildren(icon("users"), document.createTextNode(`${room.capacity} seats`));
      const approval = card.querySelector(".booking-room-approval");
      approval.textContent = room.requires_approval ? "Staff approval required" : "Automatic approval";
      approval.dataset.requiresApproval = String(room.requires_approval);
      card.querySelector(".booking-room-facilities").replaceChildren(...(room.facilities.length ? room.facilities.map(name => {
        const span = make("span");
        let kind = "facility";
        if (/video|conference/i.test(name)) kind = "video";
        else if (/display|screen|projector/i.test(name)) kind = "display";
        else if (/whiteboard|board/i.test(name)) kind = "board";
        span.append(icon(kind), document.createTextNode(name));
        return span;
      }) : [make("span", "booking-no-facilities", "Facilities not listed")]));
      const photo = card.querySelector(".booking-room-photo");
      if (room.photo_url && new URL(room.photo_url, location.origin).origin === location.origin) {
        let img = photo.querySelector("img");
        if (!img) { img = make("img"); img.loading = "lazy"; photo.replaceChildren(img); }
        if (img.getAttribute("src") !== room.photo_url) img.src = room.photo_url;
        img.alt = room.name;
      } else photo.replaceChildren(icon("room"), make("span", "", "Room photo"));
      const conflicts = room.conflicts || [];
      let conflictText = "";
      if (conflicts.length) {
        const first = conflicts[0];
        const time = `${displayTime(first.occupied_from.slice(11, 16))} – ${displayTime(first.occupied_until.slice(11, 16))}`;
        conflictText = `${availability?.data.occurrences.length > 1 ? `${displayDate(first.date, true)} · ` : ""}${time} incl. buffer${conflicts.length > 1 ? ` +${conflicts.length - 1} more` : ""}`;
      }
      card.querySelector(".booking-room-conflict").textContent = conflictText;
      if (!Array.from(roomField.options).some(option => option.value === String(room.id))) roomField.add(new Option(room.name, String(room.id)));
      return card;
    });
    if (!cards.length) {
      const empty = make("div", "booking-empty-rooms");
      empty.append(icon("room"), make("h3", "", "Rooms are being prepared"), make("p", "", "Front Desk can add rooms and photos from the Staff desk."));
      roomOptions.replaceChildren(empty);
    } else roomOptions.replaceChildren(...cards);
    if (roomField.value && !rooms.some(room => String(room.id) === roomField.value && room.available)) {
      roomField.value = "";
      const message = get("booking-availability-message");
      message.textContent = "Your selected room is no longer available for this schedule. Choose another room.";
      message.hidden = false;
    }
    updateRoomSelection();
    updateHeadcount();
  }
  function updateRoomSelection() {
    form.querySelectorAll(".booking-room-card").forEach(card => {
      const chosen = card.dataset.roomId === roomField.value;
      card.dataset.selected = String(chosen);
      card.querySelector("input").checked = chosen;
    });
    updateApprovalPolicy();
    clearError();
  }
  function updateHeadcount() {
    const count = headcount();
    const room = selectedRoom();
    setText("booking-organizer-label", organizer());
    setText("booking-headcount", `${count} ${count === 1 ? "person" : "people"}`);
    setText("booking-capacity-label", room ? `${room.name} seats ${room.capacity} people.` : "Choose a room to see its capacity.");
    const capacityError = get("booking-capacity-error");
    capacityError.hidden = !room || count <= room.capacity;
    capacityError.textContent = room && count > room.capacity ? `This room seats ${room.capacity}; your meeting lists ${count}. Reduce the headcount or choose a larger room.` : "";
    setText("attendee-room-summary", room ? `${room.name} · ${room.location} · Floor ${room.floor}` : "Your selected room will appear here.");
    get("booking-attendee-chips").replaceChildren(...addresses().slice(0, 50).map(email => make("span", "booking-attendee-chip", email)));
    form.querySelectorAll(".booking-room-card").forEach(card => {
      const ready = card.dataset.available !== undefined;
      const available = card.dataset.available === "true";
      const fits = count <= Number(card.dataset.roomCapacity);
      card.dataset.capacityExceeded = String(!fits);
      card.querySelector("input").disabled = !ready || !available || !fits;
      if (ready) card.querySelector(".booking-room-status").textContent = !available ? "Unavailable" : !fits ? "Too small" : "Available";
    });
  }
  function updateMeetingControls() {
    form.querySelectorAll("[data-meeting-type]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.meetingType === field("meeting_type").value)));
    guestCompany.required = isExternal();
    get("booking-guest-company-field").hidden = !isExternal();
    form.querySelectorAll("[data-refreshments]").forEach(button => button.setAttribute("aria-pressed", String((button.dataset.refreshments === "yes") === field("refreshments_requested").checked)));
  }
  function scheduleChanged() {
    clearError();
    clearTimeout(timer);
    if (controller) controller.abort();
    generation += 1;
    requestPromise = null;
    updateScheduleLabel();
    get("booking-availability-message").hidden = true;
    unknownRooms(scheduleReady() ? "Checking availability for your selected schedule…" : "Choose a date, start and end time to check availability.", scheduleReady());
    if (scheduleReady()) timer = setTimeout(() => fetchAvailability(), 180);
  }
  async function fetchAvailability() {
    clearTimeout(timer);
    if (!scheduleReady()) return false;
    const key = query().toString();
    if (requestPromise && requestKey === key) return requestPromise;
    if (controller) controller.abort();
    controller = new AbortController();
    const signal = controller.signal;
    const sequence = ++generation;
    requestKey = key;
    unknownRooms("Checking availability for your selected schedule…", true);
    requestPromise = (async () => {
      try {
        const response = await fetch(`${config.availability_url}?${key}`, {credentials: "same-origin", headers: {Accept: "application/json"}, cache: "no-store", signal});
        if (!response.headers.get("content-type")?.includes("application/json")) throw new Error("The server could not check availability. Please sign in again or try later.");
        const data = await response.json();
        if (sequence !== generation || query().toString() !== key) return false;
        if (!response.ok || !data.ok) throw new Error(data.error || "Room availability could not be checked. Please try again.");
        availability = {key, data};
        roomData = data.rooms;
        roomOptions.setAttribute("aria-busy", "false");
        get("booking-availability-message").hidden = true;
        renderRooms(roomData);
        const availableCount = roomData.filter(room => room.available && room.capacity >= headcount()).length;
        get("availability-summary").textContent = `${availableCount} ${availableCount === 1 ? "room" : "rooms"} available for ${displayDate(date.value, true)}, ${displayTime(start.value)} – ${displayTime(end.value)}${data.occurrences.length > 1 ? ` · ${data.occurrences.length} occurrences` : ""}`;
        return true;
      } catch (failure) {
        if (failure.name === "AbortError" || sequence !== generation) return false;
        unknownRooms("Availability is not confirmed.");
        const message = get("booking-availability-message");
        message.textContent = failure.message === "Failed to fetch" ? "Unable to reach the server. Check your connection and try again." : failure.message;
        message.hidden = false;
        return false;
      } finally {
        if (sequence === generation) requestPromise = null;
      }
    })();
    return requestPromise;
  }
  function validateFields(pane) {
    for (const input of pane.querySelectorAll("input, select, textarea")) {
      if (["room", "room_choice"].includes(input.name) || input.disabled || input.type === "hidden" || input === until && recurrence?.value === "none") continue;
      if (!input.checkValidity()) { showError(input.validationMessage, input); return false; }
    }
    return true;
  }
  async function validateSchedule() {
    if (!validateFields(panes[0])) return false;
    if (!await fetchAvailability()) {
      showError(get("booking-availability-message").textContent || "Choose a valid date and time before continuing.");
      return false;
    }
    const room = selectedRoom();
    if (!room || !room.available || !availability || availability.key !== query().toString()) {
      showError("Choose an available meeting room for this schedule.", roomOptions.querySelector("input:not(:disabled)"));
      return false;
    }
    return true;
  }
  function validateAttendees() {
    if (!validateFields(panes[1])) return false;
    const items = addresses();
    const validator = document.createElement("input");
    validator.type = "email";
    for (const email of items) {
      validator.value = email;
      if (email.length > 254 || !validator.checkValidity()) { showError(`Check this attendee email address: ${email}`, attendees); return false; }
    }
    if (items.length > 50) { showError("A booking can have at most 50 email attendees.", attendees); return false; }
    const room = selectedRoom();
    if (room && headcount() > room.capacity) { showError(`This room seats ${room.capacity} people; the meeting lists ${headcount()}.`, extraGuests); return false; }
    return true;
  }
  function populateReview() {
    const room = selectedRoom();
    const node = get("review-room");
    node.replaceChildren(document.createTextNode(room?.name || "Choose a room"));
    if (room) node.append(make("span", "", `${room.location} · Floor ${room.floor} · ${room.capacity} seats`));
    setText("review-date", displayDate(date.value));
    setText("review-time", `${displayTime(start.value)} – ${displayTime(end.value)} (${duration} minutes, Nepal time)`);
    setText("review-recurrence", recurrence ? recurrence.options[recurrence.selectedIndex].text : "This occurrence only");
    get("review-occurrences").replaceChildren(...(availability?.data.occurrences || []).map(item => make("span", "", displayDate(item.date, true))));
    setText("review-title", field("title").value);
    setText("review-meeting-type", field("meeting_type").options[field("meeting_type").selectedIndex].text);
    setText("review-department", field("department").value);
    setText("review-description", field("description").value);
    get("review-guest-company-row").hidden = !isExternal();
    setText("review-guest-company", guestCompany.value);
    setText("review-refreshments", field("refreshments_requested").checked ? "Yes, refreshments requested" : "No");
    setText("review-notes", field("front_desk_notes").value);
    if (get("review-override")) setText("review-override", override?.value || "No rule override");
    setText("review-organizer", `Organizer: ${organizer()}`);
    const people = addresses().filter(email => email !== organizer());
    get("review-attendees").replaceChildren(...people.map(email => make("li", "", email)));
    const additional = Number.parseInt(extraGuests.value, 10) || 0;
    setText("review-headcount", `${headcount()} ${headcount() === 1 ? "person" : "people"} in total${additional ? `, including ${additional} additional ${additional === 1 ? "guest" : "guests"} without email.` : "."}`);
  }
  function displayStep(step, focus = true) {
    currentStep = step;
    reachedStep = Math.max(reachedStep, step);
    panes.forEach(pane => { pane.hidden = Number(pane.dataset.wizardPane) !== step; });
    stepButtons.forEach(button => {
      const number = Number(button.dataset.wizardGoto);
      button.disabled = number > reachedStep;
      button.dataset.complete = String(number < step);
      if (number === step) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
    });
    back.hidden = step === 1;
    next.hidden = step === 3;
    submit.hidden = step !== 3;
    next.textContent = step === 1 ? "Next: attendees" : "Next: review & confirm";
    next.append(icon("arrow"));
    if (step === 3) populateReview();
    if (focus) {
      const heading = panes[step - 1].querySelector("h2");
      heading.tabIndex = -1;
      heading.focus({preventScroll: true});
      form.scrollIntoView({behavior: "instant", block: "start"});
    }
  }
  async function goToStep(step) {
    if (navigating || step === currentStep) return;
    clearError();
    if (step < currentStep) { displayStep(step); return; }
    navigating = true;
    next.disabled = true;
    const origin = currentStep;
    try {
      if (!await validateSchedule()) { displayStep(1, false); return; }
      if (step === 3 && !validateAttendees()) { displayStep(2, false); return; }
      if (currentStep === origin) displayStep(step);
    } finally { navigating = false; next.disabled = false; }
  }

  form.classList.add("booking-enhanced");
  if (!config.staff) {
    date.min = config.today;
    date.max = config.latest_date;
    if (until) { until.min = date.value || config.today; until.max = config.latest_date; }
  }
  if (!date.value) date.value = config.today;
  if (!extraGuests.value) extraGuests.value = "0";
  form.querySelectorAll("[data-duration]").forEach(button => button.addEventListener("click", () => {
    customDuration = button.dataset.duration === "custom";
    if (!customDuration) { duration = Number(button.dataset.duration); preferredDuration = duration; end.value = clockValue(minuteValue(start.value) + duration); }
    scheduleChanged();
  }));
  get("booking-time-slots").addEventListener("click", event => {
    const button = event.target.closest("[data-start]");
    if (!button || button.disabled) return;
    const previous = Number.isFinite(duration) && duration > 0 ? duration : preferredDuration;
    start.value = button.dataset.start;
    end.value = clockValue(minuteValue(start.value) + (Number.isFinite(previous) && previous > 0 ? previous : config.minimum_minutes));
    scheduleChanged();
  });
  get("time-page-previous").addEventListener("click", () => { timePage -= 1; renderTimeSlots(); });
  get("time-page-next").addEventListener("click", () => { timePage += 1; renderTimeSlots(); });
  get("clear-booking-time").addEventListener("click", () => { start.value = ""; end.value = ""; scheduleChanged(); });
  [date, start, end, recurrence, until, override].filter(Boolean).forEach(input => input.addEventListener("input", () => {
    if (input === start || input === end) customDuration = ![30, 60, 90, 120].includes(minuteValue(end.value) - minuteValue(start.value));
    if (input === date && until && !config.staff) until.min = date.value || config.today;
    scheduleChanged();
  }));
  roomOptions.addEventListener("change", event => {
    if (event.target.name !== "room_choice") return;
    roomField.value = event.target.value;
    updateRoomSelection();
    updateHeadcount();
  });
  form.querySelectorAll("[data-meeting-type]").forEach(button => button.addEventListener("click", () => { field("meeting_type").value = button.dataset.meetingType; updateMeetingControls(); clearError(); }));
  form.querySelectorAll("[data-refreshments]").forEach(button => button.addEventListener("click", () => { field("refreshments_requested").checked = button.dataset.refreshments === "yes"; updateMeetingControls(); }));
  [attendees, extraGuests, organizerField].filter(Boolean).forEach(input => input.addEventListener("input", () => { updateHeadcount(); clearError(); }));
  [field("description"), field("front_desk_notes")].forEach(input => {
    const counter = make("small", "booking-character-count");
    input.after(counter);
    const update = () => { counter.textContent = `${input.value.length.toLocaleString()} / ${input.maxLength.toLocaleString()}`; };
    input.addEventListener("input", update);
    update();
  });
  form.querySelectorAll("[data-wizard-goto]").forEach(button => button.addEventListener("click", () => goToStep(Number(button.dataset.wizardGoto))));
  next.addEventListener("click", () => goToStep(currentStep + 1));
  back.addEventListener("click", () => goToStep(currentStep - 1));
  form.addEventListener("submit", async event => {
    if (verifiedSubmit) return;
    event.preventDefault();
    if (navigating) return;
    if (currentStep < 3) { await goToStep(currentStep + 1); return; }
    navigating = true;
    submit.disabled = true;
    clearError();
    try {
      const reviewedApproval = selectedRoom()?.requires_approval;
      if (!await validateSchedule()) { displayStep(1, false); return; }
      if (!validateAttendees()) { displayStep(2, false); return; }
      if (reviewedApproval !== selectedRoom()?.requires_approval) {
        populateReview();
        showError("The room’s approval setting changed. Review the updated information and submit again.");
        return;
      }
      verifiedSubmit = true;
      submit.disabled = false;
      form.requestSubmit(submit);
    } finally { if (!verifiedSubmit) submit.disabled = false; navigating = false; }
  });
  form.querySelectorAll("#booking-server-errors a").forEach(link => link.addEventListener("click", event => {
    const input = document.getElementById(link.getAttribute("href").slice(1));
    if (!input) return;
    event.preventDefault();
    const pane = input.closest("[data-wizard-pane]");
    if (pane) displayStep(Number(pane.dataset.wizardPane), false);
    if (input === roomField) roomOptions.querySelector("input:not(:disabled)")?.focus();
    else { if (input.closest("#booking-manual-times")) manualTimes.hidden = false; if (input.closest("details")) input.closest("details").open = true; input.focus(); }
  }));
  const errorPane = form.querySelector(".booking-field .field-error")?.closest("[data-wizard-pane]");
  displayStep(errorPane ? Number(errorPane.dataset.wizardPane) : 1, false);
  updateMeetingControls();
  updateHeadcount();
  renderTimeSlots(true);
  scheduleChanged();
  window.addEventListener("pageshow", event => {
    if (!event.persisted) return;
    verifiedSubmit = false;
    navigating = false;
    reachedStep = 1;
    next.disabled = false;
    submit.disabled = false;
    displayStep(1, false);
    scheduleChanged();
  });
})();
