"""
Modular question_manager package (was the 822-line monolith).
Public API preserved — `from src.services.question_manager import ...` and
`from src.services import question_manager; question_manager.<fn>` both work.
"""
from src.services.question_manager.data_loader import (
    load_data_files, DATA, get_file_paths, get_data_summary,
)
from src.services.question_manager.queue import (
    initialize_question_file, get_question_count, get_next_question,
    add_question, remove_first_question, archive_question, get_all_questions,
    get_question_by_id, get_archive, reset_question_queue, get_question_stats,
    get_question_count_sync, get_next_question_sync, get_all_questions_sync,
)
from src.services.question_manager.generation import (
    generate_new_question_from_data, is_duplicate_question,
    get_random_fallback_question_async, get_default_fallback_questions,
    n8n_generate_questions_with_llm,
)
from src.services.question_manager.logs import (
    log_question, get_question_logs, get_question_log_stats,
    clear_question_logs, export_question_logs,
)
