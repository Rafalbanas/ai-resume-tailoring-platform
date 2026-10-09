document.addEventListener("DOMContentLoaded", () => {
  const photoInput = document.getElementById("profile-photo-input");
  const photoPreview = document.getElementById("photo-preview");
  const cropX = document.getElementById("crop-x");
  const cropY = document.getElementById("crop-y");
  if (photoInput && photoPreview) {
    const updatePosition = () => {
      const image = photoPreview.querySelector("img");
      if (image) image.style.objectPosition = `${cropX.value}% ${cropY.value}%`;
    };
    photoInput.addEventListener("change", () => {
      const file = photoInput.files[0];
      if (!file) return;
      photoPreview.innerHTML = "";
      const image = document.createElement("img");
      image.alt = "Crop preview";
      image.src = URL.createObjectURL(file);
      image.onload = () => URL.revokeObjectURL(image.src);
      photoPreview.appendChild(image);
      updatePosition();
    });
    cropX.addEventListener("input", updatePosition);
    cropY.addEventListener("input", updatePosition);
  }

  const quickAvatar = document.getElementById("quick-photo-avatar");
  const quickDialog = document.getElementById("quick-photo-dialog");
  if (quickAvatar && quickDialog) {
    const quickFile = document.getElementById("quick-photo-file");
    const chooseButton = document.getElementById("quick-photo-choose");
    const useButton = document.getElementById("quick-photo-use");
    const hideButton = document.getElementById("quick-photo-hide");
    const removeButton = document.getElementById("quick-photo-remove");
    const quickStatus = document.getElementById("quick-photo-status");
    const slug = quickDialog.dataset.slug;
    const csrf = quickDialog.dataset.csrf;

    const setPhotoStatus = (message, isError = false) => {
      quickStatus.textContent = message;
      quickStatus.classList.toggle("error", isError);
    };
    const request = async (path, options = {}) => {
      setPhotoStatus("Saving…");
      try {
        const response = await fetch(`/preview/${encodeURIComponent(slug)}/photo${path}`, {
          method: "POST",
          credentials: "same-origin",
          headers: {"X-CSRF-Token": csrf, ...(options.headers || {})},
          body: options.body,
        });
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || "Could not update the profile photo.");
        window.location.reload();
      } catch (error) {
        setPhotoStatus(error.message || "Could not update the profile photo.", true);
      }
    };
    const upload = (file) => {
      if (!file || !file.type.startsWith("image/")) return;
      const data = new FormData();
      data.append("photo", file, file.name || `clipboard.${file.type.split("/")[1] || "png"}`);
      request("", {body: data});
    };

    quickAvatar.addEventListener("click", () => {
      setPhotoStatus("");
      if (quickAvatar.dataset.photoAvailable === "true") quickDialog.showModal();
      else quickFile.click();
    });
    chooseButton.addEventListener("click", () => quickFile.click());
    quickFile.addEventListener("change", () => upload(quickFile.files[0]));
    quickDialog.addEventListener("paste", (event) => {
      const imageItem = Array.from(event.clipboardData?.items || []).find(
        (item) => item.kind === "file" && item.type.startsWith("image/"),
      );
      if (!imageItem) return;
      event.preventDefault();
      upload(imageItem.getAsFile());
    });
    if (useButton) useButton.addEventListener("click", () => request("/use"));
    if (hideButton) hideButton.addEventListener("click", () => request("/hide"));
    if (removeButton) {
      removeButton.addEventListener("click", () => {
        if (window.confirm("Remove the saved profile photo?")) request("/remove");
      });
    }
  }

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
