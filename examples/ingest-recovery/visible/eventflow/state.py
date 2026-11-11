import sqlite3

class State:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS totals(tenant TEXT PRIMARY KEY, amount INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS receipts(tenant TEXT, event_id TEXT, amount INTEGER NOT NULL, PRIMARY KEY(tenant,event_id));
        CREATE TABLE IF NOT EXISTS progress(id INTEGER PRIMARY KEY CHECK(id=1), position INTEGER NOT NULL);
        INSERT OR IGNORE INTO progress VALUES(1,0);
        """)
        self.db.commit()

    @property
    def checkpoint(self):
        return self.db.execute("SELECT position FROM progress WHERE id=1").fetchone()[0]

    def advance(self, position):
        with self.db:
            self.db.execute("UPDATE progress SET position=MAX(position,?) WHERE id=1", (position,))

    def total(self, tenant):
        row = self.db.execute("SELECT amount FROM totals WHERE tenant=?", (tenant,)).fetchone()
        return row[0] if row else 0

    def apply_event(self, event, after_commit=None):
        previous = self.db.execute("SELECT amount FROM receipts WHERE tenant=? AND event_id=?", (event.tenant,event.event_id)).fetchone()
        if previous is not None:
            if previous[0] != event.amount:
                raise ValueError("conflicting duplicate event")
            return False
        total = self.total(event.tenant) + event.amount
        if not -(2**63) <= total < 2**63:
            raise ValueError("total outside signed 64-bit range")
        with self.db:
            self.db.execute("INSERT INTO totals VALUES(?,?) ON CONFLICT(tenant) DO UPDATE SET amount=excluded.amount", (event.tenant,total))
        if after_commit is not None:
            after_commit()
        with self.db:
            self.db.execute("INSERT INTO receipts VALUES(?,?,?)", (event.tenant,event.event_id,event.amount))
        return True

    def close(self):
        self.db.close()
