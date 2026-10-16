import { Navigate, useLocation } from "react-router-dom";

/** The old Businesses list is the Subscribers list now; bookmarks and links keep working. */
export default function BusinessesPage() {
  const { search } = useLocation();
  return <Navigate to={`/operator/subscribers${search}`} replace />;
}
