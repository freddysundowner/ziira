import "./index.css";
import "@/sdk/i18n";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/shell/App";
import { registerServiceWorker } from "@/shell/registerServiceWorker";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

registerServiceWorker();
