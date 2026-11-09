from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import Song


def _short(song: Song, limit: int = 40) -> str:
    text = f"{song.artist} — {song.title}"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def battle_kb(offer_id: int, a: Song, b: Song) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🅰 {_short(a)}", callback_data=f"vote:{offer_id}:a")
    kb.button(text=f"🅱 {_short(b)}", callback_data=f"vote:{offer_id}:b")
    kb.adjust(1)
    return kb.as_markup()


def next_battle_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⚔️ Следующий баттл", callback_data="battle:next")
    return kb.as_markup()


def to_pool_kb(song_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⚔️ Отправить в баттлы", callback_data=f"pool:{song_id}")
    return kb.as_markup()
