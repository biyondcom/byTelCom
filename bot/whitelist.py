from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class WhitelistChecker:
    def __init__(self, allowed_user_ids: list[int]):
        self._allowed = set(allowed_user_ids)

    def is_authorized(self, user_id: int) -> bool:
        if user_id in self._allowed:
            return True
        logger.warning("Unauthorized access attempt from user_id=%d", user_id)
        return False
