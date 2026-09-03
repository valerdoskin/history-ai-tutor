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
    placement_service,
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
    application.add_handler(CommandHandler("test", cmd_test))
    application.add_handler(CommandHandler("classes", cmd_classes))
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


async def cmd_classes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /classes — выбор классов для обучения."""
    user_id = update.effective_user.id
    classes_info = placement_service.get_classes_info()
    current = db.get_selected_classes(user_id)

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📚 Вся база знаний", callback_data="cls_all")],
            [
                InlineKeyboardButton(f"{c['class']} класс", callback_data=f"cls_{c['class']}")
                for c in classes_info
            ],
            [InlineKeyboardButton("✅ Готово", callback_data="cls_done")],
        ]
    )
    text = (
        "🎓 *Выбери классы для обучения*\n\n"
        "Можно выбрать один или несколько классов, либо всю базу знаний.\n\n"
        f"Текущий выбор: {current if current != 'all' else 'вся база знаний'}\n\n"
        "Нажимай на классы, чтобы выбрать. Когда закончишь — нажми «Готово»."
    )
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /test — пройти изначальный тест уровня."""
    user_id = update.effective_user.id
    progress_service.record_activity(user_id)
    test = placement_service.generate_placement_test(user_id=user_id)
    if not test:
        await update.message.reply_text("Не удалось сгенерировать тест. Попробуй ещё раз.")
        return

    # Сохраняем тест в контексте пользователя
    context.user_data["placement"] = test
    context.user_data["placement_idx"] = 0
    context.user_data["placement_answers"] = []

    await _send_placement_question(update.message, context)


async def _send_placement_question(message, context):
    """Отправляет текущий вопрос теста уровня."""
    test = context.user_data.get("placement", [])
    idx = context.user_data.get("placement_idx", 0)
    if idx >= len(test):
        await _finish_placement(message, context)
        return

    q = test[idx]
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"{i+1}. {opt[:30]}", callback_data=f"plc_{idx}_{i}")
                for i, opt in enumerate(q["options"])
            ]
        ]
    )
    text = (
        f"📝 *Тест уровня — вопрос {idx + 1} из {len(test)}*\n"
        f"({q['class']} класс)\n\n"
        f"{q['question']}"
    )
    await message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def _finish_placement(message, context):
    """Завершает тест уровня и показывает результат с разбором ответов."""
    user_id = message.from_user.id
    answers = context.user_data.get("placement_answers", [])
    result = placement_service.submit_placement(user_id, answers)
    if "error" in result:
        await message.reply_text(result["error"])
        return

    text = (
        f"🎉 *Тест уровня пройден!*\n\n"
        f"Правильных ответов: {result['score']} из {result['total']}\n"
        f"Твой уровень: *{result['level']}* ({result['rank']})\n\n"
        f"Мы подберём задания под твой уровень знаний!"
    )
    await message.reply_text(text, parse_mode="Markdown")

    # Разбор ответов
    details = result.get("details", [])
    if not details:
        return
    lines = ["📋 *Разбор ответов:*"]
    for i, d in enumerate(details, 1):
        mark = "✅" if d.get("correct") else "❌"
        lines.append(f"\n{mark} *{i}. {d.get('question', '')}*")
        user_idx = d.get("user_index")
        user_opt = (
            d["options"][user_idx] if user_idx is not None and user_idx < len(d["options"]) else "—"
        )
        correct_opt = d["options"][d.get("correct_index")] if d.get("correct_index") is not None else "—"
        if d.get("correct"):
            lines.append(f"Ваш ответ: {user_opt}")
        else:
            lines.append(f"Ваш ответ: {user_opt}")
            lines.append(f"Правильный ответ: {correct_opt}")
    # Telegram ограничивает длину сообщения ~4096 символов — шлём частями
    chunk = []
    chunk_len = 0
    for line in lines:
        if chunk_len + len(line) + 1 > 4000 and chunk:
            await message.reply_text("\n".join(chunk), parse_mode="Markdown")
            chunk = []
            chunk_len = 0
        chunk.append(line)
        chunk_len += len(line) + 1
    if chunk:
        await message.reply_text("\n".join(chunk), parse_mode="Markdown")


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

        # Добавляем источники (ссылки на параграфы учебников)
        if sources:
            answer += "\n\n📚 *Источники:*\n"
            for s in sources[:3]:
                line = "• "
                parts = []
                if s.get("book"):
                    parts.append(s["book"])
                if s.get("chapter"):
                    parts.append(s["chapter"])
                if s.get("paragraph"):
                    parts.append(s["paragraph"])
                line += " — ".join(parts)
                if s.get("page_start"):
                    line += f" (с. {s['page_start']}"
                    if s.get("page_end") and s["page_end"] != s["page_start"]:
                        line += f"–{s['page_end']}"
                    line += ")"
                answer += line + "\n"

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
    elif data.startswith("cls_"):
        await _handle_class_selection(query, context, data)
    elif data.startswith("plc_"):
        await _handle_placement_answer(query, context, data)


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


