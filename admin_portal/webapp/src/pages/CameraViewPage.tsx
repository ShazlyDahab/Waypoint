import Brand from "../components/Brand";
import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, useSearchParams, Link } from "react-router-dom";
import LiveVideo from "../components/LiveVideo";
import HeatmapOverlay, { HeatmapLegend } from "../components/HeatmapOverlay";
import ServicePointEditor from "../components/ServicePointEditor";
import { loadToggles, saveToggles, OverlayToggles } from "../components/DetectionOverlay";
import {
  Camera, CameraHeatmap, ServicePoint,
  listCameras, getCameraHeatmap, referenceFrameUrl,
  listServicePoints, createServicePoint, updateServicePoint, deleteServicePoint,
} from "../lib/api";

const TOGGLE_LABELS: [keyof OverlayToggles, string][] = [
  ["boxes", "Boxes"], ["labels", "Labels"], ["confidence", "Confidence"],
  ["trackIds", "Visitor ID"], ["timeInStore", "Time in store"], ["trails", "Trails"],
];

const HEAT_RANGES = [
  { days: 1, label: "Today" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
];

type Mode = "live" | "heatmap";

// Deep-linkable camera view. ?mode=heatmap opens straight into the
// heatmap, so an Insights link or a bookmark can point at exactly the
// view someone means.
export default function CameraViewPage() {
  const { cameraId } = useParams<{ cameraId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const mode: Mode = searchParams.get("mode") === "heatmap" ? "heatmap" : "live";
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [toggles, setToggles] = useState<OverlayToggles>(loadToggles());
  const [heatDays, setHeatDays] = useState(7);
  const [heatmap, setHeatmap] = useState<CameraHeatmap | null>(null);
  const [heatError, setHeatError] = useState<string | null>(null);
  const [points, setPoints] = useState<ServicePoint[]>([]);
  const [editingPoints, setEditingPoints] = useState(false);
  const [selectedPoint, setSelectedPoint] = useState<number | null>(null);
  const [frameMissing, setFrameMissing] = useState(false);

  useEffect(() => {
    listCameras().then(setCameras).catch(() => {});
  }, []);

  useEffect(() => {
    if (!cameraId) return;
    listServicePoints(cameraId).then(setPoints).catch(() => {});
  }, [cameraId]);

  useEffect(() => {
    if (!cameraId || mode !== "heatmap") return;
    setHeatError(null);
    getCameraHeatmap(cameraId, heatDays)
      .then(setHeatmap)
      .catch((e) => setHeatError(String(e)));
  }, [cameraId, mode, heatDays]);

  function setMode(next: Mode) {
    const params = new URLSearchParams(searchParams);
    if (next === "heatmap") params.set("mode", "heatmap");
    else params.delete("mode");
    setSearchParams(params, { replace: true });
  }

  function updateToggle(key: keyof OverlayToggles) {
    setToggles((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      saveToggles(next);
      return next;
    });
  }

  const goToOffset = useCallback(
    (offset: number) => {
      if (cameras.length < 2 || !cameraId) return;
      const idx = cameras.findIndex((c) => c.id === cameraId);
      if (idx === -1) return;
      const next = cameras[(idx + offset + cameras.length) % cameras.length];
      navigate(`/cameras/${encodeURIComponent(next.id)}/view${mode === "heatmap" ? "?mode=heatmap" : ""}`);
    },
    [cameras, cameraId, navigate, mode]
  );

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (editingPoints) return; // don't hijack keys while placing points
      if (e.key === "Escape") navigate("/cameras");
      else if (e.key === "ArrowRight") goToOffset(1);
      else if (e.key === "ArrowLeft") goToOffset(-1);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [navigate, goToOffset, editingPoints]);

  async function handlePlace(x: number, y: number) {
    if (!cameraId) return;
    const name = prompt("Name this service point (e.g. Register 1, Returns Desk):");
    if (!name?.trim()) return;
    try {
      const created = await createServicePoint(cameraId, { name: name.trim(), x, y });
      setPoints((prev) => [...prev, created]);
      setSelectedPoint(created.id);
    } catch (e) {
      alert(`Could not save service point: ${e}`);
    }
  }

  async function handleMove(id: number, x: number, y: number) {
    setPoints((prev) => prev.map((p) => (p.id === id ? { ...p, x, y } : p)));
    try {
      await updateServicePoint(id, { x, y });
    } catch {
      // keep the optimistic position; a reload will resync from the server
    }
  }

  async function handleRadius(id: number, radius: number) {
    setPoints((prev) => prev.map((p) => (p.id === id ? { ...p, radius } : p)));
    try {
      await updateServicePoint(id, { radius });
    } catch {
      /* same as above */
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Remove this service point? Past measurements stay in Insights.")) return;
    await deleteServicePoint(id);
    setPoints((prev) => prev.filter((p) => p.id !== id));
    setSelectedPoint(null);
  }

  if (!cameraId) return null;
  const selected = points.find((p) => p.id === selectedPoint) ?? null;

  return (
    // Flex column rather than calc(100vh - Npx) anywhere: the header wraps
    // to two rows on a narrow window, and every hardcoded offset was wrong
    // the moment it did.
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <header className="canvas-bar">
        <Brand />
        <Link className="back" to="/cameras">← all cameras</Link>
        <span className="cam-id">{cameraId}</span>

        <div style={{ display: "flex", gap: "0.3rem", marginLeft: "1rem" }}>
          <button className={`btn btn-sm ${mode === "live" ? "btn-primary" : ""}`} onClick={() => setMode("live")}>
            Live
          </button>
          <button className={`btn btn-sm ${mode === "heatmap" ? "btn-primary" : ""}`} onClick={() => setMode("heatmap")}>
            Heatmap
          </button>
        </div>

        <div style={{ marginLeft: "auto", display: "flex", gap: "0.9rem", alignItems: "center" }}>
          {mode === "live" &&
            TOGGLE_LABELS.map(([key, label]) => (
              <label key={key} className="muted" style={{ fontSize: "0.78rem", display: "flex", alignItems: "center", gap: "0.25rem" }}>
                <input type="checkbox" checked={toggles[key]} onChange={() => updateToggle(key)} />
                {label}
              </label>
            ))}
          {mode === "heatmap" && (
            <div style={{ display: "flex", gap: "0.3rem" }}>
              {HEAT_RANGES.map((r) => (
                <button
                  key={r.days}
                  className={`btn btn-sm ${heatDays === r.days ? "btn-primary" : ""}`}
                  onClick={() => setHeatDays(r.days)}
                >
                  {r.label}
                </button>
              ))}
            </div>
          )}
          <button
            className={`btn btn-sm ${editingPoints ? "btn-primary" : ""}`}
            onClick={() => { setEditingPoints((v) => !v); setSelectedPoint(null); }}
          >
            {editingPoints ? "Done placing" : "Place service point"}
          </button>
        </div>
      </header>

      {editingPoints && (
        <div className="canvas-note">
          <p>
            Click where customers stand to be served: at the register, the counter, the returns desk.
            Drag a point to adjust it. The circle is the area that counts as "being served here"; time
            inside it becomes the service-time metrics on the Insights page.
          </p>
          {selected && (
            <div className="row" style={{ marginTop: "0.5rem", alignItems: "center" }}>
              <div>
                <label>Selected</label>
                <strong>{selected.name}</strong>
              </div>
              <div>
                <label>Catchment size</label>
                <input
                  type="range" min={0.03} max={0.4} step={0.01} value={selected.radius}
                  onChange={(e) => handleRadius(selected.id, Number(e.target.value))}
                />
              </div>
              <div>
                <button className="btn btn-sm" style={{ color: "var(--danger)" }} onClick={() => handleDelete(selected.id)}>
                  Remove
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="canvas" style={{ flex: 1, minHeight: 0 }}>
        {mode === "live" ? (
          <div style={{ position: "relative", width: "100%", height: "100%" }}>
            <LiveVideo cameraId={cameraId} detectionToggles={toggles} />
            <ServicePointEditor
              points={points} editing={editingPoints} selectedId={selectedPoint}
              onPlace={handlePlace} onSelect={setSelectedPoint} onMove={handleMove}
            />
          </div>
        ) : (
          <div style={{ position: "relative", width: "100%", height: "100%", display: "flex",
                        alignItems: "center", justifyContent: "center" }}>
            <div style={{ position: "relative", maxWidth: "100%", maxHeight: "100%" }}>
              {!frameMissing ? (
                <img
                  src={referenceFrameUrl(cameraId)}
                  alt={`${cameraId} reference view`}
                  onError={() => setFrameMissing(true)}
                  style={{
                    display: "block", maxWidth: "100%", maxHeight: "100%",
                    // Dimmed so the heat colours stay legible over a
                    // brightly-lit scene; the frame is context here, not
                    // the subject.
                    filter: "brightness(0.45) saturate(0.7)",
                  }}
                />
              ) : (
                <div className="canvas-note" style={{ maxWidth: 520, border: "1px solid var(--canvas-rule)" }}>
                  <strong>No reference image for this camera yet.</strong>
                  <p className="muted" style={{ margin: "0.4rem 0 0" }}>
                    The heatmap draws over a still frame from this camera, captured during calibration.
                    Run calibration for <code>{cameraId}</code> from{" "}
                    <a href={`/cameras/${encodeURIComponent(cameraId)}/zones`}>its areas page</a> to capture one.
                  </p>
                </div>
              )}
              {!frameMissing && <HeatmapOverlay heatmap={heatmap} />}
              {!frameMissing && (
                <ServicePointEditor
                  points={points} editing={editingPoints} selectedId={selectedPoint}
                  onPlace={handlePlace} onSelect={setSelectedPoint} onMove={handleMove}
                />
              )}
            </div>

            <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, display: "flex",
                          justifyContent: "space-between", alignItems: "center", gap: "1rem",
                          flexWrap: "wrap", padding: "0.6rem 2rem",
                          background: "oklch(0.16 0.008 70 / 0.88)" }}>
              <HeatmapLegend peak={heatmap?.peak ?? 0} />
              <span className="muted" style={{ fontSize: "0.75rem" }}>
                {heatError
                  ? heatError
                  : heatmap
                  ? heatmap.samples > 0
                    ? `${heatmap.samples.toLocaleString()} position sample(s) over ${heatDays} day(s)`
                    : `No positions recorded in the last ${heatDays} day(s) — the pipeline records one sample per person per second while it runs.`
                  : "Loading…"}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
