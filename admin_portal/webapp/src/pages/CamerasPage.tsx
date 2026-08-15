import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Camera, ConnectionState, listCameras, referenceFrameUrl } from "../lib/api";
import Brand from "../components/Brand";

// The Live Monitoring hub — what used to be the floor-plan page's job.
// Cameras are the organizing unit now: there is no store map, so a camera
// list with live status is the honest top level. Status arrives over the
// ONE shared /ws/status channel (not one socket per camera) — see
// admin_portal/ws_hub.py.

const STATE_LABEL: Record<ConnectionState, string> = {
  online: "Live",
  offline: "Offline",
  degraded: "Degraded",
  not_configured: "Not set up",
};

interface LiveStatus {
  connection_state: ConnectionState;
  person_count: number;
}

export default function CamerasPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [status, setStatus] = useState<Record<string, LiveStatus>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    listCameras()
      .then(setCameras)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${window.location.host}/ws/status`);
    wsRef.current = ws;
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type !== "status" || !msg.camera_id) return;
        setStatus((prev) => ({
          ...prev,
          [msg.camera_id]: {
            connection_state: msg.connection_state ?? "not_configured",
            person_count: msg.person_count ?? 0,
          },
        }));
      } catch {
        // a malformed status message shouldn't take the page down
      }
    };
    return () => ws.close();
  }, []);

  const anyLive = Object.values(status).some((s) => s.connection_state === "online");

  return (
    <>
      <header className="topbar">
        <Brand />
        <Link className="back" to="/grid" style={{ marginLeft: "auto" }}>Grid wall →</Link>
        <a className="back" href="/">← admin portal</a>
      </header>
      <main className="page">
        <h1>Live monitoring</h1>
        <p className="muted">
          Every camera in the system. Open one to watch it live, see where people stand most
          (heatmap), and place a cashier/service point on it. Live status comes from the detection
          pipeline — start it under <a href="/jobs">Jobs</a> if everything reads "Not set up".
          To add or remove cameras, go to <a href="/cameras">Cameras</a>.
        </p>

        {!anyLive && (
          <div className="panel">
            <strong>Nothing is reporting live right now.</strong>
            <p className="muted" style={{ margin: "0.4rem 0 0" }}>
              Heatmaps and service points still work from recorded history — only the live video and
              person boxes need the pipeline (and, for video, the go2rtc restreamer) running.
            </p>
          </div>
        )}

        {error && <p className="error-text">{error}</p>}
        {loading ? (
          <p className="muted">Loading…</p>
        ) : cameras.length === 0 ? (
          <div className="panel">
            <p className="muted" style={{ margin: 0 }}>
              No cameras yet — add them under <a href="/cameras">Cameras</a>, which can scan the
              network for you.
            </p>
          </div>
        ) : (
          <div className="camera-grid">
            {cameras.map((cam) => {
              const s = status[cam.id];
              const state: ConnectionState = s?.connection_state ?? "not_configured";
              return (
                <div key={cam.id} className="camera-plate">
                  <Link to={`/cameras/${encodeURIComponent(cam.id)}/view`} style={{ color: "inherit", textDecoration: "none" }}>
                    <div className="frame">
                      <img
                        src={referenceFrameUrl(cam.id)}
                        alt={cam.name || cam.id}
                        onError={(e) => {
                          // No calibration snapshot yet — leave the dark frame
                          // rather than showing a broken-image icon.
                          (e.currentTarget as HTMLImageElement).style.visibility = "hidden";
                        }}
                      />
                      <span className={`status status-${state}`}>{STATE_LABEL[state]}</span>
                      {state === "online" && (
                        <span className="count">
                          {s.person_count} {s.person_count === 1 ? "person" : "people"}
                        </span>
                      )}
                    </div>
                    <div className="meta">
                      <div className="name">{cam.name || cam.id}</div>
                      <div className="id">{cam.id}</div>
                    </div>
                  </Link>
                  <div className="actions">
                    <Link className="btn btn-sm" to={`/cameras/${encodeURIComponent(cam.id)}/view`}>
                      Open
                    </Link>
                    <Link className="btn btn-sm" to={`/cameras/${encodeURIComponent(cam.id)}/view?mode=heatmap`}>
                      Heatmap
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>
    </>
  );
}
