import { useRef, MouseEvent } from "react";
import { ServicePoint } from "../lib/api";

// Click-to-place editor for service points (cashier / counter spots), drawn
// in the camera's own view. Coordinates are normalized against the
// element's rendered box, so they stay correct whatever size the video is
// displayed at and whatever the camera's resolution is.
//
// The circle is the catchment area — someone standing inside it counts as
// "being served at this point". It's a plain radius, not a polygon or a
// projected floor region, and the pipeline measures it exactly that way
// (see multi_camera_dashboard.py's service-point block), so what's drawn
// here is literally what's measured.

export default function ServicePointEditor({
  points,
  editing,
  selectedId,
  onPlace,
  onSelect,
  onMove,
}: {
  points: ServicePoint[];
  editing: boolean;
  selectedId: number | null;
  onPlace: (x: number, y: number) => void;
  onSelect: (id: number | null) => void;
  onMove: (id: number, x: number, y: number) => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef<number | null>(null);
  const movedRef = useRef(false);

  function toNormalized(e: { clientX: number; clientY: number }) {
    const rect = rootRef.current!.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)),
      y: Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height)),
    };
  }

  function handleClick(e: MouseEvent) {
    if (!editing) return;
    // A click that ends a drag would otherwise place a spurious second
    // point at the drop location.
    if (movedRef.current) {
      movedRef.current = false;
      return;
    }
    const { x, y } = toNormalized(e);
    onPlace(x, y);
  }

  function startDrag(e: MouseEvent, id: number) {
    if (!editing) return;
    e.stopPropagation();
    draggingRef.current = id;
    movedRef.current = false;
    onSelect(id);

    function onMouseMove(ev: globalThis.MouseEvent) {
      if (draggingRef.current === null) return;
      movedRef.current = true;
      const { x, y } = toNormalized(ev);
      onMove(draggingRef.current, x, y);
    }
    function onMouseUp() {
      draggingRef.current = null;
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    }
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  }

  return (
    <div
      ref={rootRef}
      onClick={handleClick}
      style={{
        position: "absolute",
        inset: 0,
        cursor: editing ? "crosshair" : "default",
        pointerEvents: editing ? "auto" : "none",
      }}
    >
      <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none"
           style={{ position: "absolute", inset: 0, overflow: "visible" }}>
        {points.map((p) => {
          const selected = p.id === selectedId;
          return (
            <g key={p.id}>
              {/* Catchment circle. viewBox is 0-100 in both axes with
                  preserveAspectRatio=none, so the radius is drawn against
                  width — matching how the pipeline measures it (normalized
                  x distance), rather than silently becoming an ellipse. */}
              <ellipse
                cx={p.x * 100}
                cy={p.y * 100}
                rx={p.radius * 100}
                ry={p.radius * 100}
                fill={selected ? "rgba(236,72,153,0.22)" : "rgba(236,72,153,0.12)"}
                stroke="rgb(236,72,153)"
                strokeWidth={selected ? 0.6 : 0.35}
                vectorEffect="non-scaling-stroke"
              />
            </g>
          );
        })}
      </svg>
      {points.map((p) => (
        <div
          key={p.id}
          onMouseDown={(e) => startDrag(e, p.id)}
          title={p.name}
          style={{
            position: "absolute",
            left: `${p.x * 100}%`,
            top: `${p.y * 100}%`,
            transform: "translate(-50%, -50%)",
            pointerEvents: editing ? "auto" : "none",
            cursor: editing ? "grab" : "default",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 2,
          }}
        >
          <div
            style={{
              width: 14,
              height: 14,
              borderRadius: "50%",
              background: "rgb(236,72,153)",
              border: "2px solid #fff",
              boxShadow: "0 1px 4px rgba(0,0,0,0.6)",
            }}
          />
          <span
            style={{
              fontSize: "0.7rem",
              fontWeight: 600,
              color: "#fff",
              textShadow: "0 1px 3px rgba(0,0,0,0.9)",
              whiteSpace: "nowrap",
            }}
          >
            {p.name}
          </span>
        </div>
      ))}
    </div>
  );
}
