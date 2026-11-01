(function() {
  const card = document.getElementById("task-card");
  if (!card) return;
  const taskId = card.dataset.taskId;
  const initialStatus = card.dataset.status;
  const createdTime = new Date(card.dataset.createdAt).getTime();
  const startTime = card.dataset.startedAt || null;
  window._taskStartedAt = startTime;
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
  let currentStatus = initialStatus;
  const activityEl = document.getElementById("task-activity-section");
  const runningTasksListEl = document.getElementById("running-tasks-list");
  const queuePositionEl = document.getElementById("task-queue-position");

  function updateActivity(activity) {
    if (!activityEl) return;
    activityEl.hidden = ["completed", "failed", "rejected"].includes(currentStatus);
    if (activityEl.hidden) return;
    activity = activity || {};
    if (queuePositionEl) {
      if (activity.paused && currentStatus === "queued") {
        queuePositionEl.textContent = "Queue paused — the active task finishes, but waiting requests do not start.";
      } else if (activity.queue_position != null) {
        queuePositionEl.textContent = `Queue position: ${activity.queue_position} · ${activity.queued_ahead} queued requests ahead`;
      } else {
        queuePositionEl.textContent = currentStatus === "running" ? "This task is processing on the server." : "Waiting for the server worker to pick up this task";
      }
    }
    if (!runningTasksListEl) return;
    runningTasksListEl.replaceChildren();
    for (const task of activity.running_tasks || []) {
      const item = document.createElement("li");
      item.textContent = `Currently processing: ${task.company || "Request"} — ${task.role || task.kind || "Background task"} · ${task.stage || "Processing"}${task.model ? ` · ${task.model}` : ""} `;
      if (/^[a-f0-9]{32}$/.test(task.task_id || "")) {
        const link = document.createElement("a");
        link.href = cvAppUrl(`/tasks/${task.task_id}/view`);
        link.textContent = "View task";
        item.appendChild(link);
      }
      runningTasksListEl.appendChild(item);
    }
  }
  updateActivity(JSON.parse(card.dataset.taskActivity || "{}"));

  function updateTokens(usage) {
    if (!usage || !usage.calls) return;
    document.getElementById("token-usage").hidden = false;
    const pending = usage.active;
    document.getElementById("token-count").textContent = usage.completed_calls ? `${usage.total_tokens.toLocaleString()} reported tokens` : "Token statistics available when the model call completes";
    document.getElementById("token-speed").textContent = usage.tokens_per_second == null ? "" : `${usage.tokens_per_second.toFixed(1)} tokens/s (last completed call)`;
    document.getElementById("token-detail").textContent = usage.completed_calls ? `${usage.completed_calls}/${usage.calls} calls finished · input ${usage.input_tokens ?? "unavailable"} · output ${usage.output_tokens ?? "unavailable"}` : `Waiting for provider response · ${usage.model || "Model"}`;
    document.getElementById("token-note").textContent = pending ? "Actual usage updates when each call finishes. No live estimates." : usage.complete_usage ? "Actual usage reported by providers, including retries." : "Some calls have no reported usage; this is a partial total.";
  }
  updateTokens(JSON.parse(card.dataset.tokenUsage || "{}"));
  let timerInterval = null;
  let isDone = ["completed", "failed", "rejected"].includes(initialStatus);

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
      timerEl.textContent = currentStatus === "queued" ? `Waiting in queue: ${formatDuration(elapsedSec)}` : `Elapsed: ${formatDuration(elapsedSec)}`;
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
        headers: { "Accept": "application/json" }, redirect: "error"
      });
      if (res.ok) {
         const data = await res.json();
        currentStatus = data.status;
        updateActivity(data.activity);
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
          if (timerEl) timerEl.textContent = `Completed: ${finalDuration || "done"}`;
          const redirectUrl = (data.result && data.result.redirect_url) || "/";
          setTimeout(() => {
            window.location.href = cvAppUrl(redirectUrl);
          }, 800);
          return;
        }

        if (data.status === "failed" || data.status === "rejected") {
          const rejected = data.status === "rejected";
          isDone = true;
          clearInterval(timerInterval);
          if (livePulseEl) livePulseEl.style.display = "none";
          if (badgeIconEl) {
            badgeIconEl.classList.remove("pulse-indicator");
            badgeIconEl.textContent = rejected ? "—" : "⚠️";
          }
          if (statusTextEl) statusTextEl.textContent = rejected ? "Rejected — history kept" : "Generation failed";
          if (stageEl) stageEl.textContent = data.stage || "Execution failed";
          if (timerEl) {
            const execSec = data.execution_duration_seconds || 0;
            timerEl.textContent = `Execution time: ${formatDuration(execSec)}`;
          }
          if (footerNoteEl) {
            footerNoteEl.textContent = rejected ? "Rejected before execution. This entry remains in history until you delete it manually." : "Processing failed. Retry generation or edit the job.";
          }
          if (errorContainer && errorMessage) {
            errorMessage.textContent = rejected ? data.stage : data.error || "Generation failed.";
            document.getElementById("error-title").textContent = rejected ? "Task rejected:" : "Processing failed:";
            errorContainer.style.display = "block";
          }
          return;
        }
      } else if (res.status === 401 || res.status === 403) {
        isDone = true;
        clearInterval(timerInterval);
        if (footerNoteEl) footerNoteEl.textContent = "Sign in again to resume status updates. This does not stop server-side processing.";
        return;
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
