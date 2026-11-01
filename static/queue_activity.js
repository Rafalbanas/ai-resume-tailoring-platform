(function() {
  const counter = document.getElementById("global-queue-count");
  if (!counter) return;
  let previous = null;
  async function refresh() {
    let active = false;
    try {
      if (!document.hidden) {
        const panel = document.getElementById("live-queue-panel");
        const response = await fetch(cvAppUrl(`/queue/status${panel ? "?panel=1" : ""}`), {
          headers: {Accept: "application/json"}, cache: "no-store", redirect: "error"
        });
        if (response.status === 401 || response.status === 403 || response.redirected) return;
        if (response.ok) {
          const data = await response.json();
          const activity = data.activity || {};
          const count = (activity.running_tasks || []).length + (activity.queued_tasks || []).length;
          active = count > 0;
          counter.textContent = String(count);
          document.getElementById("global-queue-paused").textContent = activity.paused ? " · paused" : "";
          // HTML is a server-rendered, autoescaped application partial, never
          // model output. Do not replace controls while the user focuses them.
          const snapshot = JSON.stringify(activity);
          if (panel && data.panel_html && snapshot !== previous && !panel.contains(document.activeElement)) {
            const parsed = new DOMParser().parseFromString(data.panel_html, "text/html");
            const updated = parsed.getElementById("live-queue-panel");
            if (updated) {
              panel.replaceWith(document.importNode(updated, true));
              previous = snapshot;
            }
          }
        }
      }
    } catch (_) {
      // Keep the last known state; a temporary connection failure is not proof
      // that the worker failed or a reason to resubmit any generation.
    }
    window.setTimeout(refresh, active ? 2500 : 7500);
  }
  refresh();
})();
