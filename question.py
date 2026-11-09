import streamlit as st
import streamlit.components.v1 as components
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

# =====================================================================
# 🎨 DRAMATIC NEON THEME + 3D EFFECTS
# =====================================================================
NEON_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800&family=Poppins:wght@300;400;600&display=swap');

:root{
  --c1:#ff2e97; --c2:#7b2ff7; --c3:#00e5ff; --c4:#ffd400; --c5:#00ff9d;
}

/* ---------- Animated gradient backdrop ---------- */
.stApp{
  background: linear-gradient(135deg,#0b0420,#1a0638,#05172e,#2a0845,#031c2e);
  background-size: 400% 400%;
  animation: bgShift 22s ease infinite;
  font-family:'Poppins',sans-serif;
}
@keyframes bgShift{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
[data-testid="stHeader"]{background:transparent;}
.block-container{position:relative;z-index:2;padding-top:1.5rem;}

/* ---------- Floating 3D cubes in background ---------- */
.scene3d{position:fixed;inset:0;perspective:900px;z-index:0;pointer-events:none;overflow:hidden;}
.cube{position:absolute;width:60px;height:60px;transform-style:preserve-3d;
      animation:spin 14s linear infinite, floaty 9s ease-in-out infinite;}
.cube div{position:absolute;width:60px;height:60px;border:2px solid;opacity:.55;
          box-shadow:0 0 18px currentColor, inset 0 0 18px currentColor;}
.cube div:nth-child(1){transform:translateZ(30px)}
.cube div:nth-child(2){transform:rotateY(90deg) translateZ(30px)}
.cube div:nth-child(3){transform:rotateY(180deg) translateZ(30px)}
.cube div:nth-child(4){transform:rotateY(-90deg) translateZ(30px)}
.cube div:nth-child(5){transform:rotateX(90deg) translateZ(30px)}
.cube div:nth-child(6){transform:rotateX(-90deg) translateZ(30px)}
.cube.a{left:6%;top:18%;color:var(--c1);animation-duration:12s,8s}
.cube.b{left:88%;top:12%;color:var(--c3);animation-duration:17s,10s;transform:scale(1.5)}
.cube.c{left:80%;top:68%;color:var(--c4);animation-duration:15s,7s}
.cube.d{left:10%;top:72%;color:var(--c5);animation-duration:20s,11s;transform:scale(1.8)}
.cube.e{left:50%;top:88%;color:var(--c2);animation-duration:13s,9s}
.cube div{border-color:currentColor;}
@keyframes spin{from{transform:rotateX(0) rotateY(0) rotateZ(0)}to{transform:rotateX(360deg) rotateY(720deg) rotateZ(360deg)}}
@keyframes floaty{0%,100%{margin-top:0}50%{margin-top:-50px}}

/* ---------- Typography ---------- */
h1,h2,h3,h4,h5{font-family:'Orbitron',sans-serif !important;letter-spacing:.5px;}
h1{
  background:linear-gradient(90deg,var(--c1),var(--c4),var(--c3),var(--c1));
  background-size:300% auto;-webkit-background-clip:text;background-clip:text;
  -webkit-text-fill-color:transparent;animation:shine 6s linear infinite;
  text-shadow:0 0 30px rgba(255,46,151,.35);
}
@keyframes shine{to{background-position:300% center}}
h2,h3{color:var(--c3) !important;text-shadow:0 0 14px rgba(0,229,255,.55);}
h4{color:#ffb3e1 !important;text-shadow:0 0 10px rgba(255,46,151,.5);}
p,li,label,span,.stMarkdown,[data-testid="stWidgetLabel"] p,[data-testid="stCaptionContainer"]{color:#e9e4ff;}
hr{border:none !important;height:2px !important;
   background:linear-gradient(90deg,transparent,var(--c1),var(--c3),var(--c4),transparent) !important;
   box-shadow:0 0 12px var(--c1);}

/* ---------- Tabs ---------- */
.stTabs [data-baseweb="tab-list"]{gap:10px;background:rgba(255,255,255,.04);padding:8px;border-radius:16px;
  border:1px solid rgba(255,255,255,.12);backdrop-filter:blur(10px);}
.stTabs [data-baseweb="tab"]{border-radius:12px;padding:10px 18px;color:#cfc4ff;
  transition:all .3s;transform-style:preserve-3d;}
.stTabs [data-baseweb="tab"]:hover{transform:translateY(-4px) rotateX(12deg);color:#fff;
  background:rgba(123,47,247,.35);box-shadow:0 8px 20px rgba(123,47,247,.5);}
.stTabs [aria-selected="true"]{background:linear-gradient(135deg,var(--c1),var(--c2)) !important;
  color:#fff !important;box-shadow:0 0 22px rgba(255,46,151,.7);}
.stTabs [data-baseweb="tab-highlight"],.stTabs [data-baseweb="tab-border"]{display:none;}

/* ---------- Inputs (glass) ---------- */
.stTextInput input,.stTextArea textarea,.stNumberInput input,[data-baseweb="select"]>div{
  background:rgba(255,255,255,.07) !important;color:#fff !important;
  border:1px solid rgba(0,229,255,.35) !important;border-radius:12px !important;
  backdrop-filter:blur(8px);transition:all .3s;}
.stTextInput input:focus,.stTextArea textarea:focus,.stNumberInput input:focus{
  border-color:var(--c1) !important;box-shadow:0 0 0 2px rgba(255,46,151,.45),0 0 25px rgba(255,46,151,.45) !important;
  transform:translateY(-2px);}
[data-baseweb="popover"] ul{background:#1a0638 !important;}
[data-baseweb="popover"] li{color:#fff !important;}
[data-testid="stFileUploader"] section{background:rgba(255,255,255,.05);border:2px dashed var(--c3);
  border-radius:16px;transition:all .3s;}
[data-testid="stFileUploader"] section:hover{border-color:var(--c1);box-shadow:0 0 25px rgba(255,46,151,.5);
  transform:perspective(600px) rotateX(3deg) scale(1.01);}
[data-testid="stFileUploader"] section *{color:#e9e4ff !important;}

/* ---------- Radio options as 3D cards ---------- */
.stRadio [role="radiogroup"] label{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.15);
  border-radius:14px;padding:10px 16px;margin-bottom:8px;transition:all .25s;transform-style:preserve-3d;}
.stRadio [role="radiogroup"] label:hover{transform:perspective(600px) translateZ(14px) rotateY(-4deg) translateX(6px);
  background:linear-gradient(90deg,rgba(255,46,151,.3),rgba(0,229,255,.25));
  box-shadow:0 10px 25px rgba(0,229,255,.35);border-color:var(--c3);}

/* ---------- Buttons ---------- */
.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button{
  background:linear-gradient(135deg,var(--c1),var(--c2),var(--c3));background-size:250% 250%;
  color:#fff !important;font-weight:600;border:none;border-radius:14px;padding:.7rem 1rem;
  box-shadow:0 8px 0 #4a1a8f,0 14px 30px rgba(123,47,247,.55);
  transition:all .25s;animation:btnflow 5s ease infinite;}
@keyframes btnflow{0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
.stButton>button:hover,.stFormSubmitButton>button:hover,.stDownloadButton>button:hover{
  transform:translateY(-4px) scale(1.02);box-shadow:0 12px 0 #4a1a8f,0 22px 40px rgba(255,46,151,.6);color:#fff !important;}
.stButton>button:active,.stFormSubmitButton>button:active{transform:translateY(6px);box-shadow:0 2px 0 #4a1a8f,0 4px 12px rgba(0,0,0,.5);}
.stButton>button[kind="primary"]{background:linear-gradient(135deg,var(--c4),var(--c1),var(--c2));
  box-shadow:0 8px 0 #8a1450,0 14px 34px rgba(255,46,151,.65);animation:btnflow 4s ease infinite, pulse 2.2s infinite;}
@keyframes pulse{0%,100%{filter:brightness(1)}50%{filter:brightness(1.25)}}

/* ---------- Metrics as tilted 3D cards ---------- */
[data-testid="stMetric"]{background:linear-gradient(145deg,rgba(123,47,247,.35),rgba(0,229,255,.18));
  border:1px solid rgba(255,255,255,.25);border-radius:18px;padding:16px 18px;
  transform:perspective(800px) rotateX(6deg) rotateY(-6deg);transition:all .4s;
  box-shadow:0 18px 35px rgba(0,0,0,.5),0 0 25px rgba(123,47,247,.45);}
[data-testid="stMetric"]:hover{transform:perspective(800px) rotateX(0) rotateY(0) translateY(-8px) scale(1.04);
  box-shadow:0 26px 45px rgba(0,0,0,.55),0 0 40px rgba(0,229,255,.7);}
[data-testid="stMetricValue"]{color:var(--c4) !important;text-shadow:0 0 14px rgba(255,212,0,.7);
  font-family:'Orbitron',sans-serif;}
[data-testid="stMetricLabel"] *{color:#bfe9ff !important;}

/* ---------- Alerts ---------- */
[data-testid="stAlert"]{border-radius:16px;backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,.2);
  animation:slideIn .6s ease both;}
@keyframes slideIn{from{opacity:0;transform:translateX(-40px) rotateY(25deg)}to{opacity:1;transform:none}}
[data-testid="stAlert"] *{color:#fff !important;}

/* ---------- Forms & expanders ---------- */
[data-testid="stForm"]{background:rgba(255,255,255,.04);border:1px solid rgba(255,46,151,.4);
  border-radius:20px;box-shadow:0 0 30px rgba(255,46,151,.25);}
</style>

<div class="scene3d">
  <div class="cube a"><div></div><div></div><div></div><div></div><div></div><div></div></div>
  <div class="cube b"><div></div><div></div><div></div><div></div><div></div><div></div></div>
  <div class="cube c"><div></div><div></div><div></div><div></div><div></div><div></div></div>
  <div class="cube d"><div></div><div></div><div></div><div></div><div></div><div></div></div>
  <div class="cube e"><div></div><div></div><div></div><div></div><div></div><div></div></div>
</div>
"""
st.markdown(NEON_CSS, unsafe_allow_html=True)

# --- Three.js interactive 3D hero banner (rotating knot + particles + mouse parallax) ---
THREE_HERO = """
<div id="wrap" style="width:100%;height:100%;position:relative;font-family:sans-serif;">
  <canvas id="c" style="width:100%;height:100%;display:block;"></canvas>
  <div style="position:absolute;left:0;right:0;bottom:8px;text-align:center;color:#fff;
       font-size:13px;letter-spacing:4px;text-shadow:0 0 12px #00e5ff;">
       MOVE YOUR MOUSE · EXPLORE THE BRIDGE
  </div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
const canvas=document.getElementById('c');
const renderer=new THREE.WebGLRenderer({canvas,alpha:true,antialias:true});
renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(55,2,0.1,100);camera.position.z=7;

const knot=new THREE.Mesh(new THREE.TorusKnotGeometry(1.3,0.4,180,24),
  new THREE.MeshStandardMaterial({color:0xff2e97,metalness:.7,roughness:.2,emissive:0x330022}));
scene.add(knot);
const wire=new THREE.Mesh(new THREE.IcosahedronGeometry(2.6,1),
  new THREE.MeshBasicMaterial({color:0x00e5ff,wireframe:true,transparent:true,opacity:.35}));
scene.add(wire);
const ring=new THREE.Mesh(new THREE.TorusGeometry(3.4,0.03,16,120),
  new THREE.MeshBasicMaterial({color:0xffd400}));
ring.rotation.x=Math.PI/2.4;scene.add(ring);
const ring2=ring.clone();ring2.material=new THREE.MeshBasicMaterial({color:0x7b2ff7});
ring2.rotation.x=-Math.PI/3;ring2.rotation.y=.6;scene.add(ring2);

// orbiting colourful spheres
const orbs=[];const cols=[0x00ff9d,0xffd400,0x00e5ff,0xff2e97,0x7b2ff7];
cols.forEach((c,i)=>{
  const m=new THREE.Mesh(new THREE.SphereGeometry(.22,24,24),
    new THREE.MeshStandardMaterial({color:c,emissive:c,emissiveIntensity:.6}));
  m.userData={r:3+i*.25,s:.6+i*.15,o:i*1.3};scene.add(m);orbs.push(m);
});

// particles
const N=900,pos=new Float32Array(N*3),col=new Float32Array(N*3);
for(let i=0;i<N;i++){
  pos[i*3]=(Math.random()-.5)*26;pos[i*3+1]=(Math.random()-.5)*14;pos[i*3+2]=(Math.random()-.5)*14;
  const k=new THREE.Color().setHSL(Math.random(),1,.6);col.set([k.r,k.g,k.b],i*3);
}
const g=new THREE.BufferGeometry();
g.setAttribute('position',new THREE.BufferAttribute(pos,3));
g.setAttribute('color',new THREE.BufferAttribute(col,3));
const pts=new THREE.Points(g,new THREE.PointsMaterial({size:.07,vertexColors:true}));
scene.add(pts);

scene.add(new THREE.AmbientLight(0xffffff,.5));
const l1=new THREE.PointLight(0x00e5ff,2,30);l1.position.set(5,4,5);scene.add(l1);
const l2=new THREE.PointLight(0xff2e97,2,30);l2.position.set(-5,-3,4);scene.add(l2);

let mx=0,my=0;
window.addEventListener('mousemove',e=>{mx=(e.clientX/innerWidth-.5)*2;my=(e.clientY/innerHeight-.5)*2;});
function resize(){const w=canvas.clientWidth,h=canvas.clientHeight;renderer.setSize(w,h,false);
  camera.aspect=w/h;camera.updateProjectionMatrix();}
window.addEventListener('resize',resize);resize();

const clock=new THREE.Clock();
(function loop(){
  const t=clock.getElapsedTime();
  knot.rotation.x=t*.5+my*.6;knot.rotation.y=t*.7+mx*.8;
  const s=1+Math.sin(t*2)*.05;knot.scale.set(s,s,s);
  wire.rotation.y=-t*.25;wire.rotation.x=t*.15;
  ring.rotation.z=t*.6;ring2.rotation.z=-t*.4;
  orbs.forEach(o=>{const d=o.userData;o.position.set(Math.cos(t*d.s+d.o)*d.r,Math.sin(t*d.s*1.3+d.o)*1.6,Math.sin(t*d.s+d.o)*d.r);});
  pts.rotation.y=t*.03;
  camera.position.x+=(mx*1.5-camera.position.x)*.05;
  camera.position.y+=(-my*1-camera.position.y)*.05;camera.lookAt(0,0,0);
  l1.color.setHSL((t*.05)%1,1,.6);
  renderer.render(scene,camera);requestAnimationFrame(loop);
})();
</script>
"""

def render_hero(height=320):
    components.html(
        "<style>html,body{margin:0;height:100%;background:transparent;overflow:hidden}</style>" + THREE_HERO,
        height=height,
    )

def banner(title, subtitle=""):
    st.markdown(
        f"""
        <div style="padding:18px 22px;border-radius:20px;margin-bottom:10px;
             background:linear-gradient(120deg,rgba(255,46,151,.35),rgba(123,47,247,.35),rgba(0,229,255,.3));
             border:1px solid rgba(255,255,255,.25);box-shadow:0 14px 40px rgba(123,47,247,.45);
             transform:perspective(900px) rotateX(4deg);">
          <div style="font-family:Orbitron,sans-serif;font-size:1.5rem;font-weight:800;color:#fff;
               text-shadow:0 0 18px #ff2e97;">{title}</div>
          <div style="color:#d6f6ff;margin-top:4px;">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
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
    render_hero(320)
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
            if st.session_state.get("celebrated") != st.session_state["last_sub_id"]:
                st.balloons()
                st.session_state["celebrated"] = st.session_state["last_sub_id"]
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
    banner("✍️ Question Creator Studio", "Create, import, edit and manage your question bank")
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
    banner("👨‍🏫 Evaluation & Grading Command Center", "Review submissions, inspect uploads and award marks")
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
                        st.warning(f"Handwritten File Uploaded: {Path(file_path).name}")
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
