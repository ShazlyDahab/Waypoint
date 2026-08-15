import { useSearchParams, Link } from "react-router-dom";
import LiveVideo from "../components/LiveVideo";
import Brand from "../components/Brand";

// 2x2 / 3x3 camera wall — cameras selected on a floor plan (grid-select
// mode there) land here via ?cameras=id1,id2,id3. Deep-linkable like the
// single view.
export default function GridPage() {
  const [searchParams] = useSearchParams();
  const cameraIds = (searchParams.get("cameras") ?? "").split(",").filter(Boolean);
  const cols = cameraIds.length <= 4 ? 2 : 3;

  return (
    <>
      <header className="canvas-bar">
        <Brand />
        <Link className="back" to="/floor-plans">← all floor plans</Link>
        <span className="muted">{cameraIds.length} camera(s)</span>
      </header>
      {cameraIds.length === 0 ? (
        <main className="page">
          <p className="muted">No cameras selected. Go to a floor plan, turn on grid-select, and pick a few.</p>
        </main>
      ) : (
        <div className="grid-wall" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
          {cameraIds.map((id) => (
            <div key={id} className="grid-tile">
              <span className="tile-label">{id}</span>
              <LiveVideo cameraId={id} />
            </div>
          ))}
        </div>
      )}
    </>
  );
}
