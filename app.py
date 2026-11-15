import streamlit as st
import altair as alt
import pandas as pd
import random
import time
import uuid
import database_old

# ==========================================
# 1. הגדרות עמוד (עכשיו מוגדר כרחב - Wide)
# ==========================================
st.set_page_config(page_title="AI Decision Making Study", page_icon="🤖", layout="wide")

# ==========================================
# 2. ניהול מצב (Session State)
# ==========================================
if 'stage' not in st.session_state:
    st.session_state.stage = 'intro'  # intro, resume_prompt, task, feedback, outro

if 'participant_id' not in st.session_state:
    pid = st.query_params.get("PROLIFIC_PID", "")
    st.session_state.participant_id = pid

if 'questions' not in st.session_state:
    try:
        all_q = database.get_all_questions()
        random.shuffle(all_q)
        st.session_state.questions = all_q
    except Exception as e:
        st.error("Could not connect to the database. Please check your credentials.")
        st.stop()

if 'current_q_index' not in st.session_state:
    st.session_state.current_q_index = 0

if 'current_format' not in st.session_state:
    st.session_state.current_format = random.choice([1, 2, 3])

if 'start_time' not in st.session_state:
    st.session_state.start_time = 0

if 'completion_code' not in st.session_state:
    st.session_state.completion_code = None

if 'feedback' not in st.session_state:
    st.session_state.feedback = ""

# --- זמן המתנה חובה בכל מסך (בשניות) ---
MIN_WAIT_TIME = 8


# ==========================================
# 3. פונקציות עזר
# ==========================================
def submit_response(satisfaction, trust, uncertainty, understanding, cog_load):
    response_time = int((time.time() - st.session_state.start_time) * 1000)
    current_q = st.session_state.questions[st.session_state.current_q_index]

    response_data = {
        "participant_id": st.session_state.participant_id,
        "question_id": current_q["_id"],
        "distribution_id": current_q["assigned_distribution_id"],
        "presentation_format": st.session_state.current_format,
        "order_index": st.session_state.current_q_index + 1,
        "response_time_ms": response_time,
        "score_satisfaction": satisfaction,
        "score_trust": trust,
        "score_uncertainty": uncertainty,
        "score_understanding": understanding,
        "score_cognitive_load": cog_load
    }

    database.save_response(response_data)
    st.session_state.current_q_index += 25

    if st.session_state.current_q_index >= len(st.session_state.questions):
        st.session_state.stage = 'feedback'
    else:
        st.session_state.current_format = random.choice([1, 2, 3])
        st.session_state.start_time = time.time()


# ==========================================
# 4. תצוגת מסכי הניסוי
# ==========================================

# --- מסך פתיחה ---
if st.session_state.stage == 'intro':
    _, col_center, _ = st.columns([1, 2, 1])
    with col_center:
        st.title("Welcome to the AI Prediction Study 🤖")
        st.write("""
        Thank you for participating in this research. 
        In this study, an advanced AI system has analyzed various industrial and market trends. 
        You will be presented with 40 questions and the AI's prediction for each.
        After reviewing the AI's output, you will be asked to rate your experience.
        """)

        pid_input = st.text_input("Please enter your Prolific ID:", value=st.session_state.participant_id)

        if st.button("I Consent - Start Study", use_container_width=True):
            if pid_input.strip() == "":
                st.error("Please enter your Prolific ID to proceed.")
            else:
                pid = pid_input.strip()
                st.session_state.participant_id = pid
                existing_participant = database.get_participant(pid)

                if existing_participant and existing_participant.get("status") == "COMPLETED":
                    st.session_state.completion_code = existing_participant.get("completion_code")
                    st.session_state.stage = 'outro'
                    st.rerun()
                elif existing_participant and existing_participant.get("status") == "IN_PROGRESS":
                    completed_count = database.get_participant_responses_count(pid)
                    if completed_count > 0:
                        st.session_state.stage = 'resume_prompt'
                        st.rerun()
                    else:
                        st.session_state.current_q_index = 0
                        st.session_state.start_time = time.time()
                        st.session_state.stage = 'task'
                        st.rerun()
                else:
                    database.create_or_get_participant(pid, user_agent="Streamlit App")
                    st.session_state.current_q_index = 0
                    st.session_state.start_time = time.time()
                    st.session_state.stage = 'task'
                    st.rerun()

