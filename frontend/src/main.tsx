import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import App from "./App";
import Landing from "./experience/Landing";
import CertificatePage from "./pages/CertificatePage";
import NewRunPage from "./pages/NewRunPage";
import "./index.css";
import CalibrationPage from "./pages/CalibrationPage";
import PromptPage from "./pages/PromptPage";
import RunDetailPage from "./pages/RunDetailPage";
import RunsPage from "./pages/RunsPage";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
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
    </BrowserRouter>
  </StrictMode>,
);
