// History presentation only: no generation, network calls or stored-record edits.
document.addEventListener("DOMContentLoaded", () => {
  const ids = ["search", "company", "role", "sort", "from", "until", "type", "files", "status", "match", "recommendation", "batch"];
  const controls = Object.fromEntries(ids.map(id => [id, document.getElementById(`history-${id}`)]));
  if (Object.values(controls).some(control => !control)) return;
  const items = [...document.querySelectorAll("[data-history-item]")];
  const lists = [...document.querySelectorAll("[data-history-list]")];
  const positions = new Map(items.map((item, index) => [item, index]));
  const count = document.getElementById("history-filter-count");
  const empty = document.getElementById("history-filter-empty");
  const error = document.getElementById("history-filter-error");
  const lower = value => value.trim().toLocaleLowerCase();
  const fileMatch = (item, value) => {
    const pdf = item.dataset.pdf === "1", docx = item.dataset.docx === "1";
    return value === "all" || (value === "any" && (pdf || docx))
      || (value === "both" && pdf && docx) || (value === "pdf" && pdf)
      || (value === "docx" && docx) || (value === "none" && !pdf && !docx);
  };
  function update() {
    const from = controls.from.value ? new Date(controls.from.value).getTime() : null;
    const until = controls.until.value ? new Date(controls.until.value).getTime() : null;
    const invalidRange = from !== null && until !== null && from > until;
    error.hidden = !invalidRange;
    controls.from.setAttribute("aria-invalid", String(invalidRange));
    controls.until.setAttribute("aria-invalid", String(invalidRange));
    let visible = 0;
    for (const item of items) {
      const data = item.dataset;
      const time = data.date ? Date.parse(data.date) : NaN;
      const batches = (data.batches || "").split(" ").filter(Boolean);
      const show = !invalidRange
        && lower(data.search || "").includes(lower(controls.search.value))
        && lower(data.company || "").includes(lower(controls.company.value))
        && lower(data.role || "").includes(lower(controls.role.value))
        && (controls.type.value === "all" || data.entryType === controls.type.value)
        && (controls.match.value === "all" || data.match === controls.match.value)
        && (controls.status.value === "all" || data.status === controls.status.value)
        && (controls.recommendation.value === "all" || data.recommendation === controls.recommendation.value)
        && (controls.batch.value === "all" || (controls.batch.value === "individual" ? batches.length === 0 : batches.includes(controls.batch.value)))
        && fileMatch(item, controls.files.value)
        && (from === null || (Number.isFinite(time) && time >= from))
        && (until === null || (Number.isFinite(time) && time <= until));
      item.hidden = !show;
      if (show) visible++;
    }
    const [field, direction] = controls.sort.value.split("_");
    const factor = direction === "asc" ? 1 : -1;
    for (const list of lists) {
      const rows = [...list.querySelectorAll("[data-history-item]")];
      rows.sort((left, right) => {
        let comparison = 0;
        if (field === "date") {
          const a = Date.parse(left.dataset.date), b = Date.parse(right.dataset.date);
          // Unknown legacy times stay last, regardless of direction.
          if (!Number.isFinite(a) || !Number.isFinite(b)) {
            if (Number.isFinite(a)) return -1;
            if (Number.isFinite(b)) return 1;
          } else comparison = a - b;
        } else {
          comparison = (left.dataset[field] || "").localeCompare(right.dataset[field] || "", undefined, {numeric: true, sensitivity: "base"});
        }
        return factor * comparison || positions.get(left) - positions.get(right);
      });
      for (const row of rows) list.appendChild(row);
    }
    count.textContent = `Showing ${visible} of ${items.length} entries`;
    empty.hidden = visible !== 0;
  }
  for (const control of Object.values(controls)) {
    control.addEventListener("input", update);
    control.addEventListener("change", update);
  }
  document.getElementById("history-reset").addEventListener("click", () => {
    for (const id of ["search", "company", "role", "from", "until"]) controls[id].value = "";
    for (const id of ["type", "files", "status", "match", "recommendation", "batch"]) controls[id].value = "all";
    controls.sort.value = "date_desc";
    update();
  });
  document.getElementById("history-downloadable").addEventListener("click", () => {
    controls.type.value = "generated";
    controls.files.value = "any";
    update();
  });
  update();
});
