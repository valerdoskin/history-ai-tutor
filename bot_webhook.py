"""
History AI Tutor — Telegram-бот + Web App.

Flask-приложение с webhook для python-telegram-bot и Web App API.
"""

import logging
import os

from flask import Flask, jsonify, request, send_from_directory
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from database import db
from services import (
    adaptive_service,
    analytics_service,
    exam_service,
    gamification_service,
    knowledge_service,
    progress_service,
    tutor_service,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ============================================================
# Telegram-бот
# ============================================================
bot_app = None


def get_bot_app():
    global bot_app
    if bot_app is None:
        bot_app = Application.builder().token(config.BOT_TOKEN).build()
        _register_handlers(bot_app)
    return bot_app


def _register_handlers(application):
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("menu", cmd_menu))
    application.add_handler(CommandHandler("profile", cmd_profile))
    application.add_handler(CommandHandler("practice", cmd_practice))
    application.add_handler(CommandHandler("exam", cmd_exam))
    application.add_handler(CommandHandler("weak", cmd_weak))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


# ============================================================
# Команды
# ============================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    progress_service.register_user(user.id, user.username, user.first_name)
    progress_service.record_activity(user.id)

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📚 Открыть Web App", web_app=WebAppInfo(url=config.WEBAPP_DOMAIN))],
            [InlineKeyboardButton("📖 Начать обучение", callback_data="menu_learn")],
            [InlineKeyboardButton("📝 Практика ОГЭ", callback_data="menu_oge")],
            [InlineKeyboardButton("🎓 Практика ЕГЭ", callback_data="menu_ege")],
            [InlineKeyboardButton("👤 Мой профиль", callback_data="menu_profile")],
        ]
    )
    await update.message.reply_text(
        f"Привет, {user.first_name}! 👋\n\n"
        "Я — ИИ-репетитор по истории для подготовки к ОГЭ и ЕГЭ.\n"
        "Я отвечаю только на основе учебников из базы знаний.\n\n"
        "Задай мне любой вопрос по истории или выбери действие:",
        reply_markup=keyboard,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *Как пользоваться:*\n\n"
        "• Задай вопрос по истории — я отвечу на основе учебников\n"
        "• /practice — тренировка по темам\n"
        "• /exam — задания ОГЭ/ЕГЭ\n"
        "• /profile — твой прогресс и достижения\n"
        "• /weak — слабые темы для повторения\n\n"
        "Открывай Web App для удобного интерфейса!",
        parse_mode="Markdown",
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📖 Начать обучение", callback_data="menu_learn")],
            [InlineKeyboardButton("📝 Практика ОГЭ", callback_data="menu_oge")],
            [InlineKeyboardButton("🎓 Практика ЕГЭ", callback_data="menu_ege")],
            [InlineKeyboardButton("👤 Мой профиль", callback_data="menu_profile")],
            [InlineKeyboardButton("📊 Аналитика", callback_data="menu_analytics")],
        ]
    )
    await update.message.reply_text("Выбери действие:", reply_markup=keyboard)


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    profile = gamification_service.get_profile(user_id)
    user = profile["user"]
    stats = profile["stats"]

    text = (
        f"👤 *Профиль*\n\n"
        f"Имя: {user['first_name'] or '—'}\n"
        f"Уровень: {user['level']} ({profile['rank']})\n"
        f"XP: {user['xp']}\n"
        f"Серия дней: {user['streak']} 🔥\n\n"
        f"📊 *Статистика:*\n"
        f"Вопросов решено: {stats['total_questions']}\n"
        f"Правильных: {stats['correct_questions']}\n"
        f"Точность: {stats['accuracy']}%\n\n"
        f"🏆 *Достижения:* {len(profile['achievements'])}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_practice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    progress_service.record_activity(user_id)
    question = tutor_service.quiz_question(user_id=user_id)
    await _send_quiz(update, question)


async def cmd_exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝 ОГЭ", callback_data="exam_oge")],
            [InlineKeyboardButton("🎓 ЕГЭ", callback_data="exam_ege")],
        ]
    )
    await update.message.reply_text("Выбери формат экзамена:", reply_markup=keyboard)


