import React from "react";
import ReactDOM from "react-dom/client";
import { createHashRouter, RouterProvider } from "react-router-dom";
import App from "./App";
import Methods from "./pages/Methods";
import Trajectory from "./pages/Trajectory";
import Compare from "./pages/Compare";
import Trends from "./pages/Trends";
import Submission from "./pages/Submission";
import "./styles.css";

// HashRouter so the SPA works when served as static files from FastAPI.
const router = createHashRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <Methods /> },
      { path: "trajectory", element: <Trajectory /> },
      { path: "compare", element: <Compare /> },
      { path: "trends", element: <Trends /> },
      { path: "submission", element: <Submission /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
