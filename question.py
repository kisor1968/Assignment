import streamlit as st
import json
from pathlib import Path
import pypdf
import re
import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image
import platform

# --- CROSS-PLATFORM TESSERACT CONFIGURATION ---
if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Bridge Course Online Assessment Engine",
    page_icon="📝",
    layout="centered"
)

# --- ABSOLUTE PATH SETUP ---
BASE_DIR = Path(__file__).resolve().parent
JSON_FILE_PATH = BASE_DIR / "question.json"

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

tab_quiz, tab_creator = st.tabs(["📝 Take Assessment", "✍️ Teacher Question Creator"])

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

        if not st.session_state["submitted"]:
            with st.form("bridge_quiz_form"):
                user_responses = {}
                for idx, q in enumerate(questions, start=1):
                    q_type = q.get("type", "mcq") # Default to mcq for backwards compatibility
                    
                    st.markdown(f"#### **Q{idx}. {q['question']}**")
                    
                    # Render dynamic UI depending on Question Type
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
                        # Auto-score MCQs; subjective questions can be reviewed post-submission
                        mcq_questions = [q for q in questions if q.get("type", "mcq") == "mcq"]
                        mcq_correct = sum(
                            1 for q in mcq_questions if user_responses[q["id"]] == q.get("answer")
                        )
                        
                        st.session_state["user_answers"] = user_responses
                        st.session_state["score"] = mcq_correct
                        st.session_state["submitted"] = True
                        st.rerun()
        else:
            mcq_questions = [q for q in questions if q.get("type", "mcq") == "mcq"]
            total_mcq = len(mcq_questions)
            score = st.session_state["score"]
            percentage = int((score / total_mcq) * 100) if total_mcq > 0 else 0
            
            st.markdown("## 📊 Assessment Result Summary")
            
            if total_mcq > 0:
                c1, c2, c3 = st.columns(3)
                with c1: st.metric("MCQ Score", f"{score} / {total_mcq}")
                with c2: st.metric("MCQ Percentage", f"{percentage}%")
                with c3: st.metric("Status", "PASSED ✅" if percentage >= 50 else "NEEDS REVIEW ⚠️")
            else:
                st.info("This test consists entirely of subjective/descriptive questions.")
                
            st.markdown("---")
            st.markdown("### 🔍 Detailed Submission & Solution Review")
            
            user_ans = st.session_state["user_answers"]
            
            for idx, q in enumerate(questions, start=1):
                selected = user_ans.get(q["id"], "")
                model_ans = q.get("answer", "")
                q_type = q.get("type", "mcq")
                
                st.markdown(f"**Q{idx}. {q['question']}**")
                st.caption(f"Question Type: **{q_type.upper()}**")
                
                if q_type == "mcq":
                    is_correct = selected == model_ans
                    if is_correct:
                        st.success(f"Your Answer: **{selected}** (Correct ✅)")
                    else:
                        st.error(f"Your Answer: **{selected}** (Incorrect ❌)\n\nCorrect Answer: **{model_ans}**")
                else:
                    st.info(f"**Your Submitted Response:**\n\n>{selected}")
                    with st.expander("📖 View Model Answer / Grading Key"):
                        st.write(model_ans)
                st.markdown("---")

            if st.button("🔄 Retake Test", use_container_width=True):
                st.session_state["submitted"] = False
                st.session_state["user_answers"] = {}
                st.session_state["score"] = 0
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

    # --- Section A: Flexible Question Creator Form ---
    st.markdown("#### ➕ Add New Question")
    
    # Select question type outside form to dynamically render inputs
    q_type_choice = st.selectbox(
        "Select Question Type", 
        ["Multiple Choice (MCQ)", "Short Answer Type", "Long Answer / Descriptive Type"]
    )
    
    with st.form("add_flexible_question_form"):
        new_q_text = st.text_area("Question Prompt", placeholder="Enter your question text or problem statement here...")
        
        valid_options = []
        correct_ans = ""
        
        if q_type_choice == "Multiple Choice (MCQ)":
            q_type_code = "mcq"
            c1, c2 = st.columns(2)
            with c1:
                opt1 = st.text_input("Option A")
                opt2 = st.text_input("Option B")
            with c2:
                opt3 = st.text_input("Option C")
                opt4 = st.text_input("Option D")
                
            valid_options = [o.strip() for o in [opt1, opt2, opt3, opt4] if o.strip()]
            correct_ans = st.selectbox("Select Correct Option", options=valid_options if valid_options else ["Provide options above"])
        
        elif q_type_choice == "Short Answer Type":
            q_type_code = "short"
            correct_ans = st.text_input("Model Answer / Key Words", placeholder="e.g., Energy / Force / Standard definition")
            
        else: # Long Answer Type
            q_type_code = "long"
            correct_ans = st.text_area("Model Solution / Evaluation Guidelines", placeholder="Provide the step-by-step solution, formula derivation, or key grading criteria...")

        if st.form_submit_button("💾 Save Question to Bank", use_container_width=True):
            if not new_q_text.strip():
                st.error("Question prompt cannot be empty!")
            elif q_type_code == "mcq" and len(valid_options) < 2:
                st.error("Multiple-choice questions require at least 2 valid options.")
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
    
    # --- Section B: Smart PDF / Image Importer ---
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
                                # Detect if sub-lines match option patterns like (a), (b) or A), B)
                                potential_opts = [l for l in lines[1:] if re.match(r'^\(?[A-Da-d]\)[\.\s]', l)]
                                
                                if len(potential_opts) >= 2:
                                    q_type = "mcq"
                                    opts = [re.sub(r'^\(?[A-Da-d]\)[\.\s]*', '', o) for o in potential_opts]
                                    ans = opts[0]
                                else:
                                    # If no clean MCQ options are found, import as a subjective long/short question
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

    # --- Section C: Question Bank Management ---
    st.markdown("---")
    st.markdown("#### ⚙️ Question Bank Management")
    st.caption("Clear existing records to start a fresh question bank.")
    
    if st.button("🗑️ Clear & Reset Entire Question Bank", type="secondary", use_container_width=True):
        with open(JSON_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump([], f, indent=4, ensure_ascii=False)
        st.session_state["form_success"] = "Question bank has been completely cleared and reset!"
        st.rerun()
