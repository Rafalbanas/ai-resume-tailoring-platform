(function() {
  const card = document.getElementById("task-card");
  if (!card) return;
  const taskId = card.dataset.taskId;
  const initialStatus = card.dataset.status;
  const createdTime = new Date(card.dataset.createdAt).getTime();
  const startTime = card.dataset.startedAt || null;
  const stageEl = document.getElementById("task-stage");
  const timerEl = document.getElementById("task-timer");
  const statusTextEl = document.getElementById("task-status-text");
  const errorContainer = document.getElementById("error-container");
  const errorMessage = document.getElementById("error-message");
  const livePulseEl = document.getElementById("task-live-pulse");
  const badgeIconEl = document.getElementById("task-badge-icon");
  const footerNoteEl = document.getElementById("task-footer-note");
  const retryForm = document.getElementById("retry-form");
  const retryBtn = document.getElementById("retry-btn");

  function updateTokens(usage) {
    if (!usage || !usage.calls) return;
    document.getElementById("token-usage").hidden = false;
    const pending = usage.active;
    document.getElementById("token-count").textContent = usage.completed_calls ? `${usage.total_tokens.toLocaleString()} reported tokens` : "Token statistics available when the model call completes";
    document.getElementById("token-speed").textContent = usage.tokens_per_second == null ? "" : `${usage.tokens_per_second.toFixed(1)} tokens/s (last completed call)`;
    document.getElementById("token-detail").textContent = usage.completed_calls ? `${usage.completed_calls}/${usage.calls} calls finished · input ${usage.input_tokens ?? "unavailable"} · output ${usage.output_tokens ?? "unavailable"}` : `${usage.model || "Model"} is generating…`;
    document.getElementById("token-note").textContent = pending ? "Actual usage updates when each call finishes. No live estimates." : usage.complete_usage ? "Actual usage reported by providers, including retries." : "Some calls have no reported usage; this is a partial total.";
  }
  updateTokens(JSON.parse(card.dataset.tokenUsage || "{}"));
  let timerInterval = null;
  let isDone = (initialStatus === "completed" || initialStatus === "failed");

  function formatDuration(sec) {
    const min = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return min > 0 ? `${min}m ${s}s` : `${s}s`;
  }

  function updateTimer(startedAt) {
    if (isDone) return;
    const start = startedAt ? new Date(startedAt).getTime() : createdTime;
    const now = Date.now();
    const elapsedSec = Math.max(0, Math.floor((now - start) / 1000));
    if (timerEl) {
      timerEl.textContent = `Elapsed: ${formatDuration(elapsedSec)}`;
    }
  }

  if (!isDone) {
    timerInterval = setInterval(() => updateTimer(window._taskStartedAt), 1000);
    updateTimer(startTime);
  }

  // Prevent duplicate submissions on retry button click
  if (retryForm && retryBtn) {
    retryForm.addEventListener("submit", function(e) {
      if (retryBtn.disabled) {
        e.preventDefault();
        return;
      }
      retryBtn.disabled = true;
      retryBtn.setAttribute("aria-busy", "true");
      retryBtn.textContent = "Starting retry...";
    });
  }

  async function pollStatus() {
    if (isDone) return;

    try {
      const res = await fetch(cvAppUrl(`/tasks/${taskId}`), {
        headers: { "Accept": "application/json" }
      });
      if (res.ok) {
        const data = await res.json();
        updateTokens(data.token_usage);
        if (data.started_at) {
          window._taskStartedAt = data.started_at;
        }

        if (stageEl && data.stage) {
          stageEl.textContent = data.stage;
        }

        if (data.status === "running") {
          if (statusTextEl) statusTextEl.textContent = "Processing";
          if (livePulseEl) livePulseEl.style.display = "inline-block";
        } else if (data.status === "queued") {
          if (statusTextEl) statusTextEl.textContent = "Queued";
        }

        if (data.status === "completed") {
          isDone = true;
          clearInterval(timerInterval);
          if (livePulseEl) livePulseEl.style.display = "none";
          if (badgeIconEl) {
            badgeIconEl.classList.remove("pulse-indicator");
            badgeIconEl.textContent = "✓";
          }
          if (statusTextEl) statusTextEl.textContent = "Completed!";
          if (stageEl) stageEl.textContent = "Opening results...";
          const finalDuration = data.execution_duration_seconds ? ` (${formatDuration(data.execution_duration_seconds)})` : "";
          if (timerEl) timerEl.textContent = `Completed w: ${finalDuration || "done"}`;
          const redirectUrl = (data.result && data.result.redirect_url) || "/";
          setTimeout(() => {
            window.location.href = cvAppUrl(redirectUrl);
          }, 800);
          return;
        }

        if (data.status === "failed") {
          isDone = true;
          clearInterval(timerInterval);
          if (livePulseEl) livePulseEl.style.display = "none";
          if (badgeIconEl) {
            badgeIconEl.classList.remove("pulse-indicator");
            badgeIconEl.textContent = "⚠️";
          }
          if (statusTextEl) statusTextEl.textContent = "Generation failed";
          if (stageEl) stageEl.textContent = data.stage || "Execution failed";
          if (timerEl) {
            const execSec = data.execution_duration_seconds || 0;
            timerEl.textContent = `Execution time: ${formatDuration(execSec)}`;
          }
          if (footerNoteEl) {
            footerNoteEl.textContent = "Processing failed. Retry generation or edit the job.";
          }
          if (errorContainer && errorMessage) {
            errorMessage.textContent = data.error || "Generation failed.";
            errorContainer.style.display = "block";
          }
          return;
        }
      } else if (res.status === 404) {
        isDone = true;
        clearInterval(timerInterval);
        if (errorMessage) errorMessage.textContent = "Task not found.";
        if (errorContainer) errorContainer.style.display = "block";
        return;
      }
    } catch (err) {
      console.warn("Poll attempt failed, will retry:", err);
    }

    if (!isDone) {
      setTimeout(pollStatus, 1000);
    }
  }

  // Start polling if not already completed/failed
  if (!isDone) {
    setTimeout(pollStatus, 1500);
  }
})();
