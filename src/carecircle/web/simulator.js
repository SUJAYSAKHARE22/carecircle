(function () {
  "use strict";
  const { el, api, toast, pill, pretty, clear, empty } = CC;
  const $ = (id) => document.getElementById(id);

  const CHIPS = {
    en: ["Good morning, I feel fine", "I took my blood pressure tablet", "I feel dizzy", "I fell down in the bathroom", "Tell my son to call me", "Do I have any messages?"],
    hi: ["सुप्रभात, मैं ठीक हूँ", "मैंने दवाई ले ली", "मुझे चक्कर आ रहे हैं", "मैं गिर गई", "बेटे को बोलो मुझे फोन करे", "क्या मेरे लिए कोई संदेश है?"],
    mr: ["सुप्रभात, मी बरी आहे", "मी गोळी घेतली", "मला चक्कर येत आहे", "मी पडले", "मुलाला सांगा मला फोन करा", "माझे काही संदेश आहेत का?"],
  };
  const state = { elders: [], busy: false, seenAlerts: new Set(), firstPoll: true, listening: false };

  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null;

  function currentElder() { return state.elders.find((e) => e.name === $("person").value) || state.elders[0]; }
  function activeLang() { return $("lang").value || (currentElder() && currentElder().language) || "en"; }
  const SPEECH = { en: "en-IN", hi: "hi-IN", mr: "mr-IN" };

  function renderChips() {
    const box = $("chips"); clear(box);
    for (const phrase of CHIPS[activeLang()] || CHIPS.en) {
      box.append(el("button", { class: "chip", type: "button", text: phrase, onclick: () => submit(phrase) }));
    }
  }

  function addBubble(who, text) {
    const chat = $("chat");
    chat.append(el("div", { class: "bubble " + who, text }));
    chat.scrollTop = chat.scrollHeight;
  }

  function addCalls(calls) {
    const box = $("calls");
    for (const call of calls) {
      const ok = call.result && call.result.ok !== false;
      const level = call.result && call.result.concern_level;
      box.prepend(el("details", { class: "call", open: call.name === "log_checkin" ? true : null },
        el("summary", {}, el("span", { class: "name", text: call.name }),
          pill(ok ? "ok" : "error", ok ? "ok" : "urgent"),
          level && level !== "info" ? pill(level, level) : null,
          el("span", { class: "muted small", text: call.ms + " ms" })),
        el("pre", { text: "→ " + pretty(call.arguments) + "\n← " + pretty(call.result) })));
    }
  }

  function speak(text, lang) {
    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = lang;
    const voice = window.speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().startsWith(lang.slice(0, 2).toLowerCase()));
    if (voice) utterance.voice = voice;
    window.speechSynthesis.speak(utterance);
  }

  async function submit(text) {
    text = (text || "").trim();
    if (!text || state.busy) return;
    state.busy = true; $("send").disabled = true;
    addBubble("you", text); $("text").value = "";
    try {
      const result = await api("/api/sim/turn", { method: "POST", body: {
        person: $("person").value, text, lang: $("lang").value || null, use_llm: $("brain").value === "llm" } });
      addBubble("alexa", result.reply);
      addCalls(result.tool_calls);
      speak(result.reply, result.speech_lang);
      pollAlerts();
    } catch (err) {
      addBubble("alexa", "Sorry, I couldn't do that. " + err.message);
      toast(err.message, "error");
    } finally {
      state.busy = false; $("send").disabled = false;
    }
  }

  function setupMic() {
    const mic = $("mic");
    if (!Recognition) {
      mic.disabled = true;
      $("mic-status").textContent = "Speech recognition isn't available in this browser (try Chrome). Type instead.";
      return;
    }
    recognition = new Recognition();
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    recognition.onresult = (event) => {
      const result = event.results[event.results.length - 1];
      $("mic-status").textContent = result[0].transcript;
      if (result.isFinal) submit(result[0].transcript);
    };
    recognition.onerror = (event) => { $("mic-status").textContent = "Mic error: " + event.error; };
    recognition.onend = () => { state.listening = false; mic.classList.remove("live"); if ($("mic-status").textContent === "Listening…") $("mic-status").textContent = "Click the mic and speak."; };
    mic.addEventListener("click", () => {
      if (state.listening) { recognition.stop(); return; }
      recognition.lang = SPEECH[activeLang()] || "en-IN";
      try { recognition.start(); state.listening = true; mic.classList.add("live"); $("mic-status").textContent = "Listening…"; }
      catch (_) { /* already started */ }
    });
  }

  async function pollAlerts() {
    try {
      const data = await api("/api/overview");
      const phone = $("phone");
      const wanted = currentElder();
      const view = data.elders.find((e) => wanted && e.name === wanted.name);
      if (!view) return;
      const fresh = view.alerts.filter((a) => !state.seenAlerts.has(a.id)).reverse();
      for (const a of fresh) {
        state.seenAlerts.add(a.id);
        if (phone.querySelector(".empty")) clear(phone);
        phone.prepend(el("div", { class: "msg " + a.severity, text: a.severity.toUpperCase() + " · " + a.when + "\n" + a.detail }));
        if (!state.firstPoll) toast("Caregiver phone buzzed: " + a.severity, a.severity === "urgent" ? "error" : "");
      }
      if (!phone.children.length) phone.append(empty("No alerts yet."));
      state.firstPoll = false;
    } catch (_) { /* transient */ }
  }

  async function init() {
    try {
      const [cfg, overview] = await Promise.all([api("/api/config"), api("/api/overview")]);
      state.elders = overview.elders;
      const select = $("person");
      for (const e of state.elders) select.append(el("option", { value: e.name, text: e.name }));
      if (!state.elders.length) { toast("No elders yet. Run: carecircle seed-demo", "error"); }
      const badges = $("badges");
      badges.append(pill(cfg.demo ? "demo mode" : "live", cfg.demo ? "attention" : "ok"));
      if (cfg.llm) $("llm-wrap").classList.remove("hidden");
    } catch (err) { toast(err.message, "error"); }
    renderChips();
    $("phone").append(empty("No alerts yet."));
    $("lang").addEventListener("change", renderChips);
    $("person").addEventListener("change", () => { state.seenAlerts.clear(); state.firstPoll = true; clear($("phone")); renderChips(); pollAlerts(); });
    $("send").addEventListener("click", () => submit($("text").value));
    $("text").addEventListener("keydown", (e) => { if (e.key === "Enter") submit($("text").value); });
    $("clear").addEventListener("click", () => clear($("calls")));
    setupMic();
    pollAlerts();
    setInterval(pollAlerts, 3000);
  }
  init();
})();
