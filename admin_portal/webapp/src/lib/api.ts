// Thin fetch wrappers over the /api/* backend. No credential ever passes
// through here — the backend never returns one.

async function asJson<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const text = await resp.text().catch(() => resp.statusText);
    throw new Error(`${resp.status}: ${text}`);
  }
  return resp.json() as Promise<T>;
}

// ------------------------------------------------------------- cameras ----

export type ConnectionState = "online" | "offline" | "degraded" | "not_configured";

export interface Camera {
  id: string;
  name: string;
}

export async function listCameras(): Promise<Camera[]> {
  return asJson(await fetch("/api/cameras"));
}

export async function getCameraConnectionState(cameraId: string): Promise<ConnectionState> {
  const network = await asJson<{ connection_state: ConnectionState }>(
    await fetch(`/api/cameras/${cameraId}/network`)
  );
  return network.connection_state;
}

// ------------------------------------------------------------ credentials --

export interface Credential {
  id: number;
  label: string;
  username: string;
  updated_at: number;
}

export async function listCredentials(): Promise<Credential[]> {
  return asJson(await fetch("/api/cameras/credentials"));
}

export async function createCredential(body: {
  label: string;
  username: string;
  password: string;
}): Promise<Credential> {
  return asJson(
    await fetch("/api/cameras/credentials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

// -------------------------------------------------------------- analytics -

export interface CameraHeatmap {
  camera_id: string;
  days: number;
  grid: number;
  matrix: number[][];
  samples: number;
  peak: number;
}

export interface ServicePoint {
  id: number;
  camera_id: string;
  name: string;
  kind: string;
  x: number;
  y: number;
  radius: number;
}

export function referenceFrameUrl(cameraId: string): string {
  return `/api/analytics/cameras/${encodeURIComponent(cameraId)}/reference-frame`;
}

export async function getCameraHeatmap(cameraId: string, days: number): Promise<CameraHeatmap> {
  return asJson(
    await fetch(`/api/analytics/cameras/${encodeURIComponent(cameraId)}/heatmap?days=${days}`)
  );
}

export async function listServicePoints(cameraId: string): Promise<ServicePoint[]> {
  return asJson(await fetch(`/api/analytics/cameras/${encodeURIComponent(cameraId)}/service-points`));
}

export async function createServicePoint(
  cameraId: string,
  body: { name: string; kind?: string; x: number; y: number; radius?: number }
): Promise<ServicePoint> {
  return asJson(
    await fetch(`/api/analytics/cameras/${encodeURIComponent(cameraId)}/service-points`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function updateServicePoint(
  pointId: number,
  body: Partial<{ name: string; x: number; y: number; radius: number }>
): Promise<ServicePoint> {
  return asJson(
    await fetch(`/api/analytics/service-points/${pointId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function deleteServicePoint(pointId: number): Promise<void> {
  await asJson(await fetch(`/api/analytics/service-points/${pointId}`, { method: "DELETE" }));
}

// -------------------------------------------------------------- discovery --

export interface DiscoveryScan {
  id: number;
  method: "onvif" | "subnet";
  cidr: string | null;
  status: "running" | "done" | "cancelled" | "error";
  hosts_total: number | null;
  hosts_scanned: number;
  started_at: number;
  ended_at: number | null;
  error: string | null;
}

export interface DiscoveredDevice {
  id: number;
  scan_id: number;
  ip: string;
  mac: string | null;
  onvif_xaddr: string | null;
  probe_ports: string | null;
  http_banner: string | null;
  guessed_manufacturer: string | null;
  matched_camera_id: string | null;
  match_reason: string | null;
  ip_changed: number;
  dismissed: number;
  added_as_camera_id: string | null;
  created_at: number;
}

export async function startScan(body: {
  method: "onvif" | "subnet";
  cidr?: string;
  force?: boolean;
}): Promise<{ scan_id: number }> {
  return asJson(
    await fetch("/api/discovery/scans", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function getScan(scanId: number): Promise<DiscoveryScan> {
  return asJson(await fetch(`/api/discovery/scans/${scanId}`));
}

export async function listScanDevices(scanId: number): Promise<DiscoveredDevice[]> {
  return asJson(await fetch(`/api/discovery/scans/${scanId}/devices`));
}

export async function cancelScan(scanId: number): Promise<void> {
  await asJson(await fetch(`/api/discovery/scans/${scanId}/cancel`, { method: "POST" }));
}

export async function dismissDevice(deviceId: number): Promise<void> {
  await asJson(await fetch(`/api/discovery/devices/${deviceId}/dismiss`, { method: "POST" }));
}

export async function addDiscoveredDevice(
  deviceId: number,
  body: {
    camera_id: string;
    name: string;
    username: string;
    password: string;
    rtsp_port?: number;
    manufacturer?: string;
  }
): Promise<{ ok: true; camera_id: string }> {
  return asJson(
    await fetch(`/api/discovery/devices/${deviceId}/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}
