import json
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("sentury.audit")


def log_decision(
    session_id: str,
    user_id: str,
    user_message: str,
    proposed_tool: Optional[str],
    allowed: Optional[bool],
    reason: str,
    final_action: str,
) -> None:
    record: Dict[str, Any] = {
        "ts": time.time(),
        "session_id": session_id,
        "user_id": user_id,
        "user_message": user_message[:500],
        "proposed_tool": proposed_tool,
        "harness_allowed": allowed,
        "harness_reason": reason,
        "final_action": final_action,
    }
    logger.info(json.dumps(record, ensure_ascii=False))
