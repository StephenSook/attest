import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import App from "./App";
import { lazy, Suspense } from "react";
import Landing from "./experience/Landing";

const RunsPage = lazy(() => import("./pages/RunsPage"));
const RunDetailPage = lazy(() => import("./pages/RunDetailPage"));
const CalibrationPage = lazy(() => import("./pages/CalibrationPage"));
const NewRunPage = lazy(() => import("./pages/NewRunPage"));
const PromptPage = lazy(() => import("./pages/PromptPage"));
const CertificatePage = lazy(() => import("./pages/CertificatePage"));
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Suspense
        fallback={<p className="p-8 font-evidence text-sm text-ink-faint">Loading...</p>}
      >
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/prompt" element={<PromptPage />} />
        <Route element={<App />}>
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/new" element={<NewRunPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/runs/:runId/certificate" element={<CertificatePage />} />
          <Route path="/calibration" element={<CalibrationPage />} />
        </Route>
      </Routes>
      </Suspense>
    </BrowserRouter>
  </StrictMode>,
);
