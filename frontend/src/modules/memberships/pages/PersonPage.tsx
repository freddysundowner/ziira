import { useParams } from "react-router-dom";

import { PersonView } from "../components/PersonView";

/** A person's page by customer: profile, money, visits, for someone with or without a membership. */
export default function PersonPage() {
  const { customerId = "" } = useParams();
  return <PersonView customerId={customerId} />;
}
