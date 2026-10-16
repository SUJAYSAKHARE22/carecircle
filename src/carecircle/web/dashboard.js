(function () {
  "use strict";
  const { el, api, toast, pill, clear, empty } = CC;
  const $ = (id) => document.getElementById(id);
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const state = { data: null, selected: null, demo: false, timelineKey: "" };

  function view() {
    if (!state.data) return null;
    return state.data.elders.find((e) => e.name === state.selected) || state.data.elders[0] || null;
  }

  function daysLabel(days) {
    if (days.length === 7) return "every day";
    if (days.join() === "0,1,2,3,4") return "weekdays";
    if (days.join() === "5,6") return "weekends";
    return days.map((d) => DAYS[d]).join(", ");
  }

  function renderToday(v) {
    const s = v.summary;
    const line = $("status-line"), sub = $("status-sub");
    if (s.checked_in) {
      line.textContent = v.name + " checked in at " + s.first_checkin;
      sub.textContent = s.mood_label ? "Feeling " + s.mood_label : "No mood shared";
    } else if (v.checkin_state === "missed") {
      line.textContent = v.name + " hasn't checked in";
      sub.textContent = "Expected by " + v.expected_by + " — grace period is over.";
    } else if (v.checkin_state === "due") {
      line.textContent = "Waiting for " + v.name;
      sub.textContent = "Expected by " + v.expected_by + " — a gentle nudge has gone out.";
    } else {
      line.textContent = "Not yet today";
      sub.textContent = "Expected by " + v.expected_by;
    }
    const { total, taken } = s.reminders;
    $("rem-count").textContent = taken + " of " + total;
    $("meter-fill").style.width = total ? Math.round((taken / total) * 100) + "%" : "0%";
    $("meter").setAttribute("aria-valuenow", total ? String(Math.round((taken / total) * 100)) : "0");
    $("summary-text").textContent = s.text;
  }

  function renderAlerts(v) {
    const list = $("alerts"); clear(list);
    if (!v.alerts.length) { list.append(el("li", {}, empty("No alerts. Quiet is good."))); return; }
    for (const a of v.alerts) {
      list.append(el("li", { class: a.acknowledged ? "" : a.severity },
        el("div", { class: "row between" },
          el("span", { class: "row" }, pill(a.severity, a.severity), el("span", { class: "small muted", text: a.kind.replace("_", " ") + " · " + a.when })),
          a.acknowledged ? pill("handled", "ok") :
            el("button", { class: "small", text: "Mark handled", onclick: () => act(() => api("/api/alerts/" + a.id + "/ack", { method: "POST" }), "Alert marked as handled") })),
        el("div", { text: a.detail }),
        el("div", { class: "small muted", text: a.notified ? "Family notified" : "Not delivered yet" })));
    }
  }

  function renderReminders(v) {
    const events = $("events"); clear(events);
    if (!v.events_today.length) events.append(el("li", {}, empty("Nothing scheduled today.")));
    for (const e of v.events_today) {
      events.append(el("li", {}, el("div", { class: "row between" }, el("span", { text: e.title + " · " + e.due }), pill(e.status, e.status))));
    }
    const routines = $("reminders"); clear(routines);
    if (!v.reminders.length) routines.append(el("li", {}, empty("No routines yet.")));
    for (const r of v.reminders) {
      routines.append(el("li", {}, el("div", { class: "row between" },
        el("span", { text: r.title + " · " + r.time + " · " + daysLabel(r.days) }),
        el("button", { class: "small ghost", text: "Remove", onclick: () => act(() => api("/api/reminders/" + r.id, { method: "DELETE" }), "Routine removed") }))));
    }
  }

  function renderCircle(v) {
    const list = $("circle"); clear(list);
    for (const m of v.members) {
      list.append(el("li", {}, el("div", { class: "row between" },
        el("span", { text: m.name + (m.relation ? " (" + m.relation + ")" : "") }),
        el("span", { class: "row" }, pill(m.role, "info"), pill(m.telegram ? "Telegram linked" : "no Telegram", m.telegram ? "ok" : "attention")))));
    }
    const from = $("m-from"), to = $("m-to");
    const prev = { from: from.value, to: to.value };
    clear(from); clear(to);
    const names = [v.name, ...v.members.map((m) => m.name)];
    for (const n of names) { from.append(el("option", { value: n, text: n })); to.append(el("option", { value: n, text: n })); }
    from.value = prev.from && names.includes(prev.from) ? prev.from : (v.members[0] ? v.members[0].name : v.name);
    to.value = prev.to && names.includes(prev.to) ? prev.to : v.name;
  }

  async function renderTimeline(v) {
    const key = v.name + "|" + v.summary.text + "|" + v.alerts.length;
    if (key === state.timelineKey) return;
    state.timelineKey = key;
    try {
      const data = await api("/api/timeline/" + encodeURIComponent(v.name));
      const body = $("timeline"); clear(body);
      for (const d of data.days) {
        body.append(el("tr", {},
          el("td", { text: d.date }),
          el("td", { text: d.checked_in ? d.first_checkin : "—" }),
          el("td", { text: d.mood_label || "—" }),
          el("td", { text: d.reminders.total ? d.reminders.taken + "/" + d.reminders.total : "—" }),
          el("td", {}, d.concerns.length ? pill(String(d.concerns.length), d.concerns.some((c) => c.severity === "urgent") ? "urgent" : "attention") : "—")));
      }
    } catch (err) { state.timelineKey = ""; }
  }

  function render() {
    const v = view();
    if (!v) return;
    renderToday(v); renderAlerts(v); renderReminders(v); renderCircle(v); renderTimeline(v);
  }

  async function refresh(quiet) {
    try {
      state.data = await api("/api/overview");
      const select = $("elder");
      if (!select.options.length || select.options.length !== state.data.elders.length) {
        clear(select);
        for (const e of state.data.elders) select.append(el("option", { value: e.name, text: e.name }));
        if (!state.selected && state.data.elders[0]) state.selected = state.data.elders[0].name;
        select.value = state.selected;
      }
      if (!state.data.elders.length) toast("No elders yet. Run: carecircle seed-demo", "error");
      const cfg = await api("/api/config");
      state.demo = cfg.demo;
      $("demo-bar").classList.toggle("hidden", !cfg.demo);
      $("clock").textContent = "Server time " + cfg.now;
      $("updated").textContent = "Updated " + new Date().toLocaleTimeString();
      render();
    } catch (err) { if (!quiet) toast(err.message, "error"); }
  }

  async function act(fn, success) {
    try { await fn(); if (success) toast(success); state.timelineKey = ""; await refresh(); }
    catch (err) { toast(err.message, "error"); }
  }

  function bind() {
    $("elder").addEventListener("change", (e) => { state.selected = e.target.value; state.timelineKey = ""; render(); });
    $("reminder-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const v = view();
      act(async () => {
        await api("/api/reminders", { method: "POST", body: { person: v.name, title: $("r-title").value, time: $("r-time").value, days: $("r-days").value, requested_by: $("m-from").value !== v.name ? $("m-from").value : "" } });
        $("r-title").value = "";
      }, "Routine added");
    });
    $("message-form").addEventListener("submit", (e) => {
      e.preventDefault();
      act(async () => {
        await api("/api/messages", { method: "POST", body: { from: $("m-from").value, to: $("m-to").value, body: $("m-body").value } });
        $("m-body").value = "";
      }, "Message sent");
    });
    for (const btn of document.querySelectorAll("[data-advance]")) {
      btn.addEventListener("click", () => act(() => api("/api/demo/advance", { method: "POST", body: { minutes: Number(btn.dataset.advance) } }), "Clock advanced and monitor run"));
    }
    $("tick").addEventListener("click", () => act(() => api("/api/demo/tick", { method: "POST" }), "Monitor run"));
    $("reset-clock").addEventListener("click", () => act(() => api("/api/demo/reset-clock", { method: "POST" }), "Clock reset"));
  }

  bind();
  refresh();
  setInterval(() => refresh(true), 4000);
})();
