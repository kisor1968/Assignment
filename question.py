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
UPLOADS_DIR = BASE_DIR / "student_uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

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

def save_questions(questions):
    with open(JSON_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(questions, f, indent=4, ensure_ascii=False)

def load_submissions():
    if not SUBMISSIONS_FILE_PATH.exists() or SUBMISSIONS_FILE_PATH.stat().st_size == 0:
        with open(SUBMISSIONS_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump([], f, indent=4, ensure_ascii=False)
    try:
        with open(SUBMISSIONS_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

tab_quiz, tab_creator, tab_eval = st.tabs([
    "📝 Take Assessment", 
    "✍️ Teacher Question Creator", 
    "👨‍🏫 Teacher Evaluation Dashboard"
])

# =====================================================================
# TAB 1: TAKE ASSESSMENT (Supports Live Answer Modification & File Uploads)
# =====================================================================
with tab_quiz:
    st.title("🌉 Bridge Course Online Assessment Engine")
    st.subheader("Department of Physics — Interactive Assessment")
    st.markdown("---")

    questions = load_questions()

    if not questions:
        st.warning("No questions found in the question bank yet! Switch to the **Teacher Question Creator** tab to add questions.")
    else:
        if "submitted" not in st.session_state:
            st.session_state["submitted"] = False
        if "last_sub_id" not in st.session_state:
            st.session_state["last_sub_id"] = None

        if not st.session_state["submitted"]:
            student_name = st.text_input("Enter Student Name / Roll Number", placeholder="e.g. Rahul Sharma (Roll: 102)", key="student_id_input")
            st.markdown("<br>", unsafe_allow_html=True)
            
            st.info("💡 You can freely modify your answers or upload handwritten work files at any time before clicking final submission.")
            st.markdown("---")

            user_responses = {}
            uploaded_files_data = {}

            for idx, q in enumerate(questions, start=1):
                q_type = q.get("type", "mcq")
                q_id = q["id"]
                st.markdown(f"#### **Q{idx}. {q['question']}**")
                
                if q_type == "mcq":
                    user_responses[q_id] = st.radio(
                        label=f"Choose answer for Q{idx}",
                        options=q.get("options", []),
                        index=None,
                        key=f"live_q_{q_id}",
                        label_visibility="collapsed"
                    )
                elif q_type == "short":
                    user_responses[q_id] = st.text_input(
                        label=f"Short answer for Q{idx}",
                        placeholder="Type concise answer here...",
                        key=f"live_q_{q_id}",
                        label_visibility="collapsed"
                    )
                    up_file = st.file_uploader(f"Upload handwritten file for Q{idx} (Optional)", type=["pdf", "png", "jpg", "jpeg"], key=f"file_q_{q_id}")
                    if up_file:
                        file_path = UPLOADS_DIR / f"{datetime.now().strftime('%Y%m%d%H%M%S')}_Q{q_id}_{up_file.name}"
                        with open(file_path, "wb") as f:
                            f.write(up_file.getbuffer())
                        uploaded_files_data[str(q_id)] = str(file_path)
                elif q_type == "long":
                    user_responses[q_id] = st.text_area(
                        label=f"Detailed answer for Q{idx}",
                        placeholder="Write detailed derivation/steps here...",
                        key=f"live_q_{q_id}",
                        label_visibility="collapsed"
                    )
                    up_file = st.file_uploader(f"Upload handwritten solution sheet for Q{idx} (Optional)", type=["pdf", "png", "jpg", "jpeg"], key=f"file_q_{q_id}")
                    if up_file:
                        file_path = UPLOADS_DIR / f"{datetime.now().strftime('%Y%m%d%H%M%S')}_Q{q_id}_{up_file.name}"
                        with open(file_path, "wb") as f:
                            f.write(up_file.getbuffer())
                        uploaded_files_data[str(q_id)] = str(file_path)
                
                st.markdown("<br>", unsafe_allow_html=True)
            
            if st.button("🚀 Final Submit Assessment", use_container_width=True, type="primary"):
                unanswered = [
                    q["id"] for q in questions 
                    if not user_responses.get(q["id"]) and str(q["id"]) not in uploaded_files_data
                ]
                if not student_name.strip():
                    st.error("Please enter your Student Name / Roll Number before submitting.")
                elif unanswered:
                    st.warning(f"Please attempt or upload work for all questions! ({len(unanswered)} remaining)")
                else:
                    mcq_questions = [q for q in questions if q.get("type", "mcq") == "mcq"]
                    mcq_correct = sum(
                        1 for q in mcq_questions if user_responses.get(q["id"]) == q.get("answer")
                    )
                    
                    submissions = load_submissions()
                    sub_id = f"SUB-{len(submissions) + 1:03d}"
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    new_sub = {
                        "submission_id": sub_id,
                        "student_name": student_name.strip(),
                        "timestamp": timestamp,
                        "mcq_score": mcq_correct,
                        "total_mcq": len(mcq_questions),
                        "responses": user_responses,
                        "uploads": uploaded_files_data,
                        "manual_marks": {},
                        "teacher_remarks": {},
                        "evaluated": False
                    }
                    
                    submissions.append(new_sub)
                    with open(SUBMISSIONS_FILE_PATH, "w", encoding="utf-8") as f:
                        json.dump(submissions, f, indent=4, ensure_ascii=False)
                    
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
            
            st.info("ℹ️ Your answers and uploaded documents have been securely logged for faculty evaluation.")
            st.markdown("---")

            if st.button("🔄 Retake / Start New Assessment", use_container_width=True):
                st.session_state["submitted"] = False
                st.session_state["last_sub_id"] = None
                st.rerun()

# =====================================================================
# TAB 2: TEACHER QUESTION CREATOR, OCR & QUESTION MANAGER (Edit/Remove)
# =====================================================================
with tab_creator:
    st.markdown("### ✍️ Teacher Question Creator, Importer & Manager")
    st.markdown("---")

    if "form_success" in st.session_state:
        st.success(st.session_state["form_success"])
        del st.session_state["form_success"]

    # --- Sub-section 1: Add New Question ---
    st.markdown("#### ➕ Add New Question")
    q_type_choice = st.selectbox(
        "Select Question Type", 
        ["Multiple Choice (MCQ)", "Short Answer Type", "Long Answer / Descriptive Type"],
        key="teacher_q_type"
    )
    
    new_q_text = st.text_area("Question Prompt", placeholder="Enter question text...", key="q_prompt_input")
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
            st.info("💡 Type at least 2 options above to activate correct option selector.")
    elif q_type_choice == "Short Answer Type":
        q_type_code = "short"
        correct_ans = st.text_input("Model Answer / Key Words", key="short_ans_input")
    else:
        q_type_code = "long"
        correct_ans = st.text_area("Model Solution / Evaluation Guidelines", key="long_ans_input")

    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("💾 Save Question to Bank", use_container_width=True, type="primary"):
        if not new_q_text.strip():
            st.error("Question prompt cannot be empty!")
        elif q_type_code == "mcq" and len(valid_options) < 2:
            st.error("MCQs require at least 2 valid options.")
        elif q_type_code == "mcq" and not correct_ans:
            st.error("Please select a valid correct answer option.")
        else:
            current_q = load_questions()
            new_id = max([q.get("id", 0) for q in current_q], default=0) + 1
            current_q.append({
                "id": new_id,
                "type": q_type_code,
                "question": new_q_text.strip(),
                "options": valid_options if q_type_code == "mcq" else [],
                "answer": correct_ans.strip()
            })
            save_questions(current_q)
            st.session_state["form_success"] = f"Successfully added Question #{new_id}!"
            st.rerun()

    st.markdown("---")
    
    # --- Sub-section 2: Modify or Remove Existing Questions ---
    st.markdown("#### ✏️ Modify or Remove Existing Questions")
    current_questions = load_questions()
    
    if not current_questions:
        st.info("No questions available to modify or remove.")
    else:
        q_edit_options = {f"Q{q['id']}: {q['question'][:50]}...": q['id'] for q in current_questions}
        selected_q_label = st.selectbox("Select Question to Edit or Remove", options=list(q_edit_options.keys()), key="select_q_to_edit")
        selected_q_id = q_edit_options[selected_q_label]
        
        target_q = next((q for q in current_questions if q['id'] == selected_q_id), None)
        
        if target_q:
            with st.form(f"edit_form_{selected_q_id}"):
                st.markdown(f"**Editing Question ID: {selected_q_id}**")
                edit_prompt = st.text_area("Edit Question Prompt", value=target_q['question'], key=f"edit_prompt_{selected_q_id}")
                edit_answer = st.text_area("Edit Model Answer / Key", value=target_q['answer'], key=f"edit_ans_{selected_q_id}")
                
                col_e1, col_e2 = st.columns(2)
                update_btn = col_e1.form_submit_button("🔄 Update Question", use_container_width=True)
                delete_btn = col_e2.form_submit_button("🗑️ Delete Question", use_container_width=True)
                
                if update_btn:
                    target_q['question'] = edit_prompt.strip()
                    target_q['answer'] = edit_answer.strip()
                    save_questions(current_questions)
                    st.session_state["form_success"] = f"Successfully updated Question #{selected_q_id}!"
                    st.rerun()
                
                if delete_btn:
                    updated_list = [q for q in current_questions if q['id'] != selected_q_id]
                    save_questions(updated_list)
                    st.session_state["form_success"] = f"Successfully deleted Question #{selected_q_id}!"
                    st.rerun()

    st.markdown("---")
    st.markdown("#### 📄 Smart PDF / Scanned Image Importer")
    uploaded_file = st.file_uploader("Upload Question Paper", type=["pdf", "png", "jpg", "jpeg"])
    
    if uploaded_file is not None:
        if st.button("🚀 Process & Import Questions", use_container_width=True):
            with st.spinner("Extracting and structuring text..."):
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
                        st.error("OCR could not extract readable text.")
                    else:
                        raw_questions = re.split(r'\n\s*(?=\d+\.\s)', full_text)
                        current_q_bank = load_questions()
                        added_count = 0
                        for rq in raw_questions:
                            clean_block = rq.strip()
                            if not clean_block: continue
                            new_id = max([q.get("id", 0) for q in current_q_bank], default=0) + 1
                            current_q_bank.append({
                                "id": new_id,
                                "type": "long",
                                "question": clean_block,
                                "options": [],
                                "answer": "Faculty review guideline."
                            })
                            added_count += 1
                        save_questions(current_q_bank)
                        st.session_state["form_success"] = f"Successfully imported {added_count} questions!"
                        st.rerun()
                except Exception as e:
                    st.error(f"Import Error: {e}")

# =====================================================================
# TAB 3: TEACHER EVALUATION & GRADING DASHBOARD (Views Student Uploads)
# =====================================================================
with tab_eval:
    st.markdown("### 👨‍🏫 Subjective Answer Evaluation & Grading Dashboard")
    st.caption("Review student submissions, inspect uploaded work files, assign manual marks, and record feedback.")
    st.markdown("---")

    submissions = load_submissions()
    questions = load_questions()
    q_dict = {q["id"]: q for q in questions}

    if not submissions:
        st.info("No student submissions logged yet.")
    else:
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
        student_uploads = sub.get("uploads", {})
        
        with st.form("evaluation_grading_form"):
            st.markdown("#### 📝 Evaluate Answers & Uploaded Files")
            
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
                    st.info(f"**Typed Student Answer:**\n\n>{student_ans if student_ans else '*No text response provided*'}")
                    
                    # Display uploaded file link if available
                    if str(q_id) in student_uploads:
                        file_path = student_uploads[str(q_id)]
                        st.warning(📁 **Handwritten File Uploaded:** ` {Path(file_path).name} `")
                        if Path(file_path).exists():
                            with open(file_path, "rb") as fp:
                                st.download_button(
                                    label=f"📥 Download Uploaded File for Q{q_id}",
                                    data=fp,
                                    file_name=Path(file_path).name,
                                    mime="application/octet-stream",
                                    key=f"dl_{sub['submission_id']}_{q_id}"
                                )
                    
                    st.markdown(f"**Model Key / Guidelines:**\n`{q_info.get('answer')}`")
                    
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
                            placeholder="e.g. Excellent derivation steps",
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
