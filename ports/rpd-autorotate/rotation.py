"""Debounced orientation policy, independent of D-Bus and display hardware."""
TRANSFORMS = {'normal': 'normal', 'left-up': '90', 'bottom-up': '180', 'right-up': '270'}
FLAT = {'face-up', 'face-down', 'undefined'}

class RotationPolicy:
    def __init__(self, delay=0.8):
        self.delay = delay
        self.pending = None
        self.deadline = 0
        self.applied = None
        self.portrait = None

    def cancel(self):
        self.pending = None

    def observe(self, orientation, tilt, now):
        if orientation not in TRANSFORMS or tilt in FLAT or orientation == self.applied:
            self.cancel()
        elif orientation != self.pending:
            self.pending = orientation
            self.deadline = now + self.delay

    def due(self, now):
        return self.pending if self.pending and now >= self.deadline else None

    def committed(self, orientation, portrait):
        keyboard = portrait if self.portrait is None or portrait != self.portrait else None
        self.applied, self.portrait = orientation, portrait
        self.cancel()
        return keyboard