async def cmd_weak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    weak = progress_service.get_weak_topics(user_id)
    if not weak:
        await update.message.reply_text("Отлично! У тебя нет слабых тем. 🎉")
        return
    text = "📉 *Слабые темы для повторения:*\n\n"
    for t in weak:
        text += f"• {t['topic']} (ошибок: {t['error_count']})\n"
    await update.message.reply_text(text, parse_mode="Markdown")


# ============================================================
# Обработка сообщений
# ============================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    query = update.message.text
    progress_service.record_activity(user_id)

    # Показываем "печатает"
    await context.bot.send_chat_action(chat_id=user_id, action="typing")

    # Персонализация на основе уровня
    personal = adaptive_service.personalize_prompt(user_id)

    try:
        result = tutor_service.answer_question(query, user_id=user_id)
        answer = result["answer"]
        sources = result["sources"]

        # Добавляем источники
        if sources:
            answer += "\n\n📚 *Источники:*\n"
            for s in sources[:3]:
                answer += f"• {s['book']} — {s['chapter']} — {s['paragraph']}\n"

        # Начисляем XP за вопрос
        gamification_service.award_xp(user_id, config.XP_PER_QUESTION)

        await update.message.reply_text(answer, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка при ответе: {e}")
        await update.message.reply_text(
            "Извини, произошла ошибка. Попробуй ещё раз или переформулируй вопрос."
        )


# ============================================================
# Callback-обработчики
# ============================================================
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data

    if data == "menu_learn":
        await query.edit_message_text(
            "📖 *Обучение*\n\n"
            "Задай мне вопрос по любой теме истории России или всемирной истории.\n"
            "Например: «Расскажи про Куликовскую битву» или «Кто такой Иван Грозный?»"
        )
    elif data == "menu_oge":
        await _start_exam(query, "oge")
    elif data == "menu_ege":
        await _start_exam(query, "ege")
    elif data == "menu_profile":
        profile = gamification_service.get_profile(user_id)
        user = profile["user"]
        stats = profile["stats"]
        await query.edit_message_text(
            f"👤 *Профиль*\n\n"
            f"Уровень: {user['level']} ({profile['rank']})\n"
            f"XP: {user['xp']} | Серия: {user['streak']} 🔥\n"
            f"Точность: {stats['accuracy']}%\n"
            f"Достижений: {len(profile['achievements'])}"
        )
    elif data == "menu_analytics":
        report = analytics_service.get_learning_report(user_id)
        text = "📊 *Аналитика обучения*\n\n"
        text += f"Вопросов решено: {report['stats']['total_questions']}\n"
        text += f"Точность: {report['stats']['accuracy']}%\n\n"
        text += "*Рекомендации:*\n"
        for r in report["recommendations"]:
            text += f"• {r}\n"
        await query.edit_message_text(text)
    elif data.startswith("exam_"):
        exam_type = data.split("_")[1]
        await _start_exam(query, exam_type)
    elif data.startswith("quiz_"):
        await _handle_quiz_answer(query, data)


async def _start_exam(query, exam_type):
    user_id = query.from_user.id
    try:
        if exam_type == "oge":
            question = exam_service.generate_oge_question()
            options = question.get("options", [])
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(f"{i+1}. {opt[:30]}", callback_data=f"oge_ans_{i}")
                        for i, opt in enumerate(options)
                    ]
                ]
            )
            await query.edit_message_text(
                f"📝 *ОГЭ — задание*\n\n{question['question']}",
                reply_markup=keyboard,
            )
        else:
            question = exam_service.generate_ege_question()
            await query.edit_message_text(
                f"🎓 *ЕГЭ — задание*\n\n{question['question']}\n\n"
                "Напиши ответ текстом в чат."
            )
    except Exception as e:
        logger.error(f"Ошибка генерации задания: {e}")
        await query.edit_message_text("Не удалось сгенерировать задание. Попробуй ещё раз.")


async def _handle_quiz_answer(query, data):
    user_id = query.from_user.id
    # Упрощённая обработка — в реальном приложении хранить состояние
    await query.edit_message_text("Ответ принят! ✅")


async def _send_quiz(update, question):
    options = question.get("options", [])
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"{i+1}. {opt[:30]}", callback_data=f"quiz_{i}")
                for i, opt in enumerate(options)
            ]
        ]
    )
    await update.message.reply_text(
        f"❓ *Вопрос:*\n{question['question']}",
        reply_markup=keyboard,
    )


