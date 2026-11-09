from bot.middlewares import WakeUpMiddleware


class FakeClock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_fresh_message_no_greeting():
    mw = WakeUpMiddleware(clock=FakeClock())
    assert not mw.should_greet(1, sent_at=1_000_000.0 - 5)


def test_stale_message_greets_once_per_chat():
    clock = FakeClock()
    mw = WakeUpMiddleware(clock=clock)
    old = clock.t - 3600  # написали час назад, пока комп спал
    assert mw.should_greet(1, old)
    assert not mw.should_greet(1, old + 10)  # второе проспанное сообщение — без повтора
    assert mw.should_greet(2, old)  # другой чат — своё приветствие


def test_greets_again_after_next_sleep():
    clock = FakeClock()
    mw = WakeUpMiddleware(clock=clock)
    assert mw.should_greet(1, clock.t - 3600)
    clock.t += 5 * 3600  # следующий сон
    assert mw.should_greet(1, clock.t - 600)
