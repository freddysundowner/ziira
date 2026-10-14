"""Background work of the Data Import module (run by `ziira worker`): importing the rows of a committed batch."""

from typing import Any
from uuid import UUID

from ziira.modules.imports.services import batches
from ziira.sdk import Session, job


@job(batches.COMMIT_JOB)
def commit(session: Session, payload: dict[str, Any]) -> None:
    """Import the next rows of a batch; when rows are left it queues itself again. Safe to run twice."""
    batches.import_chunk(session, UUID(str(payload["batch_id"])))
