"""Per-call detector presets. No speech parsing and no device auto-detection."""
import hmac
import uuid

PRESETS = {
    'normal': {'detector': 'rms', 'min_voiced': .18},
    'car': {'detector': 'webrtcvad', 'min_voiced': .4},
}

def mode_token(secret, mode):
    if mode not in PRESETS:
        raise ValueError('Mode must be normal or car')
    return uuid.uuid5(uuid.UUID(str(secret)), 'no-hands-mode:' + mode)

def incoming_mode(token, secret, detector):
    # Existing private dialplans keep their configured detector until updated.
    base = uuid.UUID(str(secret))
    if hmac.compare_digest(token, base.bytes):
        return 'normal' if detector == 'rms' else 'car'
    for mode in PRESETS:
        if hmac.compare_digest(token, mode_token(base, mode).bytes):
            return mode
    return None
