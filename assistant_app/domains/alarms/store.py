"""SQLITE database persistence for alarms."""
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional, List


@dataclass
class Alarm:
    alarm_id: str
    when_iso: str
    label: str
    active: bool = True
    ringing: bool = False
    created_at: Optional[str] = None

    @property
    def when(self) -> datetime:
        return datetime.fromisoformat(self.when_iso)

    def to_dict(self) -> dict:
        return {
            "alarm_id": self.alarm_id,
            "when_iso": self.when_iso,
            "label": self.label,
            "active": self.active,
            "ringing": self.ringing,
            "created_at": self.created_at
        }


def row_to_alarm(row: sqlite3.Row) -> Alarm:
    return Alarm(
        alarm_id=row["alarm_id"],
        when_iso=row["when_iso"],
        label=row["label"],
        active=bool(row["active"]),
        ringing=bool(row["ringing"]),
        created_at=row["created_at"]
    )


def extract_time_tokens(text: str) -> List[str]:
    """
    Normalise simple natural time expressions into 24h HH:MM strings.

    Supported examples:
    - 7am      -> 07:00
    - 7 pm     -> 19:00
    - 07:00    -> 07:00
    - 7:30     -> 07:30
    - 7:30 pm  -> 19:30
    """
    tokens = set()
    pattern = r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b"

    for m in re.finditer(pattern, text):
        hour = int(m.group(1))
        minute = int(m.group(2) or "00")
        ampm = m.group(3)

        if minute > 59:
            continue

        if ampm == "am":
            if hour == 12:
                hour = 0
        elif ampm == "pm":
            if hour != 12:
                hour += 12

        if 0 <= hour <= 23:
            tokens.add(f"{hour:02d}:{minute:02d}")

    return sorted(tokens)


def extract_day_hint(text:str) -> Optional[int]:
    """
    Returns:
    - 0 for today
    - 1 for tomorrow
    - None if no day hints
    """
    if "tomorrow" in text:
        return 1
    if any(i in text for i in ["today", "tonight", "this morning", "this afternoon", "this evening"]):
        return 0
    return None


def extract_label_phrases(text:str) -> List[str]:
    """
    Extract progressively broader label phrases from natural language.
    Example: "cancel my 7am gym alarm" -> ["7am gym", "gym"]
    """
    stopwords = {
        "my", "the", "an", "a", "alarm", "for", "at", "in",
        "on", "to", "that", "is", "of", "please", "cancel",
        "delete", "remove", "edit", "update", "change",
        "move", "set", "stop", "snooze", "what", "which",
        "one", "this", "it", "ringing"
    }

    raw_tokens = re.findall(r"[a-z0-9:]+", text.lower())
    useful = [t for t in raw_tokens if t not in stopwords]

    phrases: List[str] = []

    if useful:
        phrases.append(" ".join(useful))

    phrases.extend(useful)

    seen = set()
    deduped = []
    for p in phrases:
        if p and p not in seen:
            seen.add(p)
            deduped.append(p)

    return deduped


