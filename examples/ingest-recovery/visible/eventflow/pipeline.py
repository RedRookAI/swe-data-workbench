from .events import Event

def process(records, state, after_commit=None):
    """Consume the complete ordered source; resume after the durable checkpoint."""
    for position, record in enumerate(records, 1):
        if position <= state.checkpoint:
            continue
        event = Event.parse(record)
        callback = None if after_commit is None else lambda: after_commit(position)
        state.apply_event(event, after_commit=callback)
        state.advance(position)
    return {"checkpoint": state.checkpoint}
