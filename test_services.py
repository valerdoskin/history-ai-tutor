"""
Тесты для сервисов приложения History AI Tutor.
Запуск: python3 test_services.py
"""

import os
import sys
import tempfile
import unittest

# Используем временную БД для тестов
os.environ["DB_PATH"] = "/tmp/test_tutor_services.db"

import config
from database import Database, db


class TestDatabase(unittest.TestCase):
    def setUp(self):
        if os.path.exists("/tmp/test_tutor_services.db"):
            os.remove("/tmp/test_tutor_services.db")
        self.db = Database(db_path="/tmp/test_tutor_services.db")

    def tearDown(self):
        if os.path.exists("/tmp/test_tutor_services.db"):
            os.remove("/tmp/test_tutor_services.db")

    def test_get_or_create_user(self):
        user = self.db.get_or_create_user(1, "test", "Тест")
        self.assertEqual(user["user_id"], 1)
        self.assertEqual(user["username"], "test")
        self.assertEqual(user["level"], 1)
        self.assertEqual(user["xp"], 0)

    def test_add_xp(self):
        self.db.get_or_create_user(1)
        level = self.db.add_xp(1, 100)
        self.assertEqual(level, 2)
        user = self.db.get_or_create_user(1)
        self.assertEqual(user["xp"], 100)

    def test_update_progress(self):
        self.db.get_or_create_user(1)
        self.db.update_progress(1, "book1", "1", "Параграф 1", "completed", 100)
        progress = self.db.get_progress(1)
        self.assertEqual(len(progress), 1)
        self.assertEqual(progress[0]["status"], "completed")

    def test_unlock_achievement(self):
        self.db.get_or_create_user(1)
        self.db.unlock_achievement(1, "first_lesson")
        achievements = self.db.get_achievements(1)
        self.assertIn("first_lesson", achievements)

    def test_add_message(self):
        self.db.get_or_create_user(1)
        self.db.add_message(1, "user", "Привет")
        self.db.add_message(1, "assistant", "Здравствуй!")
        history = self.db.get_history(1)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")

    def test_add_exam_result(self):
        self.db.get_or_create_user(1)
        self.db.add_exam_result(1, "oge", "Вопрос?", "Ответ", "Правильный", 0, "Тема 1")
        weak = self.db.get_weak_topics(1)
        self.assertEqual(len(weak), 1)
        self.assertEqual(weak[0]["topic"], "Тема 1")

    def test_get_stats(self):
        self.db.get_or_create_user(1)
        self.db.add_exam_result(1, "oge", "Вопрос?", "Ответ", "Правильный", 0, "Тема 1")
        stats = self.db.get_stats(1)
        self.assertEqual(stats["total_questions"], 1)
        self.assertEqual(stats["correct_questions"], 0)


class TestGamification(unittest.TestCase):
    def setUp(self):
        if os.path.exists("/tmp/test_tutor_services.db"):
            os.remove("/tmp/test_tutor_services.db")
        self.db = Database(db_path="/tmp/test_tutor_services.db")
        self.db.get_or_create_user(1)

    def tearDown(self):
        if os.path.exists("/tmp/test_tutor_services.db"):
            os.remove("/tmp/test_tutor_services.db")

    def test_get_rank(self):
        from services import gamification_service
        self.assertEqual(gamification_service.get_rank(1), "Новичок")
        self.assertEqual(gamification_service.get_rank(3), "Ученик")
        self.assertEqual(gamification_service.get_rank(5), "Знаток")
        self.assertEqual(gamification_service.get_rank(8), "Эксперт")
        self.assertEqual(gamification_service.get_rank(12), "Мастер истории")
        self.assertEqual(gamification_service.get_rank(16), "Легенда")

    def test_award_xp(self):
        from services import gamification_service
        level = gamification_service.award_xp(1, 100)
        self.assertEqual(level, 2)


