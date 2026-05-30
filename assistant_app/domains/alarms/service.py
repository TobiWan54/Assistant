"""Provides the alarm service."""

from datetime import datetime
from typing import Optional, List

from .store import AlarmStore, Alarm
from .resolver import AlarmResolver

class AlarmService:
    def __init__(self, store: AlarmStore, resolver: Optional[AlarmResolver] = None):
        self.store = store
        self.resolver = resolver

    def now(self) -> datetime:
        return self.store.now()

    def set_alarm(self, when:datetime, label: str = "Alarm") -> Alarm:
        return self.store.set_alarm(when, label)

    def list_alarms(self) -> List[Alarm]:
        return self.store.list_alarms()

    def get_alarm(self, alarm_id: str) -> Optional[Alarm]:
        return self.store.get_alarm(alarm_id)

    def cancel_alarm_by_id(self, alarm_id: str) -> bool:
        return self.store.cancel_alarm(alarm_id)

    def update_alarm_by_id(
            self,
            alarm_id: str,
            when: Optional[datetime] = None,
            label: Optional[str] = None,
            active: Optional[bool] = None) -> Optional[Alarm]:
        return self.store.update_alarm(alarm_id=alarm_id, when=when, label=label, active=active)

    def stop_alarm(self) -> bool:
        return self.store.stop_alarm()

    def snooze_alarm(self, minutes: int = 10, alarm_id: Optional[str] = None) -> Optional[Alarm]:
        return self.store.snooze_alarm(minutes=minutes, alarm_id=alarm_id)

    def find_alarms(self, reference: str) -> dict:
        """
        Hybrid natural-language alarm lookup.

        Behaviour:
        - deterministic candidate retrieval from SQLite
        - if zero candidates: no_match
        - if one candidate: matched
        - if multiple candidates:
            - use AlarmResolver if configured
            - otherwise return ambiguous

        Returned structure:
        {
            "reference": "...",
            "candidate_count": 2,
            "candidates": [...],
            "status": "matched|ambiguous|no_match",
            "alarm_id": "...",          # if matched
            "alarm_ids": ["...","..."], # if ambiguous
            "reason": "..."
        }
        """

        candidates = [a.to_dict() for a in self.store.find_alarms(reference)]

        if not candidates:
            return {
                "reference": reference,
                "candidate_count": 0,
                "candidates": [],
                "status": "no_match",
                "reason": "No alarm candidates were found."
            }

        if len(candidates) == 1:
            return {
                "reference": reference,
                "candidate_count": 1,
                "candidates": candidates,
                "status": "matched",
                "alarm_id": candidates[0]["alarm_id"],
                "reason": "Only one alarm candidate was found."
            }

        if self.resolver is None:
            return {
                "reference": reference,
                "candidate_count": len(candidates),
                "candidates": candidates,
                "status": "ambiguous",
                "alarm_ids": [c["alarm_id"] for c in candidates],
                "reason": "Multiple alarm candidates were found."
            }

        resolution = self.resolver.resolve(reference, candidates)

        result = {
            "reference": reference,
            "candidate_count": len(candidates),
            "candidates": candidates,
            **resolution
        }

        return result