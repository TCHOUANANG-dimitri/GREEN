# ============================================================
# GREEN App — Database Models (SQLAlchemy ORM)
# Each class maps to a table in the SQLite database.
# Tables are auto-created on startup via Base.metadata.create_all()
# ============================================================

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime,
    Text, Float, ForeignKey, JSON
)
from sqlalchemy.orm import relationship
from database import Base
import datetime


# ---- Helper -------------------------------------------------
def utcnow():
    """Returns current UTC time (used as default for timestamps)."""
    return datetime.datetime.utcnow()


# =============================================================
# USER — Platform accounts (enterprise managers / agronomists)
# =============================================================
class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    first_name    = Column(String(100), nullable=False)
    last_name     = Column(String(100), nullable=False)
    phone         = Column(String(20),  unique=True, nullable=False, index=True)
    email         = Column(String(255), unique=True, nullable=True,  index=True)
    password_hash = Column(String(255), nullable=False)
    company_name  = Column(String(255), nullable=True)   # Agribusiness name
    region        = Column(String(100), nullable=True)   # Cameroon region
    avatar_url    = Column(String(500), nullable=True)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=utcnow)
    updated_at    = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    parcels          = relationship("Parcel",          back_populates="owner", cascade="all, delete-orphan")
    analyses         = relationship("DiseaseAnalysis", back_populates="user",  cascade="all, delete-orphan")
    chat_sessions    = relationship("ChatSession",     back_populates="user",  cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User id={self.id} phone={self.phone}>"


# =============================================================
# PARCEL — Agricultural land plots / parcelles
# =============================================================
class Parcel(Base):
    __tablename__ = "parcels"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name        = Column(String(255), nullable=False)         # e.g. "Parcelle Nord-Est"
    crop_type   = Column(String(100), nullable=True)          # e.g. "Maïs", "Manioc", "Tomate"
    area_ha     = Column(Float, nullable=True)                # Area in hectares
    region      = Column(String(100), nullable=True)          # Cameroon region
    description = Column(Text, nullable=True)
    # GeoJSON polygon stored as JSON string (Leaflet.js compatible)
    geometry    = Column(JSON, nullable=True)
    # Center coordinates for map display
    latitude    = Column(Float, nullable=True)
    longitude   = Column(Float, nullable=True)
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=utcnow)
    updated_at  = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    owner    = relationship("User",            back_populates="parcels")
    analyses = relationship("DiseaseAnalysis", back_populates="parcel", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Parcel id={self.id} name={self.name}>"


# =============================================================
# DISEASE ANALYSIS — Each drone scan / manual image analysis
# =============================================================
class DiseaseAnalysis(Base):
    __tablename__ = "disease_analyses"

    id              = Column(Integer, primary_key=True, index=True)
    user_id         = Column(Integer, ForeignKey("users.id"),    nullable=False, index=True)
    parcel_id       = Column(Integer, ForeignKey("parcels.id"),  nullable=True,  index=True)

    # Detection input
    source          = Column(String(50), default="camera")  # "camera" | "upload" | "drone"
    image_path      = Column(String(500), nullable=True)   # Saved frame path

    # Detection output — Disease model (EfficientNet)
    detected_disease= Column(String(255), nullable=True)   # Disease class ID or "healthy"
    disease_name    = Column(String(255), nullable=True)   # Human-readable name
    confidence      = Column(Float, nullable=True)         # 0.0 – 1.0
    severity        = Column(String(50),  nullable=True)   # "low" | "medium" | "high"
    plant_type      = Column(String(100), nullable=True)   # "tomate" | "maïs" | "manioc" etc.

    # Detection output — Pest model (Phase MVP)
    pest_detected   = Column(String(255), nullable=True)   # Pest class ID or "none"
    pest_name       = Column(String(255), nullable=True)   # Human-readable pest name
    pest_confidence = Column(Float, nullable=True)         # 0.0 – 1.0
    pest_severity   = Column(String(50),  nullable=True)   # "low" | "medium" | "high"

    # GPS coordinates (optional — rover GPS not yet implemented)
    latitude        = Column(Float, nullable=True)
    longitude       = Column(Float, nullable=True)

    # Generated terrain sheet (fiche terrain) stored as JSON
    fiche_terrain   = Column(JSON, nullable=True)

    # Analysis metadata
    notes           = Column(Text, nullable=True)
    created_at      = Column(DateTime, default=utcnow, index=True)

    # Relationships
    user   = relationship("User",   back_populates="analyses")
    parcel = relationship("Parcel", back_populates="analyses")

    def __repr__(self):
        return f"<DiseaseAnalysis id={self.id} disease={self.detected_disease} confidence={self.confidence}>"


# =============================================================
# CHAT SESSION — GreenBot conversation sessions
# =============================================================
class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title      = Column(String(255), nullable=True)   # Auto-generated from first message
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    user     = relationship("User",        back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan",
                            order_by="ChatMessage.created_at")

    def __repr__(self):
        return f"<ChatSession id={self.id} user_id={self.user_id}>"


# =============================================================
# CHAT MESSAGE — Individual messages within a GreenBot session
# =============================================================
class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id         = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False, index=True)
    role       = Column(String(20), nullable=False)   # "user" | "assistant"
    content    = Column(Text, nullable=False)
    # Optional: link message to a disease analysis for context
    analysis_id= Column(Integer, ForeignKey("disease_analyses.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    # Relationships
    session = relationship("ChatSession", back_populates="messages")

    def __repr__(self):
        return f"<ChatMessage id={self.id} role={self.role}>"
