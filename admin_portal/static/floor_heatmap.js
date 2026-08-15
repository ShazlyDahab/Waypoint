// Click-to-draw business-area zones directly on the floor plan, rendered as
// a heatmap of real activity (avg people in queue, from metrics_store).
// FH_CONFIG is set by an inline <script> before this file loads:
// { floorUrl, cameras: [{id,name}], initialZones: [{camera_id,name,polygon,avg_count,heat_bucket}] }
(function () {
  const cfg = window.FH_CONFIG;
  const canvas = document.getElementById("floor-canvas");
  const ctx = canvas.getContext("2d");
  const status = document.getElementById("fh-status");
  const saveMsg = document.getElementById("fh-save-msg");
  const cameraSelect = document.getElementById("fh-camera-select");
  const nameInput = document.getElementById("fh-zone-name");

  let floorImg = null;
  let zones = cfg.initialZones.map((z) => ({ ...z, polygon: z.polygon.slice() }));
  let pending = [];

  function heatColor(bucket) {
    return getComputedStyle(document.documentElement).getPropertyValue(`--heat-${bucket}`).trim() || "#888";
  }

  function toCanvasCoords(evt) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return [
      Math.round((evt.clientX - rect.left) * scaleX),
      Math.round((evt.clientY - rect.top) * scaleY),
    ];
  }

  function redraw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (floorImg) ctx.drawImage(floorImg, 0, 0);

    zones.forEach((z) => {
      const pts = z.polygon;
      if (pts.length < 3) return;
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      ctx.closePath();
      ctx.fillStyle = heatColor(z.heat_bucket || 0);
      ctx.globalAlpha = 0.75;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.strokeStyle = "rgba(0,0,0,0.35)";
      ctx.lineWidth = 1.5;
      ctx.stroke();
      const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
      const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
      ctx.fillStyle = "#111";
      ctx.font = "bold 13px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(z.name, cx, cy - 6);
      ctx.font = "11px sans-serif";
      ctx.fillText(z.avg_count !== undefined ? `avg ${z.avg_count}` : "no data yet", cx, cy + 10);
      ctx.textAlign = "left";
    });

    if (pending.length > 0) {
      ctx.beginPath();
      ctx.moveTo(pending[0][0], pending[0][1]);
      for (let i = 1; i < pending.length; i++) ctx.lineTo(pending[i][0], pending[i][1]);
      ctx.strokeStyle = "#1baf7a";
      ctx.lineWidth = 2;
      ctx.stroke();
      pending.forEach(([x, y]) => {
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fillStyle = "#1baf7a";
        ctx.fill();
      });
    }

    renderList();
  }

  function renderList() {
    const list = document.getElementById("fh-zone-list");
    list.innerHTML = "";
    zones.forEach((z, i) => {
      const li = document.createElement("li");
      li.textContent = `${z.camera_id} / ${z.name} — avg ${z.avg_count !== undefined ? z.avg_count : "n/a"} `;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-sm btn-danger";
      btn.textContent = "Remove";
      btn.addEventListener("click", () => { zones.splice(i, 1); redraw(); });
      li.appendChild(btn);
      list.appendChild(li);
    });
  }

  canvas.addEventListener("click", (evt) => {
    const [x, y] = toCanvasCoords(evt);
    pending.push([x, y]);
    redraw();
    status.textContent = `${pending.length} point(s) — click "Finish zone" once you've traced the area.`;
  });

  document.getElementById("fh-undo-point").addEventListener("click", () => {
    pending.pop();
    redraw();
  });

  document.getElementById("fh-finish-zone").addEventListener("click", () => {
    const camId = cameraSelect.value;
    const name = nameInput.value.trim();
    if (!camId) { status.textContent = "Pick which camera covers this area first."; return; }
    if (!name) { status.textContent = "Give this business area a name first."; return; }
    if (pending.length < 3) { status.textContent = "Need at least 3 points."; return; }
    zones.push({ camera_id: camId, name, polygon: pending.slice(), heat_bucket: 0 });
    pending = [];
    nameInput.value = "";
    status.textContent = "Zone added — click Save to persist it.";
    redraw();
  });

  document.getElementById("fh-save").addEventListener("click", async () => {
    const resp = await fetch("/floor-heatmap/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ zones: zones.map((z) => ({ camera_id: z.camera_id, name: z.name, polygon: z.polygon })) }),
    });
    if (resp.ok) {
      saveMsg.textContent = "Saved. Reload to see updated heat once new data comes in.";
      saveMsg.className = "flash flash-ok";
    } else {
      saveMsg.textContent = "Save failed: " + (await resp.text());
      saveMsg.className = "flash flash-error";
    }
  });

  const img = new Image();
  img.onload = () => {
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    floorImg = img;
    redraw();
  };
  img.onerror = () => { status.textContent = "Could not load the floor plan image."; };
  img.src = cfg.floorUrl;

  status.textContent = "Click points on the floor plan to trace a business area, then Finish zone.";
})();
