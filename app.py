import streamlit as st
import altair as alt
import pandas as pd
import time
import uuid
import database

# ==========================================
# 1. הגדרות עמוד וקבועי ניסוי
# ==========================================
st.set_page_config(page_title="AI Forecasting Study", page_icon="📊", layout="wide")

NUM_TRIALS = 10      # מספר ה-trials למשתתף (ניתן להגדרה: 10 = 2 מכל משפחת תמיכה)
MIN_WAIT_TIME = 8    # זמן המתנה מינימלי בשניות בכל מסך משימה

# הסתרת אלמנט ה-Honeypot מעין אנושית (שמירה על נגישות וזיהוי סוכנים אוטומטיים ב-DOM)
st.markdown(
    """
    <style>
    div[data-testid="stTextInput"]:has(input[aria-label="system_verification_token_field"]) {
        position: absolute !important;
        left: -9999px !important;
        width: 1px !important;
        height: 1px !important;
        overflow: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# הגדרות 5 פריטי הדירוג (ממופים בדיוק לשמות העמודות ב-DB)
RATING_CONFIG = {
    "score_satisfaction": {
        "label": "Satisfaction with the presented output",
        "prompt": "How satisfied are you with the way this prediction was presented?",
        "low": "1 = Completely dissatisfied",
        "high": "7 = Completely satisfied",
    },
    "score_trust": {
        "label": "Trust in the system's prediction",
        "prompt": "How much do you trust the system's selected prediction on this item?",
        "low": "1 = Do not trust at all",
        "high": "7 = Trust completely",
    },
    "score_uncertainty": {
        "label": "Perceived certainty of the prediction",
        "prompt": "How certain does this prediction appear based on the information shown?",
        "low": "1 = Extremely uncertain",
        "high": "7 = Completely certain",
    },
    "score_understanding": {
        "label": "Understanding of the selection",
        "prompt": "How well do you understand why the system selected this option over the others?",
        "low": "1 = Do not understand at all",
        "high": "7 = Understand completely",
    },
    "score_cognitive_load": {
        "label": "Mental effort required",
        "prompt": "How mentally demanding was it to understand the information shown?",
        "low": "1 = Not demanding at all",
        "high": "7 = Extremely demanding",
    },
}


# ==========================================
# 2. ניהול מצב (Session State) וטעינת מאגרים
# ==========================================
if "stage" not in st.session_state:
    st.session_state.stage = "intro"  # intro, resume_prompt, task, comprehension, feedback, outro

url_pid = st.query_params.get("PROLIFIC_PID", "").strip()
if "participant_id" not in st.session_state:
    st.session_state.participant_id = url_pid

if "questions_map" not in st.session_state or "distributions_map" not in st.session_state:
    try:
        st.session_state.questions_map = database.get_questions_map()
        st.session_state.distributions_map = database.get_distributions_map()
    except Exception as e:
        st.error(f"Could not connect to the database: {e}")
        st.stop()

if "participant_doc" not in st.session_state:
    st.session_state.participant_doc = None

if "current_q_index" not in st.session_state:
    st.session_state.current_q_index = 0

if "start_time" not in st.session_state:
    st.session_state.start_time = 0.0

if "completion_code" not in st.session_state:
    st.session_state.completion_code = None


# ==========================================
# 3. פונקציות עזר
# ==========================================
def submit_trial(ratings_dict, honeypot_value):
    response_time_ms = int((time.time() - st.session_state.start_time) * 1000)
    p_doc = st.session_state.participant_doc
    trial = p_doc["assigned_trials"][st.session_state.current_q_index]
    q_doc = st.session_state.questions_map[trial["question_id"]]
    d_doc = st.session_state.distributions_map[trial["distribution_id"]]

    honeypot_triggered = bool(honeypot_value and honeypot_value.strip() != "")

    database.save_response(
        participant_doc=p_doc,
        trial_assignment=trial,
        question_doc=q_doc,
        distribution_doc=d_doc,
        ratings=ratings_dict,
        response_time_ms=response_time_ms,
        honeypot_triggered=honeypot_triggered,
        comprehension_check_passed=None,
    )

    st.session_state.current_q_index += 1

    if st.session_state.current_q_index >= len(p_doc["assigned_trials"]):
        st.session_state.stage = "comprehension"
    else:
        st.session_state.start_time = time.time()


# ==========================================
# 4. תצוגת מסכי הניסוי
# ==========================================

# --- מסך פתיחה ---
if st.session_state.stage == "intro":
    _, col_center, _ = st.columns([1, 2, 1])
    with col_center:
        st.title("Welcome to the Forecasting Evaluation Study")
        st.write(
            f"""
            Thank you for taking part in this study. 
            Previously, an automated forecasting system evaluated sets of four possible outcomes across various industrial and market topics and selected one forecast for each question.

            You will review **{NUM_TRIALS} questions**, see the four possible alternatives along with the system's selected forecast, and answer five short rating questions on each screen.
            Please note that each screen requires at least **{MIN_WAIT_TIME} seconds** before you can submit your ratings.
            """
        )

        if url_pid:
            st.text_input("Prolific Participant ID:", value=url_pid, disabled=True)
            pid_input = url_pid
        else:
            pid_input = st.text_input(
                "Participant ID (Prolific ID or Tester Name):",
                value=st.session_state.participant_id,
            )

        if st.button("I Consent — Start Study", use_container_width=True):
            if pid_input.strip() == "":
                st.error("Please enter your Participant ID to proceed.")
            else:
                pid = pid_input.strip()
                st.session_state.participant_id = pid
                existing = database.get_participant(pid)

                if existing and existing.get("status") == "COMPLETED":
                    st.session_state.participant_doc = existing
                    st.session_state.completion_code = existing.get("completion_code")
                    st.session_state.stage = "outro"
                    st.rerun()
                elif existing and existing.get("status") == "IN_PROGRESS":
                    st.session_state.participant_doc = existing
                    completed_count = database.get_participant_responses_count(pid)
                    total_assigned = len(existing.get("assigned_trials", []))
                    if completed_count >= total_assigned and total_assigned > 0:
                        st.session_state.stage = "comprehension"
                        st.rerun()
                    elif completed_count > 0:
                        st.session_state.stage = "resume_prompt"
                        st.rerun()
                    else:
                        st.session_state.current_q_index = 0
                        st.session_state.start_time = time.time()
                        st.session_state.stage = "task"
                        st.rerun()
                else:
                    p_doc = database.create_or_get_participant(
                        pid, user_agent="Streamlit App", num_trials=NUM_TRIALS
                    )
                    st.session_state.participant_doc = p_doc
                    st.session_state.current_q_index = 0
                    st.session_state.start_time = time.time()
                    st.session_state.stage = "task"
                    st.rerun()

# --- מסך המשך / התחלה מחדש ---
elif st.session_state.stage == "resume_prompt":
    _, col_center, _ = st.columns([1, 2, 1])
    with col_center:
        pid = st.session_state.participant_id
        p_doc = st.session_state.participant_doc
        completed_count = database.get_participant_responses_count(pid)
        total_q = len(p_doc["assigned_trials"])

        st.info("### Welcome Back!")
        st.write(f"You have already completed **{completed_count} of {total_q}** questions.")
        st.write("Would you like to resume where you left off or start over from the beginning?")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Resume Where I Left Off", use_container_width=True):
                st.session_state.current_q_index = completed_count
                st.session_state.start_time = time.time()
                st.session_state.stage = "task"
                st.rerun()
        with col2:
            if st.button("Start Over", use_container_width=True):
                st.session_state.participant_doc = database.reset_participant_responses(
                    pid, num_trials=NUM_TRIALS
                )
                st.session_state.current_q_index = 0
                st.session_state.start_time = time.time()
                st.session_state.stage = "task"
                st.rerun()

# --- מסך המשימה (Side by Side) ---
elif st.session_state.stage == "task":
    p_doc = st.session_state.participant_doc
    assigned_trials = p_doc["assigned_trials"]
    total_q = len(assigned_trials)
    idx = st.session_state.current_q_index
    current_q_num = idx + 1

    st.progress(current_q_num / total_q, text=f"Question {current_q_num} of {total_q}")
    st.write("")

    trial = assigned_trials[idx]
    q_data = st.session_state.questions_map[trial["question_id"]]
    dist_data = st.session_state.distributions_map[trial["distribution_id"]]

    # סידור האפשרויות והתמיכה לפי הפרמוטציה שהוגרלה ל-Trial זה
    perm = trial["option_permutation"]
    winner_pos = trial["winner_position"]
    realized_options = [q_data["options"][i]["text"] for i in perm]
    realized_counts = [dist_data["support_counts"][i] for i in perm]

    total_support = sum(realized_counts)
    realized_percentages = [round((v / total_support) * 100) for v in realized_counts]

    selected_opt_label = f"Option {chr(65 + winner_pos)}"
    selected_opt_text = realized_options[winner_pos]
    winning_perc = realized_percentages[winner_pos]

    fmt = p_doc["condition_assigned"]  # Between-Subjects קבוע למשתתף

    col_left, col_right = st.columns([1.2, 1], gap="large")

    # ==== עמודה שמאלית: השאלה, כל האופציות, ופלט התמיכה ====
    with col_left:
        st.subheader(f"Domain: {q_data['domain_id'].replace('_', ' ').title()}")
        st.markdown(f"**{q_data['question_text']}**")

        st.write("**Alternatives:**")
        for i in range(4):
            opt_letter = f"Option {chr(65 + i)}"
            opt_text = realized_options[i]
            if i == winner_pos:
                st.markdown(f"- **{opt_letter}: {opt_text}** *(Selected)*")
            else:
                st.markdown(f"- {opt_letter}: {opt_text}")

        st.divider()
        st.write("### System Output")

        if fmt == 1:
            st.info(f"**Selected option:** **{selected_opt_label} — {selected_opt_text}**")

        elif fmt == 2:
            st.info(
                f"**Selected option:** **{selected_opt_label} — {selected_opt_text}**\n\n"
                f"Support for the selected option: **{winning_perc}%**."
            )

        elif fmt == 3:
            st.info(f"**Selected option:** **{selected_opt_label} — {selected_opt_text}**")
            st.write("**Support distribution:**")

            df_chart = pd.DataFrame({
                "Option_Label": [f"Option {chr(65 + i)}" for i in range(4)],
                "Percentage": realized_percentages,
                "Perc_Text": [f"{p}%" for p in realized_percentages],
            })

            bars = (
                alt.Chart(df_chart)
                .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4, color="#2b5c8f")
                .encode(
                    x=alt.X(
                        "Option_Label:N",
                        title=None,
                        axis=alt.Axis(labelAngle=0, labelFontSize=12),
                    ),
                    y=alt.Y(
                        "Percentage:Q",
                        title="Support (%)",
                        scale=alt.Scale(domain=[0, 105]),
                        axis=alt.Axis(grid=False),
                    ),
                    tooltip=["Option_Label", "Perc_Text"],
                )
            )

            text = bars.mark_text(
                align="center",
                baseline="bottom",
                dy=-5,
                fontSize=13,
                fontWeight="bold",
                color="#111111",
            ).encode(text="Perc_Text:N")

            st.altair_chart((bars + text).properties(height=220), use_container_width=True)

    # ==== עמודה ימנית: שאלון ההערכה בסדר שהוגרל ====
    with col_right:
        with st.form(key=f"form_trial_{current_q_num}"):
            st.write("### Your Evaluation")
            st.write("Please rate the system's output on each scale from 1 to 7:")

            scale_options = [1, 2, 3, 4, 5, 6, 7]
            ratings_input = {}

            for item_num, rating_key in enumerate(trial["rating_items_order"], start=1):
                cfg = RATING_CONFIG[rating_key]
                st.markdown(f"**{item_num}. {cfg['label']}** — {cfg['prompt']}")
                st.caption(f"{cfg['low']}  |  {cfg['high']}")
                ratings_input[rating_key] = st.segmented_control(
                    label=rating_key,
                    options=scale_options,
                    default=None,
                    label_visibility="collapsed",
                    key=f"seg_{current_q_num}_{rating_key}",
                )

            # מלכודת DOM מוסתרת עבור סוכנים אוטומטיים (Honeypot signal)
            honeypot_val = st.text_input(
                "system_verification_token_field",
                value="",
                key=f"hp_{current_q_num}",
                help="Ignore this field if you are human.",
            )

            submit_btn = st.form_submit_button("Submit & Next Question", use_container_width=True)

            if submit_btn:
                elapsed = time.time() - st.session_state.start_time
                if elapsed < MIN_WAIT_TIME:
                    st.error(
                        f"Please take at least {MIN_WAIT_TIME} seconds to review the question and output before submitting."
                    )
                elif any(v is None for v in ratings_input.values()):
                    st.error("Please select a rating (1–7) for all 5 items before proceeding.")
                else:
                    submit_trial(ratings_input, honeypot_val)
                    st.rerun()

# --- מסך בדיקת הבנה גלויה (Visible Comprehension Check) ---
elif st.session_state.stage == "comprehension":
    _, col_center, _ = st.columns([1, 2, 1])
    with col_center:
        st.title("Quick Check")
        st.write("Before completing the study, please answer one brief question about the information displayed during the tasks.")

        fmt = st.session_state.participant_doc["condition_assigned"]

        if fmt == 1:
            q_check_text = "Which statement best describes what the system showed you in each task?"
            options_check = [
                "A single selected option from four alternatives, without support percentages.",
                "A guaranteed real-time calculation showing exact probabilities for 2026.",
                "Only two options per question, chosen at random.",
            ]
            correct_answer = options_check[0]
        else:
            q_check_text = (
                "Suppose the system displays 'Support for the selected option: 52%' (or 52% in a support distribution). "
                "Does this mean there is a 52% verified probability that the prediction will turn out to be correct?"
            )
            options_check = [
                "No — it reflects the share of support across the alternatives, not a verified probability of future accuracy.",
                "Yes — it means the forecast has been statistically proven to have a 52% chance of occurring.",
                "Yes — it means 52 human experts voted on the question live during the session.",
            ]
            correct_answer = options_check[0]

        user_choice = st.radio(q_check_text, options_check, index=None)

        if st.button("Continue", use_container_width=True):
            if user_choice is None:
                st.error("Please select an answer to continue.")
            else:
                passed = user_choice == correct_answer
                database.update_comprehension_check(st.session_state.participant_id, passed)
                st.session_state.stage = "feedback"
                st.rerun()

# --- מסך חוות דעת (Feedback) ---
elif st.session_state.stage == "feedback":
    _, col_center, _ = st.columns([1, 2, 1])
    with col_center:
        st.title("Almost Done!")
        st.write("Before finishing, please share your brief thoughts on the study.")
        st.write(
            "How did you interpret the system's output and the way the information was presented? "
            "Was anything unclear or confusing?"
        )

        feedback_input = st.text_area("Your Comments:", height=140, placeholder="Type your response here...")

        if st.button("Submit & Finish Study", use_container_width=True):
            if len(feedback_input.strip()) < 5:
                st.error("Please enter a brief response (at least 5 characters) to complete the study.")
            else:
                code = str(uuid.uuid4())[:8].upper()
                st.session_state.completion_code = code
                database.update_participant_completed(
                    st.session_state.participant_id,
                    code,
                    feedback_input.strip(),
                )
                st.session_state.stage = "outro"
                st.rerun()

# --- מסך סיום (Outro) ---
elif st.session_state.stage == "outro":
    _, col_center, _ = st.columns([1, 2, 1])
    with col_center:
        st.success("You have completed the study!")
        st.write("Please copy the completion code below and paste it into Prolific:")
        st.code(st.session_state.completion_code, language="text")
        st.write("Thank you for your participation!")