class AlarmStore:
    def __init__(self, db_path: str, tz: ZoneInfo):
        self.db_path = db_path
        self.tz = tz
        self.lock = threading.Lock()

        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

        self.init_db()
        self.recover_startup_state()

        self.runner = threading.Thread(target=self.loop, daemon=True)
        self.runner.start()

    def init_db(self):
        with self.lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS alarms (
                    alarm_id   TEXT PRIMARY KEY,
                    when_iso   TEXT NOT NULL,
                    label      TEXT NOT NULL,
                    active     INTEGER NOT NULL DEFAULT 1,
                    ringing    INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS alarms_idx ON alarms(active, when_iso)")
            self.conn.commit()

    def recover_startup_state(self):
        """Clear stale ringing flags to let overdue alarms ring again after restart"""
        with self.lock:
            self.conn.execute("UPDATE alarms SET ringing = 0 WHERE ringing = 1")
            self.conn.commit()

    def now(self) -> datetime:
        return datetime.now(self.tz)

    def loop(self):
        while True:
            with self.lock:
                now_iso = self.now().isoformat()

                cur = self.conn.execute(
                    """
                    SELECT alarm_id FROM alarms
                    WHERE active = 1
                        AND ringing = 0
                        AND when_iso <= ?
                    ORDER BY when_iso ASC
                    """,
                    (now_iso,),
                )
                due_alarm_ids = [r["alarm_id"] for r in cur.fetchall()]

                if due_alarm_ids:
                    for alarm_id in due_alarm_ids:
                        self.conn.execute("UPDATE alarms SET ringing = 1 WHERE alarm_id = ?", (alarm_id,))
                    self.conn.commit()

                cur = self.conn.execute(
                    """
                    SELECT * FROM alarms
                    WHERE alarm_id in ({})
                    ORDER BY when_iso ASC
                    """.format(",".join("?" for _ in due_alarm_ids)),
                    due_alarm_ids
                )
                rows = cur.fetchall()
                for row in rows:
                    alarm = row_to_alarm(row)
                    print(f"\n🔔 ALARM RINGING: {alarm.label} at {alarm.when.strftime('%Y-%m-%d %H:%M')}")

            time.sleep(1)

    def set_alarm(self, when: datetime, label: str = "Alarm") -> Alarm:
        alarm = Alarm(
            alarm_id=str(uuid.uuid4())[:8],
            when_iso=when.isoformat(),
            label=label or "Alarm",
            active=True,
            ringing=False
        )
        with self.lock:
            self.conn.execute(
                """
                INSERT INTO alarms (alarm_id, when_iso, label, active, ringing)
                VALUES (?, ?, ?, ?, ?)""", (alarm.alarm_id, alarm.when_iso, alarm.label, 1, 0)
            )
            self.conn.commit()

            cur = self.conn.execute("SELECT * FROM alarms WHERE alarm_id = ?", (alarm.alarm_id,))
            row = cur.fetchone()
            return row_to_alarm(row)

    def list_alarms(self) -> List[Alarm]:
        """Fetches all alarms, ordered by time with the soonest first"""
        with self.lock:
            cur = self.conn.execute("SELECT * FROM alarms ORDER BY when_iso ASC")
            return [row_to_alarm(row) for row in cur.fetchall()]

    def get_alarm(self, alarm_id: str) -> Optional[Alarm]:
        """Fetches alarm by ``alarm_id``"""
        with self.lock:
            cur = self.conn.execute("SELECT * FROM alarms WHERE alarm_id = ?", (alarm_id,))
            row = cur.fetchone()
            return row_to_alarm(row) if row else None

    def cancel_alarm(self, alarm_id: str) -> bool:
        """Attempts to cancel alarm with ``alarm_id``, returning `true` if any alarm was deleted"""
        with self.lock:
            cur = self.conn.execute("DELETE FROM alarms WHERE alarm_id = ?", (alarm_id,))
            self.conn.commit()
            return cur.rowcount > 0

    def stop_alarm(self) -> bool:
        """Stops currently ringing alarm, returning `true` if an alarm was stopped"""
        with self.lock:
            cur = self.conn.execute("SELECT alarm_id FROM alarms WHERE ringing = 1 ORDER BY when_iso ASC LIMIT 1")
            row = cur.fetchone()
            if not row:
                return False

            alarm_id = row["alarm_id"]
            self.conn.execute(
                """
                UPDATE alarms
                SET ringing = 0, active = 0
                WHERE alarm_id = ?
                """,
                (alarm_id,)
            )
            self.conn.commit()
            return True

    def snooze_alarm(self, minutes: int = 10, alarm_id: Optional[str] = None) -> Optional[Alarm]:
        """Extends time of an alarm by ``minutes``, returning the snoozed alarm.
        If no alarm is defined by ``alarm_id`` the currently ringing alarm is snoozed."""
        with self.lock:
            if alarm_id:
                cur = self.conn.execute("SELECT * FROM alarms WHERE alarm_id = ?", (alarm_id,))
            else:
                cur = self.conn.execute("SELECT * FROM alarms WHERE ringing = 1 ORDER BY when_iso ASC LIMIT 1")

            row = cur.fetchone()
            if not row:
                return None

            target = row_to_alarm(row)
            new_when = self.now() + timedelta(minutes=minutes)

            self.conn.execute(
                """
                UPDATE alarms
                SET when_iso = ?, active = 1, ringing = 0
                WHERE alarm_id = ?
                """,
                (new_when.isoformat(), target.alarm_id,)
            )
            self.conn.commit()

            cur = self.conn.execute("SELECT * FROM alarms WHERE alarm_id = ?", (target.alarm_id,))
            return row_to_alarm(cur.fetchone())

    def update_alarm(self,
                     alarm_id: str,
                     when: Optional[datetime] = None,
                     label: Optional[str] = None,
                     active: Optional[bool] = None,) -> Optional[Alarm]:
        """Updates an alarm with a new time, label or active status."""
        with self.lock:
            cur = self.conn.execute("SELECT * FROM alarms WHERE alarm_id = ?", (alarm_id,))
            row = cur.fetchone()
            if not row:
                return None

        current = row_to_alarm(row)

        new_when_iso = when.isoformat() if when is not None else current.when_iso
        new_label = label if label is not None else current.label
        new_active = int(active) if active is not None else current.active

        self.conn.execute(
            """
            UPDATE alarms
            SET when_iso = ?, label = ?, active = ?
            WHERE alarm_id = ?
            """,
            (new_when_iso, new_label, new_active, alarm_id)
        )
        self.conn.commit()

        cur = self.conn.execute("SELECT * FROM alarms WHERE alarm_id = ?", (alarm_id,))
        return row_to_alarm(cur.fetchone())

    def find_alarms(self, reference: str) -> List[Alarm]:
        """
        Deterministic candidate retrieval for alarm references.

        This does NOT “understand” the reference semantically by itself.
        It generates a reasonable candidate set for the LLM resolver by combining:
        - label substring matching
        - time token extraction (7am, 19:30, etc.)
        - relative phrases (in 5 minutes, in 2 hours)
        - day hints (today, tomorrow)
        - broad label token fallback

        Results are deduplicated and ranked:
        - active alarms first
        - then closest in time to "now"
        """
        if not reference or not reference.strip():
            return []

        ref = reference.strip().lower()
        candidates: dict[str, Alarm] = {}

        # 1. Direct full-reference label match
        for alarm in self.find_alarms_by_label(ref):
            candidates[alarm.alarm_id] = alarm

        # 2. Phrase and token-based label match
        for phrase in extract_label_phrases(ref):
            for alarm in self.find_alarms_by_label(phrase):
                candidates[alarm.alarm_id] = alarm

        # 3. Time match
        time_tokens = extract_time_tokens(ref)
        day_offset = extract_day_hint(ref)

        if day_offset is None:
            for token in time_tokens:
                for alarm in self.find_alarms_by_time_token(token):
                    candidates[alarm.alarm_id] = alarm
        else:
            base_date = (self.now() + timedelta(days=day_offset)).date()
            for token in time_tokens:
                hour, minute = map(int, token.split(":"))
                target_dt = datetime(
                    year = base_date.year,
                    month = base_date.month,
                    day = base_date.day,
                    hour = hour,
                    minute = minute,
                    tzinfo = self.tz
                )
                for alarm in self.find_alarms_near_datetime(target_dt, tolerance_minutes=20):
                    candidates[alarm.alarm_id] = alarm

        # 4. Relative phrases, e.g. 'in 5 minutes'
        for target_dt in self.extract_relative_target_datetimes(ref):
            for alarm in self.find_alarms_near_datetime(target_dt, tolerance_minutes=10):
                candidates[alarm.alarm_id] = alarm

        # 5. Final ranking
        results = list(candidates.values())
        now = self.now()

        def sort_key(a: Alarm):
            delta = abs((a.when - now).total_seconds())
            return not a.active, delta, a.when

        results.sort(key=sort_key)
        return results

    def find_alarms_by_label(self, text: str) -> List[Alarm]:
        with self.lock:
            cur = self.conn.execute("SELECT * FROM alarms WHERE LOWER(label) LIKE ? ORDER BY when_iso ASC",
                                    (f"%{text.lower()}%",))
            return [row_to_alarm(row) for row in cur.fetchall()]

    def find_alarms_by_time_token(self, token: str) -> List[Alarm]:
        """
        token = HH:MM
        Match by wall-clock time portion of when_iso.
        """
        with self.lock:
            cur = self.conn.execute("SELECT * FROM alarms WHERE substr(when_iso, 12, 5) = ? ORDER BY when_iso ASC",
                                    (token,))
            return [row_to_alarm(row) for row in cur.fetchall()]

    def find_alarms_near_datetime(self, target_dt: datetime, tolerance_minutes: int = 5) -> List[Alarm]:
        """Retrieve alarms whose when_iso falls within +/- tolerance_minutes of target_dt."""
        start_dt = target_dt - timedelta(minutes=tolerance_minutes)
        end_dt = target_dt + timedelta(minutes=tolerance_minutes)

        with self.lock:
            cur = self.conn.execute("SELECT * FROM alarms WHERE when_iso BETWEEN ? AND ? ORDER BY when_iso ASC",
                                    (start_dt.isoformat(), end_dt.isoformat()))
            return [row_to_alarm(row) for row in cur.fetchall()]

    def extract_relative_target_datetimes(self, text: str) -> List[datetime]:
        """
        Best-effort extraction for:
        - in 5 minutes
        - in 2 minutes
        """
        results = []
        now = self.now()

        for m in re.finditer(r"\bin\s+(\d+)\s+minutes?\b", text):
            minutes = int(m.group(1))
            results.append(now + timedelta(minutes=minutes))

        for m in re.finditer(r"\bin\s+(\d+)\s+hours?\b", text):
            hours = int(m.group(1))
            results.append(now + timedelta(hours=hours))

        return results

    def close(self):
        with self.lock:
            self.conn.close()