# --- מסך שאלת המשך ---
elif st.session_state.stage == 'resume_prompt':
    _, col_center, _ = st.columns([1, 2, 1])
    with col_center:
        pid = st.session_state.participant_id
        completed_count = database.get_participant_responses_count(pid)
        total_q = len(st.session_state.questions)

        st.info("### Welcome Back!")
        st.write(f"We noticed that you have already answered **{completed_count} out of {total_q}** questions.")
        st.write("Would you like to resume where you left off, or start over from the beginning?")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("▶️ Resume Where I Left Off", use_container_width=True):
                st.session_state.current_q_index = completed_count
                st.session_state.start_time = time.time()
                st.session_state.stage = 'task'
                st.rerun()
        with col2:
            if st.button("🔄 Start Over", use_container_width=True):
                database.reset_participant_responses(pid)
                st.session_state.current_q_index = 0
                st.session_state.start_time = time.time()
                st.session_state.stage = 'task'
                st.rerun()

# --- מסך המשימה (Side by Side) ---
elif st.session_state.stage == 'task':
    total_q = len(st.session_state.questions)
    current_q_num = st.session_state.current_q_index + 1

    st.progress(current_q_num / total_q, text=f"Question {current_q_num} of {total_q}")
    st.write("")

    col_left, col_right = st.columns([1.2, 1], gap="large")

    q_data = st.session_state.questions[st.session_state.current_q_index]
    dist_data = database.get_distribution(q_data['assigned_distribution_id'])
    options = q_data['options']

    # ==== עמודה שמאלית: השאלה ופלט ה-AI ====
    with col_left:
        st.subheader(f"Domain: {q_data['domain_id'].replace('_', ' ').title()}")
        st.markdown(f"**{q_data['question_text']}**")

        st.divider()
        st.write("### AI System Output:")

        total_votes = sum(dist_data['support_counts'])
        percentages = [round((v / total_votes) * 100) for v in dist_data['support_counts']]

        selected_opt = options[q_data['selected_option_index']]['text']
        winning_perc = percentages[0]

        fmt = st.session_state.current_format

        if fmt == 1:
            st.info(f"**The system predicts:** {selected_opt}")

        elif fmt == 2:
            st.info(
                f"**The system predicts:** {selected_opt}\n\n*(Supported by {winning_perc}% internal system consensus)*")

        elif fmt == 3:
            st.info(f"**The system predicts:** {selected_opt}")
            st.write("**Internal Consensus Distribution:**")

            df_chart = pd.DataFrame({
                'Option_Label': [f"Option {chr(65 + i)}" for i in range(4)],
                'Percentage': percentages,
                'Perc_Text': [f"{p}%" for p in percentages]
            })

            bars = alt.Chart(df_chart).mark_bar(
                cornerRadiusTopLeft=4, cornerRadiusTopRight=4, color="#1f77b4"
            ).encode(
                x=alt.X('Option_Label:N', title=None, axis=alt.Axis(labelAngle=0, labelFontSize=12)),
                y=alt.Y('Percentage:Q', title="Consensus (%)", scale=alt.Scale(domain=[0, 100]),
                        axis=alt.Axis(grid=False)),
                tooltip=['Option_Label', 'Perc_Text']
            )

            text = bars.mark_text(
                align='center', baseline='bottom', dy=-5, fontSize=13, fontWeight='bold'
            ).encode(text='Perc_Text:N')

            st.altair_chart((bars + text).properties(height=200), use_container_width=True)

            st.write("**Options:**")
            for i in range(4):
                st.markdown(f"- **Option {chr(65 + i)}:** {options[i]['text']}")

    # ==== עמודה ימנית: השאלון המעוצב ====
    with col_right:
        with st.form(key=f"form_{current_q_num}"):
            st.write("### Your Evaluation")
            st.write("Please evaluate the AI response (Select a number from 1 to 7):")

            scale_options = [1, 2, 3, 4, 5, 6, 7]

            st.markdown("**1. Satisfaction with the answer format:**")
            st.caption("👈 1 = Completely Dissatisfied | 7 = Extremely Satisfied 👉")
            q_sat = st.segmented_control("Satisfaction", scale_options, default=None, label_visibility="collapsed")

            st.markdown("**2. Perceived Trust & Professionalism:**")
            st.caption("👈 1 = Completely Unreliable | 7 = Highly Professional & Reliable 👉")
            q_trust = st.segmented_control("Trust", scale_options, default=None, label_visibility="collapsed")

            st.markdown("**3. Perceived Certainty of the AI:**")
            st.caption("👈 1 = Extremely Uncertain | 7 = Totally Confident 👉")
            q_unc = st.segmented_control("Certainty", scale_options, default=None, label_visibility="collapsed")

            st.markdown("**4. Understanding of AI's reasoning:**")
            st.caption("👈 1 = Completely Unclear | 7 = Perfectly Clear 👉")
            q_und = st.segmented_control("Understanding", scale_options, default=None, label_visibility="collapsed")

            st.markdown("**5. Cognitive Load:**")
            st.caption("👈 1 = Very Easy to Process | 7 = Extremely Heavy & Confusing 👉")
            q_cog = st.segmented_control("Cognitive Load", scale_options, default=None, label_visibility="collapsed")

            submit_btn = st.form_submit_button("Submit & Next Question", use_container_width=True)

            if submit_btn:
                elapsed = time.time() - st.session_state.start_time
                if elapsed < MIN_WAIT_TIME:
                    st.error(
                        f"Please take at least {MIN_WAIT_TIME} seconds to review the information carefully before proceeding.")
                elif None in [q_sat, q_trust, q_unc, q_und, q_cog]:
                    st.error("⚠️ Please answer all 5 questions by selecting a number before proceeding.")
                else:
                    submit_response(q_sat, q_trust, q_unc, q_und, q_cog)
                    st.rerun()