class TestAdaptive(unittest.TestCase):
    def setUp(self):
        if os.path.exists("/tmp/test_tutor_services.db"):
            os.remove("/tmp/test_tutor_services.db")
        self.db = Database(db_path="/tmp/test_tutor_services.db")
        self.db.get_or_create_user(1)

    def tearDown(self):
        if os.path.exists("/tmp/test_tutor_services.db"):
            os.remove("/tmp/test_tutor_services.db")

    def test_estimate_level_new_user(self):
        from services import adaptive_service
        level = adaptive_service.estimate_level(1)
        self.assertEqual(level, 1)

    def test_get_difficulty(self):
        from services import adaptive_service
        diff = adaptive_service.get_difficulty(1)
        self.assertEqual(diff, "easy")

    def test_personalize_prompt(self):
        from services import adaptive_service
        prompt = adaptive_service.personalize_prompt(1)
        self.assertIn("Уровень ученика", prompt)

    def test_add_and_get_daily_cards(self):
        from services import adaptive_service
        adaptive_service.add_card(1, "Тема 1", "Вопрос?", "Ответ")
        cards = adaptive_service.get_daily_cards(1)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["topic"], "Тема 1")

    def test_review_card_sm2(self):
        from services import adaptive_service
        adaptive_service.add_card(1, "Тема 1", "Вопрос?", "Ответ")
        cards = adaptive_service.get_daily_cards(1)
        card_id = cards[0]["id"]
        result = adaptive_service.review_card(card_id, 5)
        self.assertTrue(result["passed"])
        self.assertEqual(result["next_interval_days"], 1)
        # Повторный успешный ответ — интервал растёт
        result2 = adaptive_service.review_card(card_id, 5)
        self.assertEqual(result2["next_interval_days"], 6)

    def test_review_card_fail_resets(self):
        from services import adaptive_service
        adaptive_service.add_card(1, "Тема 1", "Вопрос?", "Ответ")
        cards = adaptive_service.get_daily_cards(1)
        card_id = cards[0]["id"]
        adaptive_service.review_card(card_id, 5)
        result = adaptive_service.review_card(card_id, 1)
        self.assertFalse(result["passed"])
        self.assertEqual(result["next_interval_days"], 1)

    def test_srs_summary(self):
        from services import adaptive_service
        adaptive_service.add_card(1, "Тема 1", "Вопрос?", "Ответ")
        summary = adaptive_service.get_srs_summary(1)
        self.assertEqual(summary["total_cards"], 1)
        self.assertEqual(summary["due_cards"], 1)


class TestRAGBuildContext(unittest.TestCase):
    def test_build_context(self):
        from services import rag_service
        chunks = [
            {"text": "Текст чанка 1", "book": "Книга 1", "chapter": "Глава 1", "paragraph": "Параграф 1"},
            {"text": "Текст чанка 2", "book": "Книга 1", "chapter": "Глава 1", "paragraph": "Параграф 2"},
        ]
        context = rag_service.build_context(chunks)
        self.assertIn("Чанк 1", context)
        self.assertIn("Книга 1", context)
        self.assertIn("Текст чанка 1", context)

    def test_build_context_max_chars(self):
        from services import rag_service
        chunks = [
            {"text": "A" * 5000, "book": "Книга 1"},
            {"text": "B" * 5000, "book": "Книга 2"},
        ]
        context = rag_service.build_context(chunks, max_chars=6000)
        self.assertLess(len(context), 6000)


class TestExamService(unittest.TestCase):
    def test_check_oge_answer(self):
        from services import exam_service
        options = ["А", "Б", "В", "Г"]
        self.assertTrue(exam_service.check_oge_answer("Вопрос", "2", 1, options))
        self.assertFalse(exam_service.check_oge_answer("Вопрос", "1", 1, options))

    def test_check_ege_answer(self):
        from services import exam_service
        self.assertTrue(exam_service.check_ege_answer("Иван Грозный", "иван грозный"))
        self.assertFalse(exam_service.check_ege_answer("Пётр", "Иван"))


class TestTutorService(unittest.TestCase):
    def test_check_answer(self):
        from services import tutor_service
        result = tutor_service.check_answer("Вопрос", "Ответ", "Ответ", "Пояснение")
        self.assertTrue(result["correct"])
        result = tutor_service.check_answer("Вопрос", "Неверно", "Ответ", "Пояснение")
        self.assertFalse(result["correct"])


