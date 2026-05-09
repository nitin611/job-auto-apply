from fastapi import APIRouter, UploadFile, File, HTTPException
from app.config import settings
from app.services import profile as svc

router = APIRouter()


@router.get("/profile/preferences")
def get_prefs():
    return svc.load_preferences()


@router.post("/profile/preferences")
def save_prefs(payload: dict):
    svc.save_preferences(payload)
    return {"ok": True}


@router.get("/profile/answers")
def get_answers():
    return svc.load_answers()


@router.post("/profile/answers")
def save_answers(payload: dict):
    svc.save_answers(payload)
    return {"ok": True}


@router.get("/profile/resume")
def get_resume():
    return {"markdown": svc.load_resume_md(), "skills": svc.load_skills_md(),
            "pdf_present": svc.resume_pdf_path() is not None}


@router.post("/profile/resume")
def save_resume(payload: dict):
    if "markdown" in payload:
        svc.save_resume_md(payload["markdown"])
    if "skills" in payload:
        svc.save_skills_md(payload["skills"])
    return {"ok": True}


@router.post("/profile/resume/upload")
async def upload_resume(file: UploadFile = File(...)):
    fname = (file.filename or "").lower()
    raw = await file.read()
    if fname.endswith(".pdf"):
        out = settings.profile_dir / "resume.pdf"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(raw)
        # Try to extract text to resume.md if empty
        try:
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(raw))
            text = "\n\n".join(p.extract_text() or "" for p in reader.pages)
            if text.strip() and not svc.load_resume_md().strip().replace("# Your Name", "").strip():
                svc.save_resume_md(text)
        except Exception:
            pass
        return {"ok": True, "saved": "resume.pdf"}
    if fname.endswith((".md", ".txt")):
        svc.save_resume_md(raw.decode("utf-8", errors="ignore"))
        return {"ok": True, "saved": "resume.md"}
    raise HTTPException(400, "Upload PDF, MD, or TXT")
