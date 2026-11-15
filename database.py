import os
import random
from datetime import datetime, timezone
from pymongo import MongoClient
from dotenv import load_dotenv
import streamlit as st

try:
    import certifi
    CA_FILE = certifi.where()
except ImportError:
    CA_FILE = None

load_dotenv()


MONGO_URI = os.getenv("MONGO_URI") or st.secrets.get("MONGO_URI")
if not MONGO_URI:
    raise ValueError("MONGO_URI is missing. Check your .env file or Streamlit Secrets.")


client_kwargs = {"tlsCAFile": CA_FILE} if CA_FILE else {}
client = MongoClient(MONGO_URI, **client_kwargs)
db = client["thesis_study"]

RATING_KEYS = [
    "score_satisfaction",
    "score_trust",
    "score_uncertainty",
    "score_understanding",
    "score_cognitive_load",
]


def get_questions_map():
    """מחזיר מילון של כל השאלות לפי _id לשליפה מהירה."""
    return {q["_id"]: q for q in db.questions.find({})}


def get_distributions_map():
    """מחזיר מילון של כל התפלגויות התמיכה לפי _id לשליפה מהירה."""
    return {d["_id"]: d for d in db.support_distributions.find({})}


def build_assigned_trials(num_trials=10):
    """
    בונה רצף מאוזן של trials עבור משתתף:
    - דגימה מאוזנת מ-5 משפחות התמיכה (למשל 2 מכל משפחה עבור 10 trials)
    - צימוד אקראי לשאלות מתוך המאגר (ללא שידוך קבוע)
    - פרמוטציה אקראית למיקום אפשרויות A/B/C/D כך שהמנצח לא יהיה תמיד ראשון
    - ערבוב סדר הצגת 5 פריטי הדירוג
    """
    all_questions = list(db.questions.find({}))
    all_distributions = list(db.support_distributions.find({}))

    by_family = {}
    for dist in all_distributions:
        by_family.setdefault(dist["family_type"], []).append(dist)

    num_families = len(by_family)
    per_family = max(1, num_trials // num_families)

    selected_dists = []
    for family_name, dist_list in by_family.items():
        selected_dists.extend(random.sample(dist_list, min(per_family, len(dist_list))))

    # השלמה אם num_trials אינו מתחלק ב-5
    if len(selected_dists) < num_trials:
        remaining = [d for d in all_distributions if d not in selected_dists]
        selected_dists.extend(random.sample(remaining, num_trials - len(selected_dists)))

    random.shuffle(selected_dists)
    selected_questions = random.sample(all_questions, len(selected_dists))

    assigned_trials = []
    for idx, (q, d) in enumerate(zip(selected_questions, selected_dists), start=1):
        perm = [0, 1, 2, 3]
        random.shuffle(perm)
        winner_pos = perm.index(int(q["selected_option_index"]))

        rating_order = RATING_KEYS.copy()
        random.shuffle(rating_order)

        assigned_trials.append({
            "trial_index": int(idx),
            "question_id": str(q["_id"]),
            "distribution_id": str(d["_id"]),
            "family_type": str(d["family_type"]),
            "option_permutation": [int(x) for x in perm],
            "winner_position": int(winner_pos),
            "rating_items_order": rating_order,
        })

    return assigned_trials


def get_participant(prolific_id):
    return db.participants.find_one({"_id": prolific_id})


def create_or_get_participant(prolific_id, user_agent="Streamlit App", num_trials=10):
    """
    יוצר משתתף חדש עם הגרלה חד-פעמית של condition_assigned (Between-Subjects)
    ורצף assigned_trials קבוע, או מחזיר משתתף קיים במקרה של רענון דף.
    """
    existing = get_participant(prolific_id)
    if existing:
        return existing

    participant_doc = {
        "_id": str(prolific_id),
        "condition_assigned": int(random.choice([1, 2, 3])),
        "assigned_trials": build_assigned_trials(num_trials=num_trials),
        "status": "IN_PROGRESS",
        "started_at": datetime.now(timezone.utc),
        "completed_at": None,
        "user_agent": str(user_agent),
        "completion_code": None,
        "feedback": None,
    }

    db.participants.insert_one(participant_doc)
    return participant_doc


def get_participant_responses_count(prolific_id):
    return db.responses.count_documents({"participant_id": prolific_id})


def reset_participant_responses(prolific_id, num_trials=10):
    """מאפס תשובות קודמות ובונה רצף trials חדש אם המשתתף בחר להתחיל מהתחלה."""
    db.responses.delete_many({"participant_id": prolific_id})
    new_trials = build_assigned_trials(num_trials=num_trials)

    db.participants.update_one(
        {"_id": prolific_id},
        {
            "$set": {
                "assigned_trials": new_trials,
                "status": "IN_PROGRESS",
                "started_at": datetime.now(timezone.utc),
                "completed_at": None,
                "completion_code": None,
                "feedback": None,
            }
        },
    )
    return get_participant(prolific_id)


def save_response(
    participant_doc,
    trial_assignment,
    question_doc,
    distribution_doc,
    ratings,
    response_time_ms,
    honeypot_triggered=False,
    comprehension_check_passed=None,
    fast_threshold_ms=4000,
):
    """
    שומר רשומת תשובה מלאה הכוללת גם מזהים וגם Realized Values / Snapshots
    לצורך שחזור מלא מה-DB בלבד.
    """
    perm = trial_assignment["option_permutation"]
    raw_options = [opt["text"] for opt in question_doc["options"]]
    options_order_realized = [str(raw_options[i]) for i in perm]

    support_vector_original = [int(v) for v in distribution_doc["support_counts"]]
    support_vector_realized = [int(support_vector_original[i]) for i in perm]

    winner_pos = int(trial_assignment["winner_position"])
    selected_option_text = options_order_realized[winner_pos]

    response_doc = {
        "participant_id": str(participant_doc["_id"]),
        "question_id": str(question_doc["_id"]),
        "distribution_id": str(distribution_doc["_id"]),
        "family_type": str(distribution_doc["family_type"]),
        "presentation_format": int(participant_doc["condition_assigned"]),
        "order_index": int(trial_assignment["trial_index"]),
        "question_text_snapshot": str(question_doc["question_text"]),
        "support_vector_original": support_vector_original,
        "support_vector_realized": support_vector_realized,
        "options_order_realized": options_order_realized,
        "selected_option_text": str(selected_option_text),
        "winner_position_realized": winner_pos,
        "rating_items_order_realized": [str(k) for k in trial_assignment["rating_items_order"]],
        "response_time_ms": int(response_time_ms),
        "score_satisfaction": int(ratings["score_satisfaction"]),
        "score_trust": int(ratings["score_trust"]),
        "score_uncertainty": int(ratings["score_uncertainty"]),
        "score_understanding": int(ratings["score_understanding"]),
        "score_cognitive_load": int(ratings["score_cognitive_load"]),
        "quality_flags": {
            "fast_response_flag": bool(response_time_ms < fast_threshold_ms),
            "honeypot_triggered": bool(honeypot_triggered),
            "comprehension_check_passed": comprehension_check_passed,
        },
        "submitted_at": datetime.now(timezone.utc),
    }

    db.responses.insert_one(response_doc)


def update_comprehension_check(prolific_id, passed: bool):
    """מעדכן את תוצאת בדיקת ההבנה הגלויה בכל רשומות המשתתף."""
    db.responses.update_many(
        {"participant_id": str(prolific_id)},
        {"$set": {"quality_flags.comprehension_check_passed": bool(passed)}},
    )


def update_participant_completed(prolific_id, completion_code, feedback_text=""):
    """מעדכן סטטוס COMPLETED, קוד סיום ופידבק מיד עם שליחת טופס הסיום."""
    db.participants.update_one(
        {"_id": str(prolific_id)},
        {
            "$set": {
                "status": "COMPLETED",
                "completed_at": datetime.now(timezone.utc),
                "completion_code": str(completion_code),
                "feedback": str(feedback_text),
            }
        },
    )