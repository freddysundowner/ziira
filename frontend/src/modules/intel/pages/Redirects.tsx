import { Navigate, useParams } from "react-router-dom";

/** The earlier addresses of Intelligence's pages: bookmarks and links still arrive in the right place. */
export const ToToday = () => <Navigate to="/intelligence" replace />;
export const ToThings = () => <Navigate to="/intelligence/things" replace />;
export const ToSuggestions = () => <Navigate to="/intelligence/suggestions" replace />;
export const ToWatching = () => <Navigate to="/intelligence/watching" replace />;

export function ToThing() {
  const { findingId = "" } = useParams();
  return <Navigate to={`/intelligence/things/${findingId}`} replace />;
}
