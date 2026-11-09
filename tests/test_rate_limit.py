from services.rate_limit import SlidingWindowLimiter


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_limit_and_window_slide():
    clock = FakeClock()
    lim = SlidingWindowLimiter(3, 60, clock=clock)
    assert all(lim.hit(1) for _ in range(3))
    assert not lim.hit(1)
    assert lim.hit(2)  # другой пользователь не затронут
    clock.t = 60
    assert lim.hit(1)
