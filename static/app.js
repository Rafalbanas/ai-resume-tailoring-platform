document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("job-form");
  if (!form) return;

  const urlInput = document.getElementById("job-url");
  const companyInput = document.getElementById("company");
  const roleInput = document.getElementById("role");
  const descriptionInput = document.getElementById("job-description");
  const fetchButton = document.getElementById("fetch-job");
  const submitButton = document.getElementById("submit");
  const submitLabel = document.getElementById("submit-label");
  const status = document.getElementById("fetch-status");
  let fetching = false;

  function setStatus(message, kind = "") {
    status.textContent = message;
    status.className = `fetch-status ${kind}`.trim();
  }

  function fieldsAreComplete() {
    return companyInput.value.trim() && roleInput.value.trim() && descriptionInput.value.trim().length >= 30;
  }

  async function fetchJob() {
    const url = urlInput.value.trim();
    if (!url) {
      setStatus("Paste a job URL first.", "error");
      return false;
    }
    if (fetching) return false;
    fetching = true;
    fetchButton.disabled = true;
    fetchButton.textContent = "Fetching…";
    setStatus("Fetching the job offer…");
    try {
      const csrfToken = form.querySelector('[name="csrf_token"]').value;
      const response = await fetch("/api/extract-job-url", {
        method: "POST",
        credentials: "same-origin",
        headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken},
        body: JSON.stringify({url}),
      });
      if (!response.ok) throw new Error("request failed");
      const result = await response.json();
      if (result.extraction_method === "manual_required" || !result.job_description) {
        setStatus("Could not extract this job automatically. Paste the job description manually.", "error");
        return false;
      }
      companyInput.value = result.company || companyInput.value;
      roleInput.value = result.role || roleInput.value;
      descriptionInput.value = result.job_description;
      setStatus("Job details fetched. Review and edit them before analysis.", "success");
      return fieldsAreComplete();
    } catch (_) {
      setStatus("Could not extract this job automatically. Paste the job description manually.", "error");
      return false;
    } finally {
      fetching = false;
      fetchButton.disabled = false;
      fetchButton.textContent = "Fetch job";
    }
  }

  fetchButton.addEventListener("click", fetchJob);
  form.addEventListener("submit", async (event) => {
    if (!fieldsAreComplete() && urlInput.value.trim()) {
      event.preventDefault();
      const ready = await fetchJob();
      if (ready) form.requestSubmit();
      return;
    }
    if (!fieldsAreComplete()) {
      event.preventDefault();
      setStatus("Enter company, role, and at least 30 characters of the job description.", "error");
      return;
    }
    submitLabel.textContent = "Analyzing…";
    submitButton.disabled = true;
  });
});