async def _handle_class_selection(query, context, data):
    """Обрабатывает выбор классов через inline-кнопки."""
    user_id = query.from_user.id
    action = data.split("_", 1)[1]

    # Храним выбранные классы в user_data
    selected = context.user_data.get("cls_selected", set())

    if action == "all":
        selected = set()
        context.user_data["cls_all"] = True
    elif action == "done":
        if context.user_data.get("cls_all"):
            db.set_selected_classes(user_id, "all")
        elif selected:
            db.set_selected_classes(user_id, ",".join(sorted(selected)))
        else:
            await query.edit_message_text(
                "Выбери хотя бы один класс или «Всю базу знаний»."
            )
            return
        context.user_data.pop("cls_selected", None)
        context.user_data.pop("cls_all", None)
        await query.edit_message_text("✅ Выбор классов сохранён!")
        return
    else:
        # Переключаем конкретный класс
        context.user_data["cls_all"] = False
        cls = action
        if cls in selected:
            selected.discard(cls)
        else:
            selected.add(cls)
        context.user_data["cls_selected"] = selected

    # Показываем текущий выбор
    classes_info = placement_service.get_classes_info()
    current = "вся база знаний" if context.user_data.get("cls_all") else (
        ", ".join(sorted(selected)) + " класс" if selected else "не выбран"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📚 Вся база знаний", callback_data="cls_all")],
            [
                InlineKeyboardButton(
                    f"{'✅ ' if c['class'] in selected else ''}{c['class']} класс",
                    callback_data=f"cls_{c['class']}",
                )
                for c in classes_info
            ],
            [InlineKeyboardButton("✅ Готово", callback_data="cls_done")],
        ]
    )
    await query.edit_message_text(
        f"🎓 *Выбери классы для обучения*\n\n"
        f"Текущий выбор: {current}\n\n"
        "Нажимай на классы, чтобы выбрать. Когда закончишь — нажми «Готово».",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


async def _handle_placement_answer(query, context, data):
    """Обрабатывает ответ на вопрос теста уровня."""
    user_id = query.from_user.id
    parts = data.split("_")
    idx = int(parts[1])
    answer_index = int(parts[2])

    test = context.user_data.get("placement", [])
    answers = context.user_data.get("placement_answers", [])
    if idx < len(test):
        q = test[idx]
        answers.append({"question_id": q["id"], "answer_index": answer_index})
        context.user_data["placement_answers"] = answers

    context.user_data["placement_idx"] = idx + 1
    await _send_placement_question(query.message, context)


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
    classes = "all"
    if user_id and user_id != "null":
        classes = db.get_selected_classes(int(user_id))
    result = tutor_service.answer_question(query, user_id=user_id, class_filter=classes)
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
    qtype = request.args.get("qtype")
    user_id = request.args.get("user_id")
    try:
        classes = "all"
        if user_id and user_id != "null":
            classes = db.get_selected_classes(int(user_id))
        if exam_type == "ege":
            question = exam_service.generate_ege_question(qtype=qtype, classes=classes)
        else:
            question = exam_service.generate_oge_question(qtype=qtype, classes=classes)
        if user_id and user_id != "null":
            progress_service.record_activity(int(user_id))
        return jsonify(question)
    except Exception as e:
        logger.error(f"Ошибка генерации задания: {e}")
        return jsonify({"error": "Не удалось сгенерировать задание"}), 500


@app.route("/api/exam/types", methods=["GET"])
def api_exam_types():
    """API для Web App: список типов вопросов и их соответствие заданиям ФИПИ."""
    return jsonify({"types": exam_service.get_question_types()})


# Типы заданий, доступные в тренировочных режимах (Этап 7)
TRAIN_TYPES = [
    {"qtype": "culture", "label": "Культура", "oge": [13, 14], "ege": [7, 15, 16]},
    {"qtype": "map", "label": "Карты", "oge": [8, 9, 10], "ege": [9, 10, 11, 12]},
    {"qtype": "source", "label": "Источники", "oge": [17, 18, 19, 20], "ege": [6, 13, 14]},
    {"qtype": "argumentation", "label": "Аргументация", "oge": [6], "ege": [21]},
    {"qtype": "chronology", "label": "Хронология", "oge": [1, 2], "ege": [1, 2]},
    {"qtype": "cause_effect", "label": "Причинно-следственные связи", "oge": [21], "ege": [18]},
    {"qtype": "comparison", "label": "Сравнение", "oge": [23], "ege": [20]},
]


def _train_question(exam_type, qtype, classes):
    """Генерирует одно тренировочное задание нужного типа.

    Возвращает задание в формате, совместимом с /api/test/submit
    (type: mcq / short / source). Если сгенерировать не удалось — None.
    """
    if qtype == "culture":
        if exam_type == "oge":
            q = exam_service.generate_culture_question(classes=classes)
            if q:
                q["type"] = "mcq"
        else:
            q = exam_service.generate_ege_question(qtype="culture", classes=classes)
            if q:
                q["type"] = "short"
    elif qtype == "map":
        q = exam_service.generate_map_question(classes=classes)
        if q:
            q["type"] = "mcq"
    elif qtype == "source":
        q = exam_service.generate_source_question(classes=classes)
        if q:
            q["type"] = "source"
    elif qtype == "argumentation":
        if exam_type == "oge":
            q = exam_service.generate_oge_question(qtype="argumentation", classes=classes)
            if q:
                q["type"] = "mcq"
        else:
            q = exam_service.generate_argumentation_question(classes=classes)
            if q:
                q["type"] = "short"
    else:
        # chronology / cause_effect / comparison / term / fact
        if exam_type == "oge":
            q = exam_service.generate_oge_question(qtype=qtype, classes=classes)
            if q:
                q["type"] = "mcq"
        else:
            q = exam_service.generate_ege_question(qtype=qtype, classes=classes)
            if q:
                q["type"] = "short"
    if q:
        q["points"] = 1
    return q


@app.route("/api/train", methods=["GET"])
def api_train():
    """API для Web App: серия тренировочных заданий одного типа.

    Параметры: type (oge/ege), qtype (culture/map/source/...), count,
    user_id. Возвращает {"questions": [...], "qtype": ..., "exam_type": ...}.
    """
    exam_type = request.args.get("type", "oge")
    qtype = request.args.get("qtype")
    user_id = request.args.get("user_id")
    count = request.args.get("count", default=5, type=int)
    count = max(1, min(10, count))
    if qtype not in {t["qtype"] for t in TRAIN_TYPES}:
        return jsonify({"error": "Неизвестный тип задания"}), 400
    try:
        classes = "all"
        if user_id and user_id != "null":
            classes = db.get_selected_classes(int(user_id))
        questions = []
        seen = set()
        attempts = 0
        while len(questions) < count and attempts < count * 5:
            attempts += 1
            q = _train_question(exam_type, qtype, classes)
            if not q or not q.get("question"):
                continue
            # Пропускаем некорректные/повторяющиеся вопросы
            key = str(q.get("question", ""))[:80]
            if key in seen:
                continue
            if q.get("type") == "mcq" and (not q.get("options") or q.get("correct_index") is None):
                continue
            if q.get("type") in ("short", "source") and not q.get("answer"):
                continue
            seen.add(key)
            questions.append(q)
        if user_id and user_id != "null":
            progress_service.record_activity(int(user_id))
        return jsonify({"questions": questions, "qtype": qtype, "exam_type": exam_type})
    except Exception as e:
        logger.error(f"Ошибка генерации тренировочных заданий: {e}")
        return jsonify({"error": "Не удалось сгенерировать тренировочные задания"}), 500


@app.route("/api/topics", methods=["GET"])
def api_topics():
    """API для Web App: список тем (глав) из базы знаний.

    Если передан user_id — темы фильтруются по выбранным классам пользователя.
    """
    user_id = request.args.get("user_id")
    try:
        classes = "all"
        if user_id and user_id != "null":
            classes = db.get_selected_classes(int(user_id))
        return jsonify({"topics": knowledge_service.get_topics(classes=classes)})
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
        limit = request.args.get("limit", default=2000, type=int)
        return jsonify({"events": knowledge_service.get_chronology(limit=limit)})
    except Exception as e:
        logger.error(f"Ошибка получения хронологии: {e}")
        return jsonify({"error": "Не удалось получить хронологию"}), 500


@app.route("/api/figures", methods=["GET"])
def api_figures():
    """API для Web App: исторические личности."""
    try:
        limit = request.args.get("limit", default=2000, type=int)
        return jsonify({"figures": knowledge_service.get_figures(limit=limit)})
    except Exception as e:
        logger.error(f"Ошибка получения личностей: {e}")
        return jsonify({"error": "Не удалось получить личности"}), 500


@app.route("/api/terms", methods=["GET"])
def api_terms():
    """API для Web App: термины с определениями."""
    try:
        limit = request.args.get("limit", default=2000, type=int)
        return jsonify({"terms": knowledge_service.get_terms(limit=limit)})
    except Exception as e:
        logger.error(f"Ошибка получения терминов: {e}")
        return jsonify({"error": "Не удалось получить термины"}), 500


@app.route("/api/classes", methods=["GET"])
def api_classes():
    """API для Web App: список классов с описанием и количеством чанков."""
    try:
        return jsonify({"classes": placement_service.get_classes_info()})
    except Exception as e:
        logger.error(f"Ошибка получения классов: {e}")
        return jsonify({"error": "Не удалось получить классы"}), 500


@app.route("/api/user/classes", methods=["GET", "POST"])
def api_user_classes():
    """API для Web App: получение/сохранение выбранных классов пользователя."""
    if request.method == "GET":
        user_id = request.args.get("user_id")
        if not user_id or user_id == "null":
            return jsonify({"error": "user_id required"}), 400
        try:
            selected = db.get_selected_classes(int(user_id))
            return jsonify({"classes": selected})
        except Exception as e:
            logger.error(f"Ошибка получения классов пользователя: {e}")
            return jsonify({"error": "Не удалось получить классы"}), 500

    # POST
    data = request.get_json() or {}
    user_id = data.get("user_id")
    classes = data.get("classes", "all")
    if not user_id or user_id == "null":
        return jsonify({"error": "user_id required"}), 400
    try:
        db.get_or_create_user(int(user_id))
        db.set_selected_classes(int(user_id), classes)
        return jsonify({"status": "ok", "classes": db.get_selected_classes(int(user_id))})
    except Exception as e:
        logger.error(f"Ошибка сохранения классов пользователя: {e}")
        return jsonify({"error": "Не удалось сохранить классы"}), 500


@app.route("/api/placement", methods=["GET"])
def api_placement():
    """API для Web App: генерация изначального теста уровня."""
    user_id = request.args.get("user_id")
    try:
        uid = int(user_id) if user_id and user_id != "null" else None
        test = placement_service.generate_placement_test(user_id=uid)
        return jsonify({"questions": test})
    except Exception as e:
        logger.error(f"Ошибка генерации теста уровня: {e}")
        return jsonify({"error": "Не удалось сгенерировать тест"}), 500


@app.route("/api/placement/submit", methods=["POST"])
def api_placement_submit():
    """API для Web App: проверка теста уровня и сохранение результата."""
    data = request.get_json() or {}
    user_id = data.get("user_id")
    answers = data.get("answers", [])
    if not user_id or user_id == "null":
        return jsonify({"error": "user_id required"}), 400
    if not answers:
        return jsonify({"error": "answers обязательны"}), 400
    try:
        result = placement_service.submit_placement(int(user_id), answers)
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)
    except Exception as e:
        logger.error(f"Ошибка проверки теста уровня: {e}")
        return jsonify({"error": "Не удалось проверить тест"}), 500


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
            adaptive_service.record_answer(
                uid, exam_type, question, user_answer, correct_answer, is_correct
            )
            if result["correct"]:
                progress_service.add_xp(uid, config.XP_PER_QUESTION)
                gamification_service.award_xp(uid, config.XP_PER_QUESTION)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Ошибка проверки ответа: {e}")
        return jsonify({"error": "Не удалось проверить ответ"}), 500


