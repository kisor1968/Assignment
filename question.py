import streamlit as st
import json
from pathlib import Path
import pypdf
import re
import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image
import platform
from datetime import datetime

# --- CROSS-PLATFORM TESSERACT CONFIGURATION ---
if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Bridge Course Assessment & Grading Engine",
    page_icon="📝",
    layout="centered"
)

# --- ABSOLUTE PATH SETUP ---
BASE_DIR = Path(__file__).resolve().parent
JSON_FILE_PATH = BASE_DIR / "question.json"
SUBMISSIONS_FILE_PATH = BASE_DIR / "submissions.json"

# Hybrid starter questions demonstration
DEFAULT_QUESTIONS = [
    {
        "id": 1,
        "type": "mcq",
        "question": "What is the SI unit of electric charge?",
        "options": ["Ampere", "Coulomb", "Volt", "Ohm"],
        "answer": "Coulomb"
    },
    {
        "id": 2,
        "type": "short",
        "question": "State Newton's First Law of Motion in one or two sentences.",
        "options": [],
        "answer": "An object remains at rest or in uniform motion unless acted upon by an external net force."
    },
    {
        "id": 3,
        "type": "long",
        "question": "Derive the expression for the work done by an ideal gas during an isothermal expansion.",
        "options": [],
        "answer": "Key points to include: $W = \\int P dV$, using ideal gas equation $P = nRT/V$, yielding $W = nRT \\ln(V_2/V_1)$."
    }
]

