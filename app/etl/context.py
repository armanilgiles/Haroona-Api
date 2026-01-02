import uuid
from dataclasses import dataclass
from datetime import datetime

@dataclass
class ETLContext:
    run_id: str
    source: str
    started_at: datetime

def create_context(source: str) -> ETLContext:
    return ETLContext(
        run_id=str(uuid.uuid4()),
        source=source,
        started_at=datetime.utcnow(),
    )
