import { useEffect, useRef, useState } from "react";
import DetectionOverlay, { OverlayToggles } from "./DetectionOverlay";

type ConnState = "connecting" | "live" | "error";

// WebRTC connect lifecycle, reused by both the full CameraViewPage and grid
// tiles. Talks only to this backend (/api/streams/*) — the browser never
// sees an RTSP URL or credential; the backend proxies signaling to go2rtc,
// which is localhost-only (see restreamer.py).
export default function LiveVideo({
  cameraId,
  showControls = true,
  detectionToggles,
}: {
  cameraId: string;
  showControls?: boolean;
  /** Pass the current overlay toggle state to draw detection boxes; omit
   * (e.g. for small grid tiles) to skip the WebSocket + canvas entirely. */
  detectionToggles?: OverlayToggles;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const [state, setState] = useState<ConnState>("connecting");
  const [errorDetail, setErrorDetail] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState("connecting");
    setErrorDetail(null);

    async function connect() {
      const pc = new RTCPeerConnection();
      pcRef.current = pc;
      pc.addTransceiver("video", { direction: "recvonly" });
      pc.addTransceiver("audio", { direction: "recvonly" });

      pc.ontrack = (ev) => {
        if (videoRef.current && ev.streams[0]) {
          videoRef.current.srcObject = ev.streams[0];
        }
      };
      pc.onconnectionstatechange = () => {
        if (cancelled) return;
        if (pc.connectionState === "connected") setState("live");
        if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
          setState("error");
          setErrorDetail(`WebRTC connection ${pc.connectionState}`);
        }
      };

      try {
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        const resp = await fetch(`/api/streams/${encodeURIComponent(cameraId)}/webrtc-offer`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sdp: offer.sdp, type: "offer" }),
        });
        if (!resp.ok) {
          const text = await resp.text();
          let message = text || `HTTP ${resp.status}`;
          try {
            const parsed = JSON.parse(text);
            if (parsed?.detail) message = parsed.detail;
          } catch {
            // not JSON — use the raw text as-is
          }
          throw new Error(message);
        }
        const answer = await resp.json();
        if (cancelled) return;
        await pc.setRemoteDescription({ type: answer.type ?? "answer", sdp: answer.sdp });
      } catch (err) {
        if (!cancelled) {
          setState("error");
          setErrorDetail(String(err));
        }
      }
    }

    connect();
    return () => {
      cancelled = true;
      pcRef.current?.close();
      pcRef.current = null;
    };
  }, [cameraId]);

  async function handleSnapshot() {
    const resp = await fetch(`/api/streams/${encodeURIComponent(cameraId)}/snapshot`);
    if (!resp.ok) return;
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${cameraId}-${new Date().toISOString()}.jpg`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function handleFullscreen() {
    videoRef.current?.requestFullscreen();
  }

  return (
    <div style={{ position: "relative", width: "100%", height: "100%", background: "#000" }}>
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        style={{ width: "100%", height: "100%", objectFit: "contain", display: state === "live" ? "block" : "none" }}
      />
      {state === "live" && detectionToggles && (
        <DetectionOverlay cameraId={cameraId} videoRef={videoRef} toggles={detectionToggles} />
      )}
      {state !== "live" && (
        <div
          style={{
            position: "absolute", inset: 0, display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center", color: "#fff", gap: "0.5rem", padding: "1rem", textAlign: "center",
          }}
        >
          {state === "connecting" && <span className="muted">Connecting…</span>}
          {state === "error" && (
            <>
              <span style={{ color: "var(--danger)", fontWeight: 600 }}>Camera stream unavailable</span>
              <span className="muted" style={{ fontSize: "0.8rem", maxWidth: 360 }}>{errorDetail}</span>
            </>
          )}
        </div>
      )}
      {showControls && state === "live" && (
        <div style={{ position: "absolute", bottom: 8, right: 8, display: "flex", gap: "0.4rem" }}>
          <button className="btn btn-sm" onClick={handleSnapshot}>Snapshot</button>
          <button className="btn btn-sm" onClick={handleFullscreen}>Fullscreen</button>
        </div>
      )}
    </div>
  );
}
