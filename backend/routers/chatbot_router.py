# ============================================================
# GREEN App — GreenBot Router (Phase 6)
# RAG-powered agronomic chatbot using Google Gemini API.
#
# Endpoints:
#   POST /api/chat/sessions          — create a new session
#   GET  /api/chat/sessions          — list user's sessions
#   GET  /api/chat/sessions/{id}     — get session + messages
#   POST /api/chat/sessions/{id}/messages — send message, get reply
#   DELETE /api/chat/sessions/{id}   — delete session
# ============================================================

import json
import os
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import ChatSession, ChatMessage, DiseaseAnalysis, User
from auth import get_current_user
from config import GEMINI_API_KEY, GEMINI_MODEL, RAG_CHUNKS_PATH, RAG_EMBEDDINGS_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["GreenBot"])


# =============================================================
# RAG ENGINE — load chunks + TF-IDF index at startup
# =============================================================
_chunks: List[dict] = []
_vectorizer = None
_tfidf_matrix = None

def _load_rag():
    """Load RAG corpus and build TF-IDF index (called once at startup)."""
    global _chunks, _vectorizer, _tfidf_matrix

    if not os.path.exists(RAG_CHUNKS_PATH):
        logger.warning(f"[GreenBot] RAG chunks not found at {RAG_CHUNKS_PATH}")
        return

    with open(RAG_CHUNKS_PATH, encoding="utf-8") as f:
        _chunks = json.load(f)

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        texts = [c.get("text", "") for c in _chunks]
        _vectorizer = TfidfVectorizer(
            max_features=8000,
            ngram_range=(1, 2),
            sublinear_tf=True,
            strip_accents="unicode",
        )
        _tfidf_matrix = _vectorizer.fit_transform(texts)
        logger.info(f"[GreenBot] RAG index built — {len(_chunks)} chunks, TF-IDF shape {_tfidf_matrix.shape}")
    except Exception as e:
        logger.error(f"[GreenBot] Failed to build TF-IDF index: {e}")
        _vectorizer = None
        _tfidf_matrix = None

# _load_rag() is NOT called at import time.
# It is triggered from main.py's lifespan in a background thread so the
# server starts accepting requests immediately.


def _retrieve_context(query: str, top_k: int = 5) -> str:
    """Return the top-k most relevant text chunks for a query."""
    if _vectorizer is None or _tfidf_matrix is None or not _chunks:
        _load_rag()
        
    if _vectorizer is None or _tfidf_matrix is None or not _chunks:
        return ""

    try:
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity

        q_vec = _vectorizer.transform([query])
        scores = cosine_similarity(q_vec, _tfidf_matrix).flatten()
        top_indices = scores.argsort()[-top_k:][::-1]

        parts = []
        for idx in top_indices:
            if scores[idx] > 0.01:   # skip near-zero relevance
                chunk = _chunks[idx]
                parts.append(f"[Source: {chunk.get('source','?')} p.{chunk.get('page','?')}]\n{chunk.get('text','')}")
        return "\n\n---\n\n".join(parts)
    except Exception as e:
        logger.error(f"[GreenBot] RAG retrieval error: {e}")
        return ""


# =============================================================
# GOOGLE GEMINI API CLIENT
# =============================================================
_gemini_client = None
_gemini_client_key = None   # track key to detect changes


def _get_client():
    """
    Return a Google Gemini client.
    Re-creates the client if GEMINI_API_KEY changed since last call.
    """
    global _gemini_client, _gemini_client_key
    api_key = os.environ.get("GEMINI_API_KEY", "") or GEMINI_API_KEY
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "GreenBot non configuré. "
                "Veuillez définir GEMINI_API_KEY dans le fichier .env. "
                "Obtenez une clé gratuite sur aistudio.google.com/apikey"
            )
        )
    if _gemini_client is None or _gemini_client_key != api_key:
        try:
            from google import genai
            _gemini_client     = genai.Client(api_key=api_key)
            _gemini_client_key = api_key
            logger.info("[GreenBot] Gemini client initialised.")
        except ImportError:
            raise HTTPException(
                status_code=503,
                detail="Package google-genai non installé. Lancez : pip install google-genai"
            )
    return _gemini_client