# ============================================================
# Flask: Web App + webhook
# ============================================================
@app.route("/")
def index():
    return send_from_directory("templates", "webapp.html")


@app.route("/static/<path:path>")
def static_files(path):
    return send_from_directory("static", path)


@app.route(config.WEBHOOK_PATH, methods=["POST"])
def webhook():
    if config.WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != config.WEBHOOK_SECRET:
        return jsonify({"error": "Unauthorized"}), 401
    update = Update.de_json(request.get_json(force=True), get_bot_app().bot)
    get_bot_app().process_update(update)
    return jsonify({"ok": True})


@app.route("/api/ask", methods=["POST"])
def api_ask():
    """API для Web App: задать вопрос."""
    data = request.get_json()
    query = data.get("query", "")
    user_id = data.get("user_id")
    if not query:
        return jsonify({"error": "query required"}), 400
    result = tutor_service.answer_question(query, user_id=user_id)
    return jsonify(result)


@app.route("/api/profile", methods=["GET"])
def api_profile():
    user_id = request.args.get("user_id")
    if not user_id or user_id == "null":
        return jsonify({"error": "user_id required"}), 400
    profile = gamification_service.get_profile(int(user_id))
    return jsonify(profile)


@app.route("/api/exam", methods=["GET"])
def api_exam():
    """API для Web App: генерация задания ОГЭ/ЕГЭ."""
    exam_type = request.args.get("type", "oge")
    user_id = request.args.get("user_id")
    try:
        if exam_type == "ege":
            question = exam_service.generate_ege_question()
        else:
            question = exam_service.generate_oge_question()
        if user_id and user_id != "null":
            progress_service.record_activity(int(user_id))
        return jsonify(question)
    except Exception as e:
        logger.error(f"Ошибка генерации задания: {e}")
        return jsonify({"error": "Не удалось сгенерировать задание"}), 500


@app.route("/api/topics", methods=["GET"])
def api_topics():
    """API для Web App: список тем (глав) из базы знаний."""
    try:
        return jsonify({"topics": knowledge_service.get_topics()})
    except Exception as e:
        logger.error(f"Ошибка получения тем: {e}")
        return jsonify({"error": "Не удалось получить темы"}), 500


@app.route("/api/topic/<int:topic_id>", methods=["GET"])
def api_topic(topic_id):
    """API для Web App: детали темы по id."""
    try:
        topic = knowledge_service.get_topic(topic_id)
        if not topic:
            return jsonify({"error": "Тема не найдена"}), 404
        return jsonify(topic)
    except Exception as e:
        logger.error(f"Ошибка получения темы: {e}")
        return jsonify({"error": "Не удалось получить тему"}), 500


@app.route("/api/chronology", methods=["GET"])
def api_chronology():
    """API для Web App: хронология (даты и события)."""
    try:
        limit = request.args.get("limit", default=200, type=int)
        return jsonify({"events": knowledge_service.get_chronology(limit=limit)})
    except Exception as e:
        logger.error(f"Ошибка получения хронологии: {e}")
        return jsonify({"error": "Не удалось получить хронологию"}), 500


@app.route("/api/figures", methods=["GET"])
def api_figures():
    """API для Web App: исторические личности."""
    try:
        limit = request.args.get("limit", default=200, type=int)
        return jsonify({"figures": knowledge_service.get_figures(limit=limit)})
    except Exception as e:
        logger.error(f"Ошибка получения личностей: {e}")
        return jsonify({"error": "Не удалось получить личности"}), 500


@app.route("/api/terms", methods=["GET"])
def api_terms():
    """API для Web App: термины с определениями."""
    try:
        limit = request.args.get("limit", default=300, type=int)
        return jsonify({"terms": knowledge_service.get_terms(limit=limit)})
    except Exception as e:
        logger.error(f"Ошибка получения терминов: {e}")
        return jsonify({"error": "Не удалось получить термины"}), 500


