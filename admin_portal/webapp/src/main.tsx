import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import CamerasPage from "./pages/CamerasPage";
import CameraViewPage from "./pages/CameraViewPage";
import GridPage from "./pages/GridPage";
import DiscoveryPage from "./pages/DiscoveryPage";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {/* basename matches vite.config.ts's `base` — keeps every route under /app,
        consistent between `npm run dev` and the built app FastAPI serves. */}
    <BrowserRouter basename="/app">
      <Routes>
        <Route path="/" element={<Navigate to="/cameras" replace />} />
        <Route path="/cameras" element={<CamerasPage />} />
        <Route path="/cameras/:cameraId/view" element={<CameraViewPage />} />
        <Route path="/grid" element={<GridPage />} />
        <Route path="/discovery" element={<DiscoveryPage />} />
        <Route path="*" element={<Navigate to="/cameras" replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
