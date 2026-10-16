import { Navigate } from "react-router-dom";

import { ADDONS_PATH } from "../paths";

/** An earlier address of the Add-ons page. */
export default function AppsRedirect() {
  return <Navigate to={ADDONS_PATH} replace />;
}