class TestSelectedClasses(unittest.TestCase):
    def setUp(self):
        if os.path.exists("/tmp/test_tutor_services.db"):
            os.remove("/tmp/test_tutor_services.db")
        self.db = Database(db_path="/tmp/test_tutor_services.db")

    def tearDown(self):
        if os.path.exists("/tmp/test_tutor_services.db"):
            os.remove("/tmp/test_tutor_services.db")

    def test_default_selected_classes(self):
        self.db.get_or_create_user(1)
        self.assertEqual(self.db.get_selected_classes(1), "all")

    def test_set_selected_classes(self):
        self.db.get_or_create_user(1)
        self.db.set_selected_classes(1, "5,6,7")
        self.assertEqual(self.db.get_selected_classes(1), "5,6,7")

    def test_set_selected_classes_all(self):
        self.db.get_or_create_user(1)
        self.db.set_selected_classes(1, "all")
        self.assertEqual(self.db.get_selected_classes(1), "all")

    def test_save_placement_result(self):
        self.db.get_or_create_user(1)
        self.db.save_placement_result(1, 8, 10, 4)
        result = self.db.get_placement_result(1)
        self.assertEqual(result["score"], 8)
        self.assertEqual(result["total"], 10)
        self.assertEqual(result["level"], 4)


class TestPlacementService(unittest.TestCase):
    def setUp(self):
        if os.path.exists("/tmp/test_tutor_services.db"):
            os.remove("/tmp/test_tutor_services.db")
        self.db = Database(db_path="/tmp/test_tutor_services.db")

    def tearDown(self):
        if os.path.exists("/tmp/test_tutor_services.db"):
            os.remove("/tmp/test_tutor_services.db")

    def test_get_classes_info(self):
        from services import placement_service
        info = placement_service.get_classes_info()
        self.assertEqual(len(info), 7)
        classes = [c["class"] for c in info]
        self.assertEqual(classes, [5, 6, 7, 8, 9, 10, 11])
        for c in info:
            self.assertTrue(c["description"])

    def test_get_class_from_source(self):
        from services import placement_service
        self.assertEqual(placement_service.get_class_from_source("5_klass.docx"), 5)
        self.assertEqual(placement_service.get_class_from_source("6_klass.docx"), 6)
        self.assertEqual(placement_service.get_class_from_source("7_klass.docx"), 7)
        self.assertEqual(placement_service.get_class_from_source("8_klass.docx"), 8)
        self.assertEqual(placement_service.get_class_from_source("9_klass.docx"), 9)
        self.assertEqual(placement_service.get_class_from_source("Vseobschaya_10.docx"), 10)
        self.assertIsNone(placement_service.get_class_from_source("unknown.docx"))

    def test_generate_placement_test(self):
        from services import placement_service
        self.db.get_or_create_user(1)
        test = placement_service.generate_placement_test(user_id=1, num_questions=10)
        self.assertEqual(len(test), 10)
        for q in test:
            self.assertIn("question", q)
            self.assertIn("options", q)
            self.assertIn("correct_index", q)
            self.assertIn("class", q)
            self.assertGreaterEqual(len(q["options"]), 2)

    def test_submit_placement_all_correct(self):
        from services import placement_service
        self.db.get_or_create_user(1)
        test = placement_service.generate_placement_test(user_id=1, num_questions=10)
        answers = [{"question_id": q["id"], "answer_index": q["correct_index"]} for q in test]
        result = placement_service.submit_placement(1, answers)
        self.assertEqual(result["score"], 10)
        self.assertEqual(result["total"], 10)
        self.assertEqual(result["level"], 5)
        self.assertEqual(result["rank"], "Эксперт")

    def test_submit_placement_all_wrong(self):
        from services import placement_service
        self.db.get_or_create_user(1)
        test = placement_service.generate_placement_test(user_id=1, num_questions=10)
        answers = [
            {"question_id": q["id"], "answer_index": (q["correct_index"] + 1) % len(q["options"])}
            for q in test
        ]
        result = placement_service.submit_placement(1, answers)
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["level"], 1)
        self.assertEqual(result["rank"], "Новичок")


if __name__ == "__main__":
    unittest.main(verbosity=2)