SYSTEM_PROMPT = """Tu es Green Bot, le partenaire et guide expert agronome de l'application GREEN.

GREEN est une plateforme d'intelligence agricole destinée aux grandes entreprises agro-industrielles camerounaises et africaines. Elle permet la détection de maladies des plantes et de ravageurs via des modèles IA (EfficientNet-B0 + YOLOv8), l'analyse d'images de rover, et le suivi des parcelles agricoles.

Ton rôle est d'assister les gestionnaires d'exploitation, les agronomes de terrain et les directeurs agricoles en leur fournissant :
- Des conseils agronomiques précis sur les maladies des plantes (manioc, maïs, tomate et autres cultures camerounaises)
- Des recommandations de lutte contre les ravageurs (criquets, papillons de nuit, etc.)
- Des conseils sur les traitements phytosanitaires adaptés au contexte africain
- Des informations sur les pratiques agricoles durables et la gestion intégrée des cultures
- Une interprétation des résultats d'analyse IA (maladies détectées, ravageurs identifiés, niveaux de sévérité)
- Des conseils économiques et de gestion des coûts agricoles

Contexte géographique : Cameroun et Afrique centrale. Adapte toujours tes réponses aux réalités locales (disponibilité des produits, saisons, pratiques paysannes).

Règles de réponse :
- Réponds en anglais par défaut (ou en français  si l'utilisateur écrit en français)
- Sois précis, pratique et actionnable — privilégie les listes et les étapes claires
- Si une analyse IA est fournie dans le contexte, interprète-la en premier
- Si tu utilises des données de la base de connaissance agronomique, indique-le brièvement
- Ne fais pas de diagnostics médicaux humains
- Si tu n'es pas sûr, dis-le clairement et recommande une consultation avec un agronome terrain
"""


def _call_llm(messages: list, context_rag: str = "", analysis_context: str = "") -> str:
    """
    Call Google Gemini API with full conversation history.

    message format: [{"role": "user"|"assistant", "content": "..."}]
    The system prompt + RAG context are injected via system_instruction.
    """
    client = _get_client()

    # Build the system instruction with optional RAG and analysis context
    system = SYSTEM_PROMPT
    if analysis_context:
        system += f"\n\n--- ANALYSE IA EN COURS ---\n{analysis_context}\n--- FIN ANALYSE ---"
    if context_rag:
        system += (
            "\n\n--- BASE DE CONNAISSANCE AGRONOMIQUE (extraits pertinents) ---\n"
            f"{context_rag}\n--- FIN BASE DE CONNAISSANCE ---"
        )

    # Convert message history to Gemini format
    # Gemini uses "user" and "model" roles (not "assistant")
    gemini_contents = []
    for msg in messages:
        role = "model" if msg["role"] == "assistant" else "user"
        gemini_contents.append({
            "role": role,
            "parts": [{"text": msg["content"]}]
        })

    try:
        from google.genai import types

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=gemini_contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=1024,
                temperature=0.7,
            ),
        )
        return response.text

    except Exception as e:
        err_str = str(e)
        logger.error(f"[GreenBot] Gemini API error: {err_str}")

        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
            raise HTTPException(
                status_code=429,
                detail=(
                    "Quota Gemini épuisé. Le tier gratuit est limité à 15 requêtes/minute "
                    "et 1 million de tokens/jour. Attendez quelques minutes puis réessayez."
                )
            )
        if "403" in err_str or "PERMISSION_DENIED" in err_str:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Clé API Gemini invalide ou permissions insuffisantes. "
                    "Vérifiez votre clé dans le fichier .env et régénérez-la sur aistudio.google.com/apikey"
                )
            )
        if "400" in err_str or "INVALID_ARGUMENT" in err_str:
            raise HTTPException(
                status_code=400,
                detail=f"Requête Gemini invalide : {err_str}"
            )
        raise HTTPException(status_code=502, detail=f"GreenBot erreur : {err_str}")


# =============================================================
# PYDANTIC SCHEMAS
# =============================================================
class SessionCreate(BaseModel):
    title: Optional[str] = None


class MessageCreate(BaseModel):
    content: str
    analysis_id: Optional[int] = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    analysis_id: Optional[int]
    created_at: str

    class Config:
        from_attributes = True


class SessionOut(BaseModel):
    id: int
    title: Optional[str]
    created_at: str
    updated_at: str
    message_count: int = 0

    class Config:
        from_attributes = True


class SessionDetailOut(BaseModel):
    id: int
    title: Optional[str]
    created_at: str
    updated_at: str
    messages: List[MessageOut]

    class Config:
        from_attributes = True


# =============================================================
# HELPERS
# =============================================================
def _fmt(dt) -> str:
    return dt.isoformat() if dt else ""


