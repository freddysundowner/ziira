import { Navigate } from "react-router-dom";

/** The earlier addresses of the Command Center: old links and bookmarks arrive at Intelligence. */
export const ToToday = () => <Navigate to="/intelligence" replace />;
export const ToSummary = () => <Navigate to="/intelligence/summary" replace />;