# --- מסך חוות דעת (Feedback) ---
elif st.session_state.stage == 'feedback':
    _, col_center, _ = st.columns([1, 2, 1])
    with col_center:
        st.title("Almost Done! 📝")
        st.write("Before we finish, please share your thoughts regarding the study.")
        st.write(
            "How did you feel about the AI's predictions and the way the information was presented? Did you notice anything specific?")

        feedback_input = st.text_area("Your Feedback:", height=150, placeholder="Type your thoughts here...")

        if st.button("Submit & Finish Study", use_container_width=True):
            if len(feedback_input.strip()) < 5:
                st.error("Please provide at least a brief feedback to complete the study.")
            else:
                st.session_state.feedback = feedback_input.strip()
                st.session_state.stage = 'outro'
                st.rerun()

# --- מסך סיום (Outro) ---
elif st.session_state.stage == 'outro':
    _, col_center, _ = st.columns([1, 2, 1])
    with col_center:
        st.success("🎉 You have completed the study!")

        if not st.session_state.completion_code:
            code = str(uuid.uuid4())[:8].upper()
            st.session_state.completion_code = code
            database.update_participant_completed(
                st.session_state.participant_id,
                code,
                st.session_state.feedback
            )

        st.write("Please copy the completion code below and paste it back in Prolific to receive your payment:")
        st.code(st.session_state.completion_code, language="text")
        st.write("Thank you for your participation!")