def _analysis_context(analysis_id: Optional[int], db: Session) -> str:
    """Build a structured analysis context string for Gemini."""
    if not analysis_id:
        return ""
    a = db.query(DiseaseAnalysis).filter(DiseaseAnalysis.id == analysis_id).first()
    if not a:
        return ""

    lines = [f"Analyse #{a.id} — Source: {a.source}"]
    if a.plant_type:
        lines.append(f"Plante: {a.plant_type}")
    if a.disease_name:
        conf = f"{a.confidence * 100:.1f}%" if a.confidence else "—"
        lines.append(f"Maladie détectée: {a.disease_name} (confiance: {conf}, sévérité: {a.severity or '—'})")
    elif a.detected_disease == "healthy":
        lines.append("Maladie: Aucune (plante saine)")
    if a.pest_name and a.pest_name != "No pest detected":
        pconf = f"{a.pest_confidence * 100:.1f}%" if a.pest_confidence else "—"
        lines.append(f"Ravageur détecté: {a.pest_name} (confiance: {pconf}, sévérité: {a.pest_severity or '—'})")

    fiche = a.fiche_terrain or {}
    symptoms = fiche.get("symptoms") or (fiche.get("disease") or {}).get("symptoms") or []
    if symptoms:
        lines.append(f"Symptômes observés: {', '.join(symptoms[:3])}")
    recos = fiche.get("recommendations") or (fiche.get("disease") or {}).get("recommendations") or []
    if recos:
        lines.append(f"Recommandations initiales: {', '.join(recos[:2])}")

    return "\n".join(lines)


def _auto_title(content: str) -> str:
    """Generate a short session title from the first message."""
    words = content.strip().split()
    title = " ".join(words[:8])
    if len(words) > 8:
        title += "…"
    return title[:80]


# =============================================================
# ENDPOINTS
# =============================================================

@router.post("/sessions", status_code=201)
async def create_session(
    payload: SessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new GreenBot chat session."""
    session = ChatSession(
        user_id=current_user.id,
        title=payload.title or "New conversation",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "id": session.id,
        "title": session.title,
        "created_at": _fmt(session.created_at),
        "updated_at": _fmt(session.updated_at),
        "message_count": 0,
    }


@router.get("/sessions")
async def list_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all sessions for the current user (newest first)."""
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.updated_at.desc())
        .all()
    )
    return [
        {
            "id": s.id,
            "title": s.title,
            "created_at": _fmt(s.created_at),
            "updated_at": _fmt(s.updated_at),
            "message_count": len(s.messages),
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a session with all its messages."""
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Explicit query — bypasses ORM relationship cache so we always
    # get the latest committed messages even right after a write.
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
        .all()
    )

    return {
        "id": session.id,
        "title": session.title,
        "created_at": _fmt(session.created_at),
        "updated_at": _fmt(session.updated_at),
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "analysis_id": m.analysis_id,
                "created_at": _fmt(m.created_at),
            }
            for m in messages
        ],
    }


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: int,
    payload: MessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Send a user message and receive GreenBot's reply.
    Performs RAG retrieval and calls Gemini 2.0 Flash.
    """
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    from models import utcnow

    # Load prior messages via explicit query (bypasses ORM cache)
    prior_msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
        .all()
    )

    # Auto-title the session from the first user message
    if not prior_msgs:
        session.title = _auto_title(payload.content)

    # ── Commit user message first (separate transaction) ──────────────────
    # This guarantees the user's message is always saved even if Gemini
    # later fails (quota 429, network error) — nothing will roll it back.
    user_msg = ChatMessage(
        session_id=session_id,
        role="user",
        content=payload.content,
        analysis_id=payload.analysis_id,
    )
    db.add(user_msg)
    session.updated_at = utcnow()
    db.commit()
    db.refresh(user_msg)

    # Build history: prior messages + the just-committed user message
    history = [{"role": m.role, "content": m.content} for m in prior_msgs[-19:]]
    history.append({"role": "user", "content": payload.content})

    # RAG: retrieve relevant agricultural knowledge
    rag_context = _retrieve_context(payload.content, top_k=5)

    # Optional: enrich with linked analysis context
    analysis_ctx = _analysis_context(payload.analysis_id, db)

    # ── Call Gemini (may raise HTTPException — user msg already saved) ────
    reply_text = _call_llm(history, rag_context, analysis_ctx)

    # ── Commit assistant reply ────────────────────────────────────────────
    assistant_msg = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=reply_text,
    )
    db.add(assistant_msg)
    session.updated_at = utcnow()
    db.commit()
    db.refresh(assistant_msg)

    return {
        "id": assistant_msg.id,
        "role": "assistant",
        "content": reply_text,
        "created_at": _fmt(assistant_msg.created_at),
        "session_title": session.title,
        "rag_used": bool(rag_context),
    }


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a session and all its messages."""
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.delete(session)
    db.commit()
