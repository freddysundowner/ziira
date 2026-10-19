import { useParams } from "react-router-dom";

import { PersonView } from "../components/PersonView";

/** One membership, seen through the person who holds it. */
export default function MemberPage() {
  const { memberId = "" } = useParams();
  return <PersonView memberId={memberId} />;
}