def load_questions():
    if not JSON_FILE_PATH.exists() or JSON_FILE_PATH.stat().st_size == 0:
        with open(JSON_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_QUESTIONS, f, indent=4, ensure_ascii=False)
    try:
        with open(JSON_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

def load_submissions():
    if not SUBMISSIONS_FILE_PATH.exists() or SUBMISSIONS_FILE_PATH.stat().st_size == 0:
        with open(SUBMISSIONS_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump([], f, indent=4, ensure_ascii=False)
    try:
        with open(SUBMISSIONS_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

def save_submission(student_name, user_responses, mcq_score, total_mcq):
    submissions = load_submissions()
    sub_id = f"SUB-{len(submissions) + 1:03d}"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    new_sub = {
        "submission_id": sub_id,
        "student_name": student_name if student_name.strip() else "Anonymous Student",
        "timestamp": timestamp,
        "mcq_score": mcq_score,
        "total_mcq": total_mcq,
        "responses": user_responses,
        "manual_marks": {},
        "teacher_remarks": {},
        "evaluated": False
    }
    
    submissions.append(new_sub)
    with open(SUBMISSIONS_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(submissions, f, indent=4, ensure_ascii=False)
    return sub_id

tab_quiz, tab_creator, tab_eval = st.tabs([
    "📝 Take Assessment", 
    "✍️ Teacher Question Creator", 
    "👨‍🏫 Teacher Evaluation Dashboard"
])

# =====================================================================
# TAB 1: TAKE ASSESSMENT
# =====================================================================
with tab_quiz:
    st.title("🌉 Bridge Course Online Assessment Engine")
    st.subheader("Department of Physics — Interactive Assessment")
    st.markdown("---")

    questions = load_questions()

    if not questions:
        st.warning("No questions found in the question bank yet! Switch to the **Teacher Question Creator** tab to add or import questions.")
    else:
        if "submitted" not in st.session_state:
            st.session_state["submitted"] = False
        if "user_answers" not in st.session_state:
            st.session_state["user_answers"] = {}
        if "score" not in st.session_state:
            st.session_state["score"] = 0
        if "last_sub_id" not in st.session_state:
            st.session_state["last_sub_id"] = None

        if not st.session_state["submitted"]:
            student_name = st.text_input("Enter Student Name / Roll Number", placeholder="e.g. Rahul Sharma (Roll: 102)", key="student_id_input")
            st.markdown("<br>", unsafe_allow_html=True)
            
            with st.form("bridge_quiz_form"):
                user_responses = {}
                for idx, q in enumerate(questions, start=1):
                    q_type = q.get("type", "mcq")
                    st.markdown(f"#### **Q{idx}. {q['question']}**")
                    
                    if q_type == "mcq":
                        user_responses[q["id"]] = st.radio(
                            label=f"Choose answer for Q{idx}",
                            options=q.get("options", []),
                            index=None,
                            key=f"q_{q['id']}",
                            label_visibility="collapsed"
                        )
                    elif q_type == "short":
                        user_responses[q["id"]] = st.text_input(
                            label=f"Short answer for Q{idx}",
                            placeholder="Type your concise answer here...",
                            key=f"q_{q['id']}",
                            label_visibility="collapsed"
                        )
                    elif q_type == "long":
                        user_responses[q["id"]] = st.text_area(
                            label=f"Detailed answer for Q{idx}",
                            placeholder="Write your detailed explanation / steps here...",
                            key=f"q_{q['id']}",
                            label_visibility="collapsed"
                        )
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                submit_btn = st.form_submit_button("🚀 Submit Assessment", use_container_width=True)
                
                if submit_btn:
                    unanswered = [
                        q["id"] for q in questions 
                        if user_responses[q["id"]] is None or str(user_responses[q["id"]]).strip() == ""
                    ]
                    if unanswered:
                        st.warning(f"Please attempt all questions before submitting! ({len(unanswered)} remaining)")
                    else:
                        mcq_questions = [q for q in questions if q.get("type", "mcq") == "mcq"]
                        mcq_correct = sum(
                            1 for q in mcq_questions if user_responses[q["id"]] == q.get("answer")
                        )
                        
                        sub_id = save_submission(student_name, user_responses, mcq_correct, len(mcq_questions))
                        
                        st.session_state["user_answers"] = user_responses
                        st.session_state["score"] = mcq_correct
                        st.session_state["last_sub_id"] = sub_id
                        st.session_state["submitted"] = True
                        st.rerun()
        else:
            mcq_questions = [q for q in questions if q.get("type", "mcq") == "mcq"]
            total_mcq = len(mcq_questions)
            score = st.session_state["score"]
            percentage = int((score / total_mcq) * 100) if total_mcq > 0 else 0
            
            st.success(f"🎉 Assessment Submitted Successfully! Reference ID: **{st.session_state['last_sub_id']}**")
            st.markdown("## 📊 Submission Summary")
            
            if total_mcq > 0:
                c1, c2, c3 = st.columns(3)
                with c1: st.metric("MCQ Score", f"{score} / {total_mcq}")
                with c2: st.metric("MCQ Percentage", f"{percentage}%")
                with c3: st.metric("MCQ Status", "PASSED ✅" if percentage >= 50 else "NEEDS REVIEW ⚠️")
            
            st.info("ℹ️ Your subjective/descriptive responses have been logged for faculty evaluation.")
            st.markdown("---")
            st.markdown("### 🔍 Submission Copy & Answer Key")
            
            user_ans = st.session_state["user_answers"]
            for idx, q in enumerate(questions, start=1):
                selected = user_ans.get(q["id"], "")
                model_ans = q.get("answer", "")
                q_type = q.get("type", "mcq")
                
                st.markdown(f"**Q{idx}. {q['question']}**")
                st.caption(f"Type: **{q_type.upper()}**")
                
                if q_type == "mcq":
                    is_correct = selected == model_ans
                    if is_correct:
                        st.success(f"Your Answer: **{selected}** (Correct ✅)")
                    else:
                        st.error(f"Your Answer: **{selected}** (Incorrect ❌) | Correct: **{model_ans}**")
                else:
                    st.info(f"**Your Submitted Response:**\n\n>{selected}")
                    with st.expander("📖 View Model Answer / Grading Key"):
                        st.write(model_ans)
                st.markdown("---")

            if st.button("🔄 Take Another Assessment", use_container_width=True):
                st.session_state["submitted"] = False
                st.session_state["user_answers"] = {}
                st.session_state["score"] = 0
                st.session_state["last_sub_id"] = None
                st.rerun()

# =====================================================================
# TAB 2: TEACHER QUESTION CREATOR & OCR IMPORTER
# =====================================================================
with tab_creator:
    st.markdown("### ✍️ Teacher Question Creator & Flexible Importer")
    st.markdown("---")

    if "form_success" in st.session_state:
        st.success(st.session_state["form_success"])
        del st.session_state["form_success"]

    st.markdown("#### ➕ Add New Question")
    q_type_choice = st.selectbox(
        "Select Question Type", 
        ["Multiple Choice (MCQ)", "Short Answer Type", "Long Answer / Descriptive Type"],
        key="teacher_q_type"
    )
    
    new_q_text = st.text_area("Question Prompt", placeholder="Enter your question text or problem statement here...", key="q_prompt_input")
    
    valid_options = []
    correct_ans = ""
    
    if q_type_choice == "Multiple Choice (MCQ)":
        q_type_code = "mcq"
        c1, c2 = st.columns(2)
        with c1:
            opt1 = st.text_input("Option A", key="opt_a")
            opt2 = st.text_input("Option B", key="opt_b")
        with c2:
            opt3 = st.text_input("Option C", key="opt_c")
            opt4 = st.text_input("Option D", key="opt_d")
            
        valid_options = [o.strip() for o in [opt1, opt2, opt3, opt4] if o.strip()]
        
        if valid_options:
            correct_ans = st.selectbox("Select Correct Option", options=valid_options, key="correct_opt_select")
        else:
            st.info("💡 Type at least 2 options above to activate the correct answer selector.")
            
    elif q_type_choice == "Short Answer Type":
        q_type_code = "short"
        correct_ans = st.text_input("Model Answer / Key Words", placeholder="e.g., Energy / Force / Standard definition", key="short_ans_input")
        
    else:
        q_type_code = "long"
        correct_ans = st.text_area("Model Solution / Evaluation Guidelines", placeholder="Provide step-by-step solution or grading criteria...", key="long_ans_input")

    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("💾 Save Question to Bank", use_container_width=True, type="primary"):
        if not new_q_text.strip():
            st.error("Question prompt cannot be empty!")
        elif q_type_code == "mcq" and len(valid_options) < 2:
            st.error("Multiple-choice questions require at least 2 valid options.")
        elif q_type_code == "mcq" and not correct_ans:
            st.error("Please select a valid correct answer option.")
        else:
            current_q = load_questions()
            new_id = max([q.get("id", 0) for q in current_q], default=0) + 1
            
            new_entry = {
                "id": new_id,
                "type": q_type_code,
                "question": new_q_text.strip(),
                "options": valid_options if q_type_code == "mcq" else [],
                "answer": correct_ans.strip()
            }
            
            current_q.append(new_entry)
            with open(JSON_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(current_q, f, indent=4, ensure_ascii=False)
                
            st.session_state["form_success"] = f"Successfully added [{q_type_code.upper()}] Question #{new_id}!"
            st.rerun()

    st.markdown("---")
    st.markdown("#### 📄 Smart PDF / Scanned Image Importer")
    st.caption("Upload question papers (`.pdf`, `.png`, `.jpg`). The system automatically detects whether questions are MCQs or subjective tasks.")
    
    uploaded_file = st.file_uploader("Upload Question Paper", type=["pdf", "png", "jpg", "jpeg"])
    
    if uploaded_file is not None:
        if st.button("🚀 Process & Import Questions", use_container_width=True):
            with st.spinner("Extracting and analyzing text..."):
                try:
                    full_text = ""
                    file_bytes = uploaded_file.read()
                    
                    if uploaded_file.type == "application/pdf":
                        reader = pypdf.PdfReader(uploaded_file)
                        for page in reader.pages:
                            t = page.extract_text()
                            if t: full_text += t + "\n"
                        
                        if not full_text.strip():
                            images = convert_from_bytes(file_bytes)
                            for img in images:
                                full_text += pytesseract.image_to_string(img) + "\n"
                    else:
                        img = Image.open(uploaded_file)
                        full_text = pytesseract.image_to_string(img)
                    
                    if not full_text.strip():
                        st.error("OCR could not extract readable text from this file.")
                    else:
                        raw_questions = re.split(r'\n\s*(?=\d+[\.\)]\s)', full_text)
                        current_q_bank = load_questions()
                        added_count = 0
                        
                        for rq in raw_questions:
                            if not rq.strip(): continue
                            lines = [l.strip() for l in rq.split('\n') if l.strip()]
                            
                            if lines:
                                q_text = re.sub(r'^\d+[\.\)]\s*', '', lines[0])
                                potential_opts = [l for l in lines[1:] if re.match(r'^\(?[A-Da-d]\)[\.\s]', l)]
                                
                                if len(potential_opts) >= 2:
                                    q_type = "mcq"
                                    opts = [re.sub(r'^\(?[A-Da-d]\)[\.\s]*', '', o) for o in potential_opts]
                                    ans = opts[0]
                                else:
                                    q_type = "long" if len(lines) > 2 else "short"
                                    opts = []
                                    ans = "\n".join(lines[1:]) if len(lines) > 1 else "Refer to textbook/notes."
                                    if len(lines) > 1:
                                        q_text += "\n" + "\n".join(lines[1:])
                                
                                new_id = max([q.get("id", 0) for q in current_q_bank], default=0) + 1
                                current_q_bank.append({
                                    "id": new_id,
                                    "type": q_type,
                                    "question": q_text,
                                    "options": opts,
                                    "answer": ans
                                })
                                added_count += 1
                        
                        with open(JSON_FILE_PATH, "w", encoding="utf-8") as f:
                            json.dump(current_q_bank, f, indent=4, ensure_ascii=False)
                        
                        st.session_state["form_success"] = f"Successfully imported {added_count} hybrid questions!"
                        st.rerun()
                except Exception as e:
                    st.error(f"Import Error: {e}")

    st.markdown("---")
    st.markdown("#### ⚙️ Question Bank Management")
    st.caption("Clear existing records to start a fresh question bank.")
    
    if st.button("🗑️ Clear & Reset Entire Question Bank", type="secondary", use_container_width=True):
        with open(JSON_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump([], f, indent=4, ensure_ascii=False)
        st.session_state["form_success"] = "Question bank has been completely cleared and reset!"
        st.rerun()

# =====================================================================
# TAB 3: TEACHER EVALUATION & GRADING DASHBOARD
# =====================================================================
with tab_eval:
    st.markdown("### 👨‍🏫 Subjective Answer Evaluation & Grading Dashboard")
    st.caption("Review student submissions, assign manual marks for short/long answers, and record faculty feedback.")
    st.markdown("---")

    submissions = load_submissions()
    questions = load_questions()
    q_dict = {q["id"]: q for q in questions}

    if not submissions:
        st.info("No student submissions logged yet.")
    else:
        # Build submission selector options
        sub_options = {
            f"{s['submission_id']} — {s['student_name']} ({s['timestamp']}) [{'EVALUATED ✅' if s.get('evaluated') else 'PENDING ⏳'}]": idx
            for idx, s in enumerate(submissions)
        }
        
        selected_label = st.selectbox("Select Student Submission to Review", options=list(sub_options.keys()))
        selected_idx = sub_options[selected_label]
        sub = submissions[selected_idx]
        
        st.markdown(f"### Student: **{sub['student_name']}** (`{sub['submission_id']}`)")
        st.caption(f"Submitted on: {sub['timestamp']}")
        
        c1, c2 = st.columns(2)
        with c1:
            st.metric("Auto-Scored MCQ Result", f"{sub['mcq_score']} / {sub['total_mcq']}")
        with c2:
            status_label = "Evaluated ✅" if sub.get("evaluated") else "Pending Evaluation ⏳"
            st.metric("Evaluation Status", status_label)
            
        st.markdown("---")
        
        manual_marks = sub.get("manual_marks", {})
        teacher_remarks = sub.get("teacher_remarks", {})
        
        with st.form("evaluation_grading_form"):
            st.markdown("#### 📝 Evaluate Subjective & Short Answers")
            
            for q_id_str, student_ans in sub["responses"].items():
                q_id = int(q_id_str) if str(q_id_str).isdigit() else q_id_str
                q_info = q_dict.get(q_id, {"question": f"Question #{q_id}", "type": "unknown", "answer": "N/A"})
                q_type = q_info.get("type", "mcq")
                
                st.markdown(f"**Q. {q_info['question']}**")
                st.caption(f"Question Type: **{q_type.upper()}**")
                
                if q_type == "mcq":
                    is_correct = student_ans == q_info.get("answer")
                    if is_correct:
                        st.success(f"Student Choice: **{student_ans}** (Correct ✅)")
                    else:
                        st.error(f"Student Choice: **{student_ans}** (Incorrect ❌) | Key: **{q_info.get('answer')}**")
                else:
                    st.info(f"**Student Answer:**\n\n>{student_ans if student_ans else '*No response provided*'}")
                    st.markdown(f"**Model Key / Solution Guidelines:**\n`{q_info.get('answer')}`")
                    
                    col_m1, col_m2 = st.columns([1, 3])
                    with col_m1:
                        existing_mark = manual_marks.get(str(q_id), 0.0)
                        manual_marks[str(q_id)] = st.number_input(
                            f"Marks (Q#{q_id})", 
                            min_value=0.0, 
                            max_value=10.0, 
                            value=float(existing_mark),
                            step=0.5,
                            key=f"mark_{sub['submission_id']}_{q_id}"
                        )
                    with col_m2:
                        existing_remark = teacher_remarks.get(str(q_id), "")
                        teacher_remarks[str(q_id)] = st.text_input(
                            f"Faculty Remark (Q#{q_id})", 
                            value=existing_remark,
                            placeholder="e.g. Good derivation, check sign in step 2",
                            key=f"remark_{sub['submission_id']}_{q_id}"
                        )
                st.markdown("---")
                
            eval_submitted = st.form_submit_button("💾 Save Evaluation & Grade", use_container_width=True)
            
            if eval_submitted:
                submissions[selected_idx]["manual_marks"] = manual_marks
                submissions[selected_idx]["teacher_remarks"] = teacher_remarks
                submissions[selected_idx]["evaluated"] = True
                
                with open(SUBMISSIONS_FILE_PATH, "w", encoding="utf-8") as f:
                    json.dump(submissions, f, indent=4, ensure_ascii=False)
                    
                st.session_state["form_success"] = f"Successfully saved evaluation for {sub['student_name']} ({sub['submission_id']})!"
                st.rerun()