@app.route("/api/test", methods=["GET"])
def api_test():
    """API для Web App: генерация полноценного теста из 10 заданий."""
    user_id = request.args.get("user_id")
    try:
        classes = "all"
        if user_id and user_id != "null":
            classes = db.get_selected_classes(int(user_id))
        test = exam_service.generate_full_test(classes=classes)
        if user_id and user_id != "null":
            progress_service.record_activity(int(user_id))
        return jsonify(test)
    except Exception as e:
        logger.error(f"Ошибка генерации теста: {e}")
        return jsonify({"error": "Не удалось сгенерировать тест"}), 500


@app.route("/api/test/submit", methods=["POST"])
def api_test_submit():
    """API для Web App: проверка ответа на задание полноценного теста.

    Поддерживает все типы заданий: MCQ (выбор ответа), краткий ответ,
    развёрнутый ответ по источнику (проверка через LLM).
    """
    data = request.get_json() or {}
    user_id = data.get("user_id")
    question = data.get("question", {})
    user_answer = data.get("answer")
    if not question or user_answer is None:
        return jsonify({"error": "question и answer обязательны"}), 400
    try:
        qtype = question.get("type", "mcq")
        if qtype == "source":
            # Развёрнутый ответ по источнику — проверка через LLM
            result = exam_service.check_open_answer(
                question.get("question", ""),
                user_answer,
                question.get("answer", ""),
            )
            correct = result["correct"]
            correct_answer = question.get("answer", "")
        elif qtype == "short":
            # Краткий ответ
            correct_answer = question.get("answer") or question.get("correct_answer")
            correct = exam_service.check_ege_answer(user_answer, correct_answer)
            result = {"correct": bool(correct)}
        else:
            # MCQ — выбор ответа
            correct_index = question.get("correct_index")
            options = question.get("options", [])
            correct_answer = options[correct_index] if 0 <= correct_index < len(options) else ""
            correct = exam_service.check_oge_answer(
                question, user_answer, correct_index, options
            )
            result = {"correct": bool(correct)}

        result["correct"] = bool(correct)
        result["points"] = question.get("points", 1)
        result["earned"] = result.get("points", 1) if correct else 0
        if user_id and user_id != "null":
            uid = int(user_id)
            progress_service.record_activity(uid)
            adaptive_service.record_answer(
                uid, "test", question, user_answer, correct_answer, correct
            )
            if correct:
                progress_service.add_xp(uid, config.XP_PER_QUESTION)
                gamification_service.award_xp(uid, config.XP_PER_QUESTION)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Ошибка проверки ответа теста: {e}")
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
