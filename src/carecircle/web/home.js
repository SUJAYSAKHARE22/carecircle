(function () {
  "use strict";
  document.getElementById("endpoint").textContent = location.origin + "/mcp";
  const status = document.getElementById("status");
  CC.api("/api/config").then((cfg) => {
    const bits = ["v" + cfg.version, cfg.demo ? "demo mode" : "live mode", cfg.telegram ? "Telegram on" : "Telegram off (log only)", cfg.llm ? "LLM on" : "rule-based agent"];
    status.textContent = "Server ready \u2022 " + bits.join(" \u2022 ");
  }).catch((err) => { status.textContent = "Server not reachable: " + err.message; });
})();
