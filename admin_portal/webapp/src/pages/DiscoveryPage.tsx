import Brand from "../components/Brand";
import { useEffect, useRef, useState } from "react";
import {
  DiscoveredDevice,
  DiscoveryScan,
  addDiscoveredDevice,
  cancelScan,
  dismissDevice,
  getScan,
  listScanDevices,
  startScan,
} from "../lib/api";

// Live scan progress arrives over /ws/discovery/{scan_id} (a dedicated
// channel per scan_id in ws_hub.py) — but the DB row is the source of
// truth (survives a page reload mid-scan), so both a WS listener and an
// initial fetch feed the same `scan` state.

type Method = "onvif" | "subnet";

function wsUrl(scanId: number): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/discovery/${scanId}`;
}

export default function DiscoveryPage() {
  const [method, setMethod] = useState<Method>("onvif");
  const [cidr, setCidr] = useState("192.168.1.0/24");
  const [force, setForce] = useState(false);
  const [scan, setScan] = useState<DiscoveryScan | null>(null);
  const [devices, setDevices] = useState<DiscoveredDevice[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [addingId, setAddingId] = useState<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  async function refreshDevices(scanId: number) {
    setDevices(await listScanDevices(scanId));
  }

  useEffect(() => {
    if (!scan || scan.status !== "running") return;
    const ws = new WebSocket(wsUrl(scan.id));
    wsRef.current = ws;
    ws.onmessage = async () => {
      // Payload just signals "something changed" — refetch the row and
      // device list rather than trying to keep two representations in sync.
      try {
        const fresh = await getScan(scan.id);
        setScan(fresh);
        await refreshDevices(scan.id);
      } catch {
        // scan/devices fetch races the unmount; ignore
      }
    };
    return () => ws.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scan?.id, scan?.status]);

  // Fallback poll in case a WS message is dropped or the connection never
  // opens (e.g. a proxy that doesn't forward the upgrade) — cheap insurance
  // at this scale (single scan, few-second cadence).
  useEffect(() => {
    if (!scan || scan.status !== "running") return;
    const interval = setInterval(async () => {
      try {
        const fresh = await getScan(scan.id);
        setScan(fresh);
        await refreshDevices(scan.id);
      } catch {
        // ignore transient errors during polling
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [scan?.id, scan?.status]);

  async function handleStart() {
    setError(null);
    try {
      const { scan_id } = await startScan({
        method,
        cidr: method === "subnet" ? cidr.trim() : undefined,
        force,
      });
      const fresh = await getScan(scan_id);
      setScan(fresh);
      setDevices([]);
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleCancel() {
    if (!scan) return;
    await cancelScan(scan.id);
  }

  async function handleDismiss(deviceId: number) {
    await dismissDevice(deviceId);
    if (scan) await refreshDevices(scan.id);
  }

  const visibleDevices = devices.filter((d) => !d.dismissed);

  return (
    <>
      <header className="topbar">
        <Brand />
        <a className="back" href="/cameras">← back to Cameras</a>
      </header>
      <main className="page">
        <h1>Camera Discovery</h1>
        <p className="muted">
          Finds cameras on the network instead of hand-typing IPs. <strong>ONVIF WS-Discovery</strong> is the
          primary method — it needs no credentials, but only sees cameras on the same L2 segment/VLAN as this
          server (multicast doesn't cross routers). If a camera doesn't show up there, use a{" "}
          <strong>subnet sweep</strong> with its CIDR instead. Nothing found here is added automatically — review
          each device and add it explicitly.
        </p>

        <div className="panel">
          <h2 style={{ marginTop: 0, fontSize: "1rem" }}>Start a scan</h2>
          <div className="row">
            <div>
              <label>Method</label>
              <select value={method} onChange={(e) => setMethod(e.target.value as Method)}>
                <option value="onvif">ONVIF WS-Discovery (multicast, no CIDR needed)</option>
                <option value="subnet">Subnet sweep (needs CIDR)</option>
              </select>
            </div>
            {method === "subnet" && (
              <div>
                <label>CIDR</label>
                <input type="text" value={cidr} onChange={(e) => setCidr(e.target.value)} placeholder="192.168.1.0/24" />
              </div>
            )}
            {method === "subnet" && (
              <div>
                <label style={{ marginTop: "0.7rem" }}>
                  <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} style={{ marginRight: "0.4rem" }} />
                  Force (allow &gt; 1024 hosts / larger than a /22)
                </label>
              </div>
            )}
            <div>
              <button className="btn btn-primary" onClick={handleStart} disabled={!!scan && scan.status === "running"}>
                {scan && scan.status === "running" ? "Scanning…" : "Start scan"}
              </button>
            </div>
          </div>
          {error && <p className="error-text">{error}</p>}
        </div>

        {scan && (
          <div className="panel">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <strong>Scan #{scan.id}</strong> · {scan.method}
                {scan.cidr ? ` (${scan.cidr})` : ""} ·{" "}
                <span
                  style={{
                    color:
                      scan.status === "error"
                        ? "var(--danger)"
                        : scan.status === "done"
                        ? "var(--ok)"
                        : "var(--ink-muted)",
                  }}
                >
                  {scan.status}
                </span>
                {scan.hosts_total != null && (
                  <span className="muted">
                    {" "}
                    — {scan.hosts_scanned}/{scan.hosts_total} hosts scanned
                  </span>
                )}
              </div>
              {scan.status === "running" && (
                <button className="btn btn-sm" onClick={handleCancel}>
                  Cancel
                </button>
              )}
            </div>
            {scan.error && <p className="error-text">{scan.error}</p>}
          </div>
        )}

        {scan && (
          <div className="panel">
            <h2 style={{ marginTop: 0, fontSize: "1rem" }}>
              Discovered devices {visibleDevices.length > 0 && `(${visibleDevices.length})`}
            </h2>
            {visibleDevices.length === 0 ? (
              <p className="muted" style={{ margin: 0 }}>
                {scan.status === "running" ? "Scanning…" : "No devices found yet."}
              </p>
            ) : (
              <table >
                <thead>
                  <tr>
                    <th>IP</th>
                    <th>MAC</th>
                    <th>Manufacturer / banner</th>
                    <th>Match</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {visibleDevices.map((d) => (
                    <DeviceRow
                      key={d.id}
                      device={d}
                      isAdding={addingId === d.id}
                      onStartAdd={() => setAddingId(d.id)}
                      onCancelAdd={() => setAddingId(null)}
                      onDismiss={() => handleDismiss(d.id)}
                      onAdded={async () => {
                        setAddingId(null);
                        if (scan) await refreshDevices(scan.id);
                      }}
                    />
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </main>
    </>
  );
}

function DeviceRow({
  device,
  isAdding,
  onStartAdd,
  onCancelAdd,
  onDismiss,
  onAdded,
}: {
  device: DiscoveredDevice;
  isAdding: boolean;
  onStartAdd: () => void;
  onCancelAdd: () => void;
  onDismiss: () => void;
  onAdded: () => void;
}) {
  const [cameraId, setCameraId] = useState("");
  const [name, setName] = useState("");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [rowError, setRowError] = useState<string | null>(null);

  const alreadyAdded = !!device.added_as_camera_id;

  async function handleAdd() {
    if (!cameraId.trim() || !name.trim() || !username.trim() || !password) {
      setRowError("Camera id, name, username, and password are all required.");
      return;
    }
    setSaving(true);
    setRowError(null);
    try {
      await addDiscoveredDevice(device.id, {
        camera_id: cameraId.trim(),
        name: name.trim(),
        username: username.trim(),
        password,
        manufacturer: device.guessed_manufacturer ?? undefined,
      });
      onAdded();
    } catch (e) {
      setRowError(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <tr>
        <td className="num">{device.ip}</td>
        <td className="num">{device.mac ?? "—"}</td>
        <td>{device.guessed_manufacturer ?? device.http_banner ?? "—"}</td>
        <td>
          {device.matched_camera_id ? (
            <span title={device.match_reason ?? undefined}>
              {device.matched_camera_id}
              {!!device.ip_changed && <span style={{ color: "var(--danger)", borderColor: "var(--danger)" }}> (IP changed)</span>}
            </span>
          ) : (
            <span className="muted">new</span>
          )}
        </td>
        <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
          {alreadyAdded ? (
            <span className="muted">added as {device.added_as_camera_id}</span>
          ) : isAdding ? (
            <button className="btn btn-sm" onClick={onCancelAdd}>
              Cancel
            </button>
          ) : (
            <>
              <button className="btn btn-sm" onClick={onStartAdd} style={{ marginRight: "0.3rem" }}>
                Add
              </button>
              <button className="btn btn-sm" style={{ color: "var(--danger)", borderColor: "var(--danger)" }} onClick={onDismiss}>
                Dismiss
              </button>
            </>
          )}
        </td>
      </tr>
      {isAdding && !alreadyAdded && (
        <tr>
          <td colSpan={5} style={{ paddingTop: "0.9rem", paddingBottom: "1.1rem" }}>
            <div className="row">
              <div>
                <label>Camera id</label>
                <input type="text" value={cameraId} onChange={(e) => setCameraId(e.target.value)} placeholder="loading_dock_cam" />
              </div>
              <div>
                <label>Display name</label>
                <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Loading Dock" />
              </div>
              <div>
                <label>Username</label>
                <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} />
              </div>
              <div>
                <label>Password</label>
                <input type="text" value={password} onChange={(e) => setPassword(e.target.value)} />
              </div>
              <div>
                <button className="btn btn-primary btn-sm" onClick={handleAdd} disabled={saving}>
                  {saving ? "Adding…" : "Save"}
                </button>
              </div>
            </div>
            {rowError && <p className="error-text">{rowError}</p>}
          </td>
        </tr>
      )}
    </>
  );
}
