# Audible handoff

During a call, `switch NAME --handoff "Handing you to NAME."` queues the outgoing sentence in the current voice, then announces the switch. A plain `switch NAME` supplies a default outgoing sentence. The bridge requests a one-sentence greeting from the target session. Only its reply triggers the connection tone, “Switched to NAME”, and the greeting.

The command returns when queued, not when connected. Status exposes `handoff.state` and its target. A target that does not reply within 30 seconds after delivery gets an explicit timeout announcement; its route remains selected. Recognized caller speech, another switch, or hangup cancels the handoff and rejects late replies. Unprompted `say` is refused while a handoff is in progress. Idle switching selects the route without announcements.

The outgoing Wolt supplies its sentence through the switch command; the bridge speaks it rather than asking the old session for an extra turn. No new Wolt discovery or session spawning is included.

Validation uses synthetic audio, stubbed speech and fake session delivery in disposable containers. Real phone audio and live session response timing require a caller trial.
