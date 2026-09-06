import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { MyQueues } from "./screens/MyQueues";

const accessToken = window.localStorage.getItem("access_token") ?? undefined;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MyQueues accessToken={accessToken} />
  </StrictMode>,
);
