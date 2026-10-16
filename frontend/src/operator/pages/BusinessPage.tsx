import { Navigate, useParams } from "react-router-dom";

/** The old business page is the subscriber page now; bookmarks and links keep working. */
export default function BusinessPage() {
  const code = useParams().code ?? "";
  return <Navigate to={`/operator/subscribers/${encodeURIComponent(code)}`} replace />;
}
