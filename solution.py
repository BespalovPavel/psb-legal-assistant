"""Обязательная точка входа solution.py для автоматической проверки на платформе."""

from __future__ import annotations

import config
import controllers
import models
import prompts


def main() -> None:
    if not config.API_BASE or not config.LLM_KEY:
        raise ValueError("Нужны переменные окружения LLM_BASE_URL и LLM_API_KEY")

    q_path = models.find_questions_file()
    questions = models.load_questions(q_path)
    controller = controllers.LegalAssistantController()

    print(
        f"[INIT] Вопросов: {len(questions)} | Документов БЗ: {len(controller.documents)} | Чанков: {len(controller.chunks)}",
        flush=True,
    )

    answers = controller.run_batch_evaluation(questions)
    prompts.save_submission_csv("submission.csv", questions, answers)
    print(f"[DONE] Создан submission.csv: {len(questions)} ответов", flush=True)


if __name__ == "__main__":
    main()