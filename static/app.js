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

  let toastTimer = null;
  const showToast = (message, kind = "info", duration = 6000) => {
    const toast = document.getElementById("quick-photo-toast");
    if (!toast) return;
    toast.textContent = message;
    toast.className = `quick-photo-toast ${kind}`;
    toast.hidden = false;
    if (toastTimer) clearTimeout(toastTimer);
    if (duration > 0) {
      toastTimer = setTimeout(() => { toast.hidden = true; }, duration);
    }
  };

  const quickAvatar = document.getElementById("quick-photo-avatar");
  const quickDialog = document.getElementById("quick-photo-dialog");
  const cropDialog = document.getElementById("quick-photo-crop-dialog");
  if (quickAvatar && (quickDialog || cropDialog)) {
    const quickFile = document.getElementById("quick-photo-file");
    const photoOptionsBtn = document.getElementById("preview-photo-options-btn");
    const adjustBtn = document.getElementById("quick-photo-adjust");
    const useButton = document.getElementById("quick-photo-use");
    const hideButton = document.getElementById("quick-photo-hide");
    const removeButton = document.getElementById("quick-photo-remove");
    const quickStatus = document.getElementById("quick-photo-status");
    const cropViewport = document.getElementById("crop-viewport");
    const cropImage = document.getElementById("crop-image");
    const cropZoomSlider = document.getElementById("crop-zoom-slider");
    const cropSaveBtn = document.getElementById("crop-save-btn");
    const cropCancelBtn = document.getElementById("crop-cancel-btn");
    const cropStatus = document.getElementById("crop-photo-status");
    const slug = (quickDialog || cropDialog).dataset.slug;
    const csrf = (quickDialog || cropDialog).dataset.csrf;

    const V = 240;
    let currentCropFile = null;
    let panX = 0;
    let panY = 0;
    let zoom = 1.0;
    let isDragging = false;
    let startX = 0;
    let startY = 0;
    let initialPanX = 0;
    let initialPanY = 0;

    const request = async (path, options = {}) => {
      showToast("Saving…", "info", 0);
      try {
        const response = await fetch(cvAppUrl(`/preview/${encodeURIComponent(slug)}/photo${path}`), {
          method: "POST",
          credentials: "same-origin",
          headers: {"X-CSRF-Token": csrf, ...(options.headers || {})},
          body: options.body,
        });
        let result = {};
        try {
          result = await response.json();
        } catch (_) {}
        if (!response.ok || result.ok === false) {
          const err = result.error || response.statusText || "Could not update the profile photo.";
          showToast(`Upload failed (HTTP ${response.status}): ${err}`, "error", 8000);
          if (quickStatus) {
            quickStatus.textContent = `HTTP ${response.status}: ${err}`;
            quickStatus.classList.add("error");
          }
          return false;
        }
        showToast("Photo updated! Refreshing preview…", "success", 2000);
        setTimeout(() => {
          window.location.href = window.location.pathname + "?v=" + Date.now();
        }, 350);
        return true;
      } catch (error) {
        showToast(`Network error: ${error.message || "Request failed"}`, "error", 8000);
        if (quickStatus) {
          quickStatus.textContent = error.message || "Network error";
          quickStatus.classList.add("error");
        }
        return false;
      }
    };

    const uploadFileDirect = (file, cropX = 50, cropY = 50, cropZoom = 1.0) => {
      if (!file) return;
      const name = file.name || "";
      const isKnownExt = /\.(jpe?g|png|webp|heic|heif|tiff?)$/i.test(name);
      const isImageMime = file.type && file.type.startsWith("image/");
      if (!isImageMime && !isKnownExt && file.type) {
        showToast("Please select a supported image file (JPEG, PNG, WEBP, or HEIC).", "error", 6000);
        return;
      }
      const data = new FormData();
      data.append("photo", file, name || `upload_${Date.now()}.${(file.type && file.type.split("/")[1]) || "jpg"}`);
      data.append("crop_x", cropX);
      data.append("crop_y", cropY);
      data.append("crop_zoom", cropZoom);
      request("", {body: data});
    };

    const updateCropTransform = () => {
      if (!cropImage) return;
      const scale = (cropImage._baseScale || 1) * zoom;
      const dispW = (cropImage._natW || V) * scale;
      const dispH = (cropImage._natH || V) * scale;
      const minPanX = V - dispW;
      const maxPanX = 0;
      const minPanY = V - dispH;
      const maxPanY = 0;
      panX = Math.min(maxPanX, Math.max(minPanX, panX));
      panY = Math.min(maxPanY, Math.max(minPanY, panY));

      cropImage.style.width = `${dispW}px`;
      cropImage.style.height = `${dispH}px`;
      cropImage.style.transform = `translate(${panX}px, ${panY}px)`;
    };

    const openCropModal = (sourceUrl, file = null) => {
      currentCropFile = file;
      zoom = 1.0;
      if (cropZoomSlider) cropZoomSlider.value = "1";
      if (cropStatus) cropStatus.textContent = "";
      if (quickDialog && quickDialog.open) quickDialog.close();
      if (cropImage) {
        cropImage.onload = () => {
          const natW = cropImage.naturalWidth || 600;
          const natH = cropImage.naturalHeight || 600;
          const baseScale = Math.max(V / natW, V / natH);
          cropImage._baseScale = baseScale;
          cropImage._natW = natW;
          cropImage._natH = natH;
          panX = (V - natW * baseScale) / 2;
          panY = (V - natH * baseScale) / 2;
          updateCropTransform();
        };
        cropImage.onerror = () => {
          // Fallback if browser cannot decode blob (e.g. HEIC on unsupported browser)
          if (file) uploadFileDirect(file);
        };
        cropImage.src = sourceUrl;
      }
      if (cropDialog) cropDialog.showModal();
    };

    if (cropZoomSlider) {
      cropZoomSlider.addEventListener("input", () => {
        const oldZoom = zoom;
        zoom = parseFloat(cropZoomSlider.value);
        const centerImgX = (V / 2 - panX) / oldZoom;
        const centerImgY = (V / 2 - panY) / oldZoom;
        panX = V / 2 - centerImgX * zoom;
        panY = V / 2 - centerImgY * zoom;
        updateCropTransform();
      });
    }

    if (cropViewport) {
      cropViewport.addEventListener("mousedown", (e) => {
        isDragging = true;
        startX = e.clientX;
        startY = e.clientY;
        initialPanX = panX;
        initialPanY = panY;
      });
      window.addEventListener("mousemove", (e) => {
        if (!isDragging) return;
        panX = initialPanX + (e.clientX - startX);
        panY = initialPanY + (e.clientY - startY);
        updateCropTransform();
      });
      window.addEventListener("mouseup", () => { isDragging = false; });

      cropViewport.addEventListener("touchstart", (e) => {
        if (e.touches.length === 1) {
          isDragging = true;
          startX = e.touches[0].clientX;
          startY = e.touches[0].clientY;
          initialPanX = panX;
          initialPanY = panY;
        }
      }, {passive: true});
      window.addEventListener("touchmove", (e) => {
        if (!isDragging || e.touches.length !== 1) return;
        panX = initialPanX + (e.touches[0].clientX - startX);
        panY = initialPanY + (e.touches[0].clientY - startY);
        updateCropTransform();
      }, {passive: true});
      window.addEventListener("touchend", () => { isDragging = false; });
    }

    if (cropSaveBtn) {
      cropSaveBtn.addEventListener("click", () => {
        cropSaveBtn.disabled = true;
        cropSaveBtn.textContent = "Saving…";
        const scale = (cropImage._baseScale || 1) * zoom;
        const natW = cropImage._natW || V;
        const natH = cropImage._natH || V;
        const sx = Math.max(0, -panX / scale);
        const sy = Math.max(0, -panY / scale);
        const sSide = Math.min(natW, natH, V / scale);

        const maxLeft = Math.max(1, natW - sSide);
        const maxTop = Math.max(1, natH - sSide);
        const cropX = Math.max(0, Math.min(100, (sx / maxLeft) * 100));
        const cropY = Math.max(0, Math.min(100, (sy / maxTop) * 100));
        const cropZoom = zoom;

        try {
          const canvas = document.createElement("canvas");
          canvas.width = 600;
          canvas.height = 600;
          const ctx = canvas.getContext("2d");
          ctx.drawImage(cropImage, sx, sy, sSide, sSide, 0, 0, 600, 600);
          canvas.toBlob((blob) => {
            if (cropDialog) cropDialog.close();
            cropSaveBtn.disabled = false;
            cropSaveBtn.textContent = "Save crop";
            if (blob) {
              uploadFileDirect(blob, cropX, cropY, cropZoom);
            } else if (currentCropFile) {
              uploadFileDirect(currentCropFile, cropX, cropY, cropZoom);
            }
          }, "image/jpeg", 0.94);
        } catch (_) {
          if (cropDialog) cropDialog.close();
          cropSaveBtn.disabled = false;
          cropSaveBtn.textContent = "Save crop";
          if (currentCropFile) {
            uploadFileDirect(currentCropFile, cropX, cropY, cropZoom);
          }
        }
      });
    }

    if (cropCancelBtn) {
      cropCancelBtn.addEventListener("click", () => {
        if (cropDialog) cropDialog.close();
      });
    }

    quickAvatar.addEventListener("click", () => {
      if (quickAvatar.dataset.photoAvailable === "true") {
        if (quickDialog) quickDialog.showModal();
      }
    });

    quickAvatar.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        if (quickAvatar.dataset.photoAvailable === "true") {
          if (quickDialog) quickDialog.showModal();
        } else if (quickFile) {
          quickFile.click();
        }
      }
    });

    if (photoOptionsBtn) {
      photoOptionsBtn.addEventListener("click", () => {
        if (quickAvatar.dataset.photoAvailable === "true") {
          if (quickDialog) quickDialog.showModal();
        } else if (quickFile) {
          quickFile.click();
        }
      });
    }

    if (adjustBtn) {
      adjustBtn.addEventListener("click", () => {
        openCropModal(cvAppUrl(`/profile/photo/content?v=${Date.now()}`));
      });
    }

    if (quickFile) {
      quickFile.addEventListener("change", () => {
        const file = quickFile.files && quickFile.files[0];
        if (!file) return;
        try {
          const objectUrl = URL.createObjectURL(file);
          openCropModal(objectUrl, file);
        } catch (_) {
          uploadFileDirect(file);
        }
      });
    }

    const onDragOver = (e) => {
      e.preventDefault();
      e.stopPropagation();
      quickAvatar.classList.add("dragover");
    };
    const onDragLeave = (e) => {
      e.preventDefault();
      e.stopPropagation();
      quickAvatar.classList.remove("dragover");
    };
    const onDrop = (e) => {
      e.preventDefault();
      e.stopPropagation();
      quickAvatar.classList.remove("dragover");
      const files = e.dataTransfer?.files;
      if (files && files.length > 0) {
        try {
          const objectUrl = URL.createObjectURL(files[0]);
          openCropModal(objectUrl, files[0]);
        } catch (_) {
          uploadFileDirect(files[0]);
        }
      }
    };
    quickAvatar.addEventListener("dragenter", onDragOver);
    quickAvatar.addEventListener("dragover", onDragOver);
    quickAvatar.addEventListener("dragleave", onDragLeave);
    quickAvatar.addEventListener("drop", onDrop);

    document.addEventListener("paste", (event) => {
      const tag = event.target?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea") return;
      const items = Array.from(event.clipboardData?.items || []);
      const fileItem = items.find(
        (item) => item.kind === "file" && (item.type.startsWith("image/") || !item.type),
      );
      if (fileItem) {
        const file = fileItem.getAsFile();
        if (file) {
          event.preventDefault();
          try {
            const objectUrl = URL.createObjectURL(file);
            openCropModal(objectUrl, file);
          } catch (_) {
            uploadFileDirect(file);
          }
          return;
        }
      }
      const files = event.clipboardData?.files;
      if (files && files.length > 0) {
        const file = files[0];
        if (file.type.startsWith("image/") || /\.(jpe?g|png|webp|heic|heif|tiff?)$/i.test(file.name)) {
          event.preventDefault();
          try {
            const objectUrl = URL.createObjectURL(file);
            openCropModal(objectUrl, file);
          } catch (_) {
            uploadFileDirect(file);
          }
        }
      }
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
    const beforeFetch = [companyInput.value, roleInput.value, descriptionInput.value];
    fetching = true;
    fetchButton.disabled = true;
    fetchButton.textContent = "Fetching…";
    setStatus("Fetching the job offer…");
    try {
      const csrfToken = form.querySelector('[name="csrf_token"]').value;
      const response = await fetch(cvAppUrl("/api/extract-job-url"), {
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
      if ([companyInput.value, roleInput.value, descriptionInput.value].some((value, index) => value !== beforeFetch[index])) {
        setStatus("You edited the offer while fetching. Your changes were kept; fetch again to replace them.", "error");
        return false;
      }
      companyInput.value = result.company || "";
      roleInput.value = result.role || "";
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
    event.preventDefault();
    submitLabel.textContent = "Uruchamianie zadania…";
    submitButton.disabled = true;
    try {
      const formData = new FormData(form);
      const res = await fetch(cvAppUrl("/analyze"), {
        method: "POST",
        headers: { "Accept": "application/json" },
        body: formData,
      });
      if (res.status === 202) {
        const data = await res.json();
        window.location.href = cvAppUrl(data.view_url || `/tasks/${data.task_id}/view`);
        return;
      }
      const html = await res.text();
      document.open();
      document.write(html);
      document.close();
    } catch (err) {
      form.submit();
    }
  });

  const compareForm = document.getElementById("compare-form");
  if (compareForm) {
    compareForm.addEventListener("submit", async (event) => {
      const companyVal = compareForm.querySelector('[name="company"]')?.value.trim();
      const roleVal = compareForm.querySelector('[name="role"]')?.value.trim();
      const descVal = compareForm.querySelector('[name="job_description"]')?.value.trim();
      if (!companyVal || !roleVal || (descVal && descVal.length < 30)) {
        return; // Let standard HTML5 validation handle empty fields
      }
      event.preventDefault();
      const compBtn = compareForm.querySelector('button[type="submit"]');
      if (compBtn) {
        compBtn.disabled = true;
        compBtn.textContent = "Starting comparison…";
      }
      try {
        const formData = new FormData(compareForm);
        const res = await fetch(cvAppUrl("/compare"), {
          method: "POST",
          headers: { "Accept": "application/json" },
          body: formData,
        });
        if (res.status === 202) {
          const data = await res.json();
          window.location.href = cvAppUrl(data.view_url || `/tasks/${data.task_id}/view`);
          return;
        }
        const html = await res.text();
        document.open();
        document.write(html);
        document.close();
      } catch (err) {
        compareForm.submit();
      }
    });
  }
});

const providerSelect = document.getElementById('llm_provider');
const providerOrder = document.getElementById('provider-order');
if (providerSelect && providerOrder) {
  const updateOrder = () => {
    const primary = providerSelect.value === 'gemini' ? 'Gemini' : 'Ollama';
    const secondary = primary === 'Gemini' ? 'Ollama' : 'Gemini';
    providerOrder.textContent = 'Order: ' + primary + (providerOrder.dataset.fallback === 'true' ? ' → ' + secondary : ' (fallback disabled)');
  };
  providerSelect.addEventListener('change', updateOrder);
  updateOrder();
}
window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
