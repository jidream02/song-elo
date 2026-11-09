"""Форматирование ответов (HTML parse mode)."""

from datetime import datetime, timezone
from html import escape

from db.models import Song
from services.elo import PROVISIONAL_MATCHES, is_provisional
from services.llm_rater import CRITERIA
from services.songs import RatingSource, SongRating

HELP = (
    "🎵 <b>Song Elo</b> — рейтинг песен по системе Elo (1500 = средняя песня).\n\n"
    "/rate &lt;песня&gt; — оценить песню\n"
    "/battle — выбрать лучшую из двух песен\n"
    "/top — топ-20 песен\n"
    "/mytop — твой личный рейтинг по баттлам\n"
    "/compare &lt;песня1&gt; | &lt;песня2&gt; — кто победит\n\n"
    "⚖️ Судья — кот автора 🐱. Первую оценку новой песни он даёт по критериям, "
    "дальше рейтинг двигают ваши баттлы.\n\n"
    "😴 <b>Если кот не отвечает — значит, он спит.</b> Проснётся — ответит."
)


def song_title(song: Song) -> str:
    year = f" ({song.year})" if song.year else ""
    return f"<b>{escape(song.artist)} — {escape(song.title)}</b>{year}"


def model_name(model_id: str) -> str:
    """gemini-3.5-flash-lite → Gemini 3.5 Flash-Lite"""
    parts = model_id.split("-")
    out = parts[0].capitalize()
    rest = parts[1:]
    if rest and rest[0][:1].isdigit():
        out += " " + rest.pop(0)
    if rest:
        out += " " + "-".join(p.capitalize() for p in rest)
    return out


def _bar(score: int) -> str:
    return "█" * score + "░" * (10 - score)


def rating_card(r: SongRating) -> str:
    s = r.song
    lines = [song_title(s)]
    if s.genre:
        lines.append(f"<i>{escape(s.genre)}</i>")
    lines.append("")

    if r.source is RatingSource.BATTLES:
        lines.append(f"🏆 <b>Elo: {round(s.rating)}</b> — по {s.matches} баттлам ({s.wins} побед)")
    elif r.source is RatingSource.LLM:
        lines.append(f"🤖 <b>Elo: {round(s.rating)}</b> — предварительная оценка")
        if s.matches:
            lines.append(f"Стартовая оценка ИИ: {s.llm_elo}, уже скорректирована {s.matches} баттлами.")
        else:
            lines.append(f"Нужно {PROVISIONAL_MATCHES} баттлов, чтобы рейтинг стал «настоящим».")
    elif r.source is RatingSource.UNKNOWN:
        lines.append("🤷 <b>Честно: я не знаю эту песню достаточно хорошо</b>, чтобы её оценить.")
        lines.append("Выдумывать оценку не буду — отправь её в баттлы, и рейтинг сформируют люди.")
        if s.matches:
            lines.append(f"Сейчас по баттлам: {round(s.rating)} ({s.matches} матчей, пока мало).")
    elif r.source is RatingSource.DAILY_LIMIT:
        lines.append("😾 <b>Кот устал оценивать твои новые песни.</b>")
        wait = ""
        if r.retry_at is not None:
            mins = max(1, int((r.retry_at - datetime.now(timezone.utc)).total_seconds() // 60) + 1)
            wait = f" Следующая оценка через {mins // 60} ч {mins % 60} мин." if mins >= 60 else f" Следующая оценка через {mins} мин."
        lines.append(f"Лимит — {r.daily_limit} новых песен в сутки на человека.{wait}")
        lines.append("Песни, которые уже есть в базе, доступны всегда: /top, /battle.")
    elif r.source is RatingSource.NO_LLM:
        lines.append(f"⚔️ <b>Elo: {round(s.rating)}</b> — {s.matches} из {PROVISIONAL_MATCHES} баттлов")
        lines.append("ИИ-оценка выключена, рейтинг формируют только ваши баттлы.")
        if not s.matches:
            lines.append("Песня добавлена в баттлы — жми /battle.")
    else:
        lines.append("⚠️ Не получилось получить оценку от ИИ, попробуй позже.")
        if s.matches:
            lines.append(f"Текущий рейтинг по баттлам: {round(s.rating)} ({s.matches} матчей).")

    llm = r.llm
    # Для «не знаю» критерии не показываем — их либо нет, либо им нельзя доверять.
    if llm and llm.criteria and r.source is not RatingSource.UNKNOWN:
        lines.append("\n<b>Критерии (ИИ):</b>")
        for key, label in CRITERIA.items():
            score = llm.criteria.get(key)
            if score is None:
                lines.append(f"<code>{'·' * 10}</code> —  {label} (не применимо)")
                continue
            lines.append(f"<code>{_bar(score)}</code> {score}/10 <b>{label}</b>")
            why = (llm.analysis or {}).get(key)
            if why:
                lines.append(f"<i>{escape(why)}</i>")
        model = llm.model or s.llm_model
        who = f" · оценил {escape(model_name(model))}" if model else ""
        lines.append(f"\nУверенность модели: {round(llm.confidence * 100)}%{who}")
        if llm.strengths:
            lines.append("\n<b>👍 Сильные стороны:</b>")
            lines += [f"• {escape(x)}" for x in llm.strengths]
        if llm.weaknesses:
            lines.append("\n<b>👎 Слабые стороны:</b>")
            lines += [f"• {escape(x)}" for x in llm.weaknesses]

    if s.spotify_url:
        lines.append(f'\n<a href="{escape(s.spotify_url)}">Открыть в Spotify</a>')
    return "\n".join(lines)


def battle_text(a: Song, b: Song) -> str:
    return f"⚔️ <b>Какая песня лучше?</b>\n\n🅰 {song_title(a)}\n\n🅱 {song_title(b)}"


def top_line(i: int, song: Song, rating: float, matches: int, medals: bool = True, mark_provisional: bool = True) -> str:
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.") if medals else f"{i}."
    mark = " <i>(пред.)</i>" if mark_provisional and is_provisional(matches) else ""
    return f"{medal} <b>{round(rating)}</b> — {escape(song.artist)} — {escape(song.title)}{mark}"
