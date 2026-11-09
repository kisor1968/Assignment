import streamlit as st
import json
from pathlib import Path
import pypdf
import re
import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image
import pytesseract
import platform

# Automatically configure path ONLY if running locally on Windows
if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# Explicitly set the path to tesseract.exe on Windows
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

DEFAULT_QUESTIONS = [
    {
        "id": 1,
        "question": "What is the SI unit of electric charge?",
        "options": ["Ampere", "Coulomb", "Volt", "Ohm"],
        "answer": "Coulomb"
    },
    {
        "id": 2,
        "question": "Which of the following physical quantities is a scalar?",
        "options": ["Velocity", "Force", "Work", "Acceleration"],
        "answer": "Work"
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
    st.subheader("Department of Physics — Diagnostic Test")
    st.markdown("---")

    questions = load_questions()

    if not questions:
        st.warning("No questions found in the question bank yet!")
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
                    st.markdown(f"#### **Q{idx}. {q['question']}**")
                    user_responses[q["id"]] = st.radio(
                        label=f"Choose answer for Q{idx}",
                        options=q["options"],
                        index=None,
                        key=f"q_{q['id']}",
                        label_visibility="collapsed"
                    )
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                submit_btn = st.form_submit_button("🚀 Submit Assessment", use_container_width=True)
                
                if submit_btn:
                    unanswered = [q["id"] for q in questions if user_responses[q["id"]] is None]
                    if unanswered:
                        st.warning(f"Please answer all questions before submitting! ({len(unanswered)} remaining)")
                    else:
                        score = sum(1 for q in questions if user_responses[q["id"]] == q["answer"])
                        st.session_state["user_answers"] = user_responses
                        st.session_state["score"] = score
                        st.session_state["submitted"] = True
                        st.rerun()
        else:
            score = st.session_state["score"]
            total = len(questions)
            percentage = int((score / total) * 100) if total > 0 else 0
            
            st.markdown("## 📊 Assessment Result Summary")
            c1, c2, c3 = st.columns(3)
            with c1: st.metric("Total Score", f"{score} / {total}")
            with c2: st.metric("Percentage", f"{percentage}%")
            with c3: st.metric("Status", "PASSED ✅" if percentage >= 50 else "NEEDS REVIEW ⚠️")
                
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
    st.markdown("### ✍️ Teacher Question Creator & OCR Importer")
    st.markdown("---")

    if "form_success" in st.session_state:
        st.success(st.session_state["form_success"])
        del st.session_state["form_success"]

    # Manual Creator Form
    st.markdown("#### ➕ Add Individual MCQ Question")
    with st.form("add_question_form"):
        new_q_text = st.text_area("Question Text", placeholder="e.g., What is $E = mc^2$?")
        c1, c2 = st.columns(2)
        with c1:
            opt1 = st.text_input("Option A", "Energy")
            opt2 = st.text_input("Option B", "Force")
        with c2:
            opt3 = st.text_input("Option C", "Mass")
            opt4 = st.text_input("Option D", "Velocity")
            
        valid_options = [o.strip() for o in [opt1, opt2, opt3, opt4] if o.strip()]
        correct_ans = st.selectbox("Select Correct Answer", options=valid_options if valid_options else ["Fill options"])
        
        if st.form_submit_button("💾 Save Question to Bank", use_container_width=True):
            if not new_q_text.strip() or len(valid_options) < 2:
                st.error("Please provide valid question text and at least 2 options.")
            else:
                current_q = load_questions()
                new_id = max([q.get("id", 0) for q in current_q], default=0) + 1
                current_q.append({"id": new_id, "question": new_q_text.strip(), "options": valid_options, "answer": correct_ans})
                with open(JSON_FILE_PATH, "w", encoding="utf-8") as f:
                    json.dump(current_q, f, indent=4, ensure_ascii=False)
                st.session_state["form_success"] = f"Successfully added Question #{new_id}!"
                st.rerun()

    st.markdown("---")
    
    # --- OCR PDF / Image Importer ---
    st.markdown("#### 📄 OCR-Powered PDF / Scanned Image Importer")
    st.caption("Upload a scanned PDF or image (`.pdf`, `.png`, `.jpg`) containing questions. Tesseract OCR will read the text automatically.")
    
    uploaded_file = st.file_uploader("Upload Scanned Question Paper", type=["pdf", "png", "jpg", "jpeg"])
    
    if uploaded_file is not None:
        if st.button("🚀 Run OCR & Import Questions", use_container_width=True):
            with st.spinner("Running OCR extraction... Please wait."):
                try:
                    full_text = ""
                    file_bytes = uploaded_file.read()
                    
                    if uploaded_file.type == "application/pdf":
                        # Try standard text extraction first
                        reader = pypdf.PdfReader(uploaded_file)
                        for page in reader.pages:
                            t = page.extract_text()
                            if t: full_text += t + "\n"
                        
                        # If text layer is empty (scanned image PDF), use OCR via pdf2image
                        if not full_text.strip():
                            images = convert_from_bytes(file_bytes)
                            for img in images:
                                full_text += pytesseract.image_to_string(img) + "\n"
                    else:
                        # Direct image OCR (PNG/JPG)
                        img = Image.open(uploaded_file)
                        full_text = pytesseract.image_to_string(img)
                    
                    if not full_text.strip():
                        st.error("OCR could not find any readable text in this file.")
                    else:
                        # Parse extracted text into questions
                        raw_questions = re.split(r'\n\s*(?=\d+\.\s)', full_text)
                        current_q_bank = load_questions()
                        added_count = 0
                        
                        for rq in raw_questions:
                            if not rq.strip(): continue
                            lines = [l.strip() for l in rq.split('\n') if l.strip()]
                            if len(lines) >= 3:
                                q_text = re.sub(r'^\d+\.\s*', '', lines[0])
                                options = [re.sub(r'^[A-Da-d][\.\)]\s*', '', opt) for opt in lines[1:5]]
                                if len(options) >= 2:
                                    new_id = max([q.get("id", 0) for q in current_q_bank], default=0) + 1
                                    current_q_bank.append({
                                        "id": new_id,
                                        "question": q_text,
                                        "options": options,
                                        "answer": options[0]
                                    })
                                    added_count += 1
                        
                        with open(JSON_FILE_PATH, "w", encoding="utf-8") as f:
                            json.dump(current_q_bank, f, indent=4, ensure_ascii=False)
                        
                        st.session_state["form_success"] = f"Successfully OCR-extracted and imported {added_count} questions!"
                        st.rerun()
                except Exception as e:
                    st.error(f"OCR Processing Error: {e}")
