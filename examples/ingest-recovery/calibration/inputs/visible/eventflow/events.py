from dataclasses import dataclass

@dataclass(frozen=True)
class Event:
    tenant: str
    event_id: str
    amount: int

    @classmethod
    def parse(cls, record):
        if not isinstance(record, dict):
            raise ValueError("event must be an object")
        tenant, event_id, amount = record.get("tenant"), record.get("event_id"), record.get("amount")
        if not isinstance(tenant, str) or not tenant or not isinstance(event_id, str) or not event_id:
            raise ValueError("nonempty tenant and event_id required")
        if type(amount) is not int or not -(2**31) <= amount < 2**31:
            raise ValueError("amount must be a signed 32-bit integer")
        return cls(tenant, event_id, amount)