@app.route("/api/exam/submit", methods=["POST"])
def api_exam_submit():
    """API для Web App: проверка ответа на задание ОГЭ/ЕГЭ."""
    data = request.get_json() or {}
    exam_type = data.get("type", "oge")
    user_id = data.get("user_id")
    question = data.get("question", {})
    user_answer = data.get("answer")
    if not question or user_answer is None:
        return jsonify({"error": "question и answer обязательны"}), 400
    try:
        if exam_type == "ege":
            correct_answer = question.get("answer") or question.get("correct_answer")
            is_correct = exam_service.check_ege_answer(user_answer, correct_answer)
        else:
            correct_index = question.get("correct_index")
            options = question.get("options", [])
            correct_answer = options[correct_index] if 0 <= correct_index < len(options) else ""
            is_correct = exam_service.check_oge_answer(
                question, user_answer, correct_index, options
            )
        result = {"correct": bool(is_correct)}
        if user_id and user_id != "null":
            uid = int(user_id)
            progress_service.record_activity(uid)
            db.add_exam_result(
                uid,
                exam_type,
                question.get("question", ""),
                user_answer,
                correct_answer,
                int(is_correct),
                question.get("topic", ""),
            )
            if result["correct"]:
                progress_service.add_xp(uid, config.XP_PER_QUESTION)
                gamification_service.award_xp(uid, config.XP_PER_QUESTION)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Ошибка проверки ответа: {e}")
        return jsonify({"error": "Не удалось проверить ответ"}), 500


@app.route("/api/progress", methods=["GET"])
def api_progress():
    """API для Web App: прогресс пользователя."""
    user_id = request.args.get("user_id")
    if not user_id or user_id == "null":
        return jsonify({"error": "user_id required"}), 400
    try:
        summary = progress_service.get_progress_summary(int(user_id))
        profile = gamification_service.get_profile(int(user_id))
        return jsonify({"progress": summary, "profile": profile})
    except Exception as e:
        logger.error(f"Ошибка получения прогресса: {e}")
        return jsonify({"error": "Не удалось получить прогресс"}), 500


@app.route("/api/cards", methods=["GET"])
def api_cards():
    """API для Web App: ежедневные карточки для повторения."""
    user_id = request.args.get("user_id")
    if not user_id or user_id == "null":
        return jsonify({"error": "user_id required"}), 400
    try:
        cards = adaptive_service.get_daily_cards(int(user_id))
        summary = adaptive_service.get_srs_summary(int(user_id))
        return jsonify({"cards": cards, "summary": summary})
    except Exception as e:
        logger.error(f"Ошибка получения карточек: {e}")
        return jsonify({"error": "Не удалось получить карточки"}), 500


@app.route("/api/cards", methods=["POST"])
def api_cards_add():
    """API для Web App: добавить карточку для повторения."""
    data = request.get_json() or {}
    user_id = data.get("user_id")
    if not user_id or user_id == "null":
        return jsonify({"error": "user_id required"}), 400
    topic = data.get("topic", "")
    question = data.get("question", "")
    answer = data.get("answer", "")
    if not topic or not question or not answer:
        return jsonify({"error": "topic, question и answer обязательны"}), 400
    result = adaptive_service.add_card(int(user_id), topic, question, answer)
    return jsonify(result)


@app.route("/api/cards/review", methods=["POST"])
def api_cards_review():
    """API для Web App: оценить карточку (SM-2)."""
    data = request.get_json() or {}
    user_id = data.get("user_id")
    if not user_id or user_id == "null":
        return jsonify({"error": "user_id required"}), 400
    card_id = data.get("card_id")
    quality = data.get("quality")
    if card_id is None or quality is None:
        return jsonify({"error": "card_id и quality обязательны"}), 400
    try:
        result = adaptive_service.review_card(int(card_id), int(quality))
        if not result:
            return jsonify({"error": "Карточка не найдена"}), 404
        return jsonify(result)
    except Exception as e:
        logger.error(f"Ошибка оценки карточки: {e}")
        return jsonify({"error": "Не удалось оценить карточку"}), 500


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


def main():
    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN не задан в .env")
        return

    if config.WEBHOOK_DOMAIN:
        # Режим webhook
        app.run(host=config.WEBAPP_HOST, port=config.WEBAPP_PORT)
    else:
        # Режим polling (для локальной разработки)
        application = get_bot_app()
        application.run_polling()


if __name__ == "__main__":
    main()
