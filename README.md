# GREEN — Agricultural Intelligence Platform

> **GREEN** (Gestion et Reconnaissance des Espèces et Nuisibles) is an end-to-end agricultural AI platform designed for Cameroonian agribusinesses. It combines a ground rover with a live camera, dual deep-learning inference (disease + pest detection), an agronomic RAG chatbot, and a rich web dashboard — all served from a single FastAPI backend.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Key Features](#2-key-features)
3. [System Architecture](#3-system-architecture)
4. [AI Models](#4-ai-models)
5. [Tech Stack](#5-tech-stack)
6. [Project Structure](#6-project-structure)
7. [Prerequisites](#7-prerequisites)
8. [Installation](#8-installation)
9. [Environment Variables](#9-environment-variables)
10. [Running the Application](#10-running-the-application)
11. [Application Pages](#11-application-pages)
12. [REST API Reference](#12-rest-api-reference)
13. [Database Schema](#13-database-schema)
14. [ONNX Export](#14-onnx-export)
15. [Roadmap](#15-roadmap)

---

## 1. Overview

GREEN is built around a **rover equipped with a camera** (streaming MJPEG over Wi-Fi) that patrols agricultural fields. Frames are grabbed by the FastAPI server, run through two AI models in parallel, and the results are stored, visualized, and discussed through the web interface.

The platform targets **Cameroonian field conditions** — crops (maize, cassava, tomato, plantain), regional disease pressures, local market prices in XAF, and Cameroon's dual planting seasons.

### What GREEN does

| Capability | Detail |
|---|---|
| **Disease detection** | EfficientNet-B0 classifying 11 disease/healthy states across 3 crop families |
| **Pest detection** | YOLOv8 detecting locusts (*Criquet*) and moths (*Papillon de nuit*) in real time |
| **Live camera feed** | MJPEG stream viewer with single-frame capture and instant AI analysis |
| **Parcel management** | GPS-tracked field parcels on an interactive Leaflet map |
| **Agronomic chatbot** | GreenBot — RAG + Google Gemini, answers questions in context of the user's field data |
| **Economic simulation** | Real-time ROI calculator for treatment decisions |
| **Agricultural calendar** | Cameroon crop schedule with planting / harvest / risk periods |
| **Disease reference** | 38-entry searchable knowledge base with symptoms and treatments |
| **Local benchmark** | User performance vs. regional averages (Cameroon) |
| **Weather integration** | OpenWeatherMap proxy per parcel location |

---

## 2. Key Features

### Dual AI Inference Pipeline
- Frames from the rover camera are passed **simultaneously** to both models via `asyncio.gather` + a dedicated `ThreadPoolExecutor(max_workers=2)`
- Wall-clock inference time = `max(T_disease, T_pest)` instead of the sum
- Both PyTorch and Ultralytics release the GIL during C-level operations, enabling true CPU overlap

### Authentication & Security
- JWT tokens (HS256, 7-day expiry) stored in `localStorage`
- Bcrypt password hashing (direct — no passlib due to bcrypt ≥ 4.x compatibility issues)
- All analysis and parcel endpoints require a valid Bearer token

### App Shell Architecture
- Single `layout.js` injects the sidebar and header into every page — no duplication
- Theme (light/dark) persisted in `localStorage` and applied before first paint to prevent flash
- `i18n.js` + `translations.json` for French/English switching

### GreenBot RAG Chatbot
- **Retrieval**: TF-IDF index (scikit-learn, 8 000 features, bigrams) over a `chunks.json` corpus
- **Generation**: Google Gemini `gemini-2.5-flash-lite` with injected field context (recent analyses, parcels, weather)
- Chat sessions and messages persisted in SQLite

### Performance Optimisations
- `torch.inference_mode()` (faster than `no_grad` — disables autograd tape entirely)
- Models loaded lazily on first request + background warmup thread (1 s delay after ASGI bind)
- MJPEG chunk size set to 16 384 bytes to reduce `read()` system calls

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        GREEN Platform                           │
│                                                                 │
│  ┌──────────┐   Wi-Fi / HTTP    ┌───────────────────────────┐  │
│  │  Rover   │ ─────────────────▶│   FastAPI Backend          │  │
│  │ Camera   │  MJPEG stream     │   (uvicorn, port 8000)     │  │
│  │(Arduino  │                   │                            │  │
│  │  Uno Q)  │                   │  ┌─────────────────────┐  │  │
│  └──────────┘                   │  │  EfficientNet-B0    │  │  │
│                                 │  │  (disease, 11 cls)  │  │  │
│                                 │  ├─────────────────────┤  │  │
│                                 │  │  YOLOv8             │  │  │
│                                 │  │  (pest, 2 cls)      │  │  │
│                                 │  ├─────────────────────┤  │  │
│                                 │  │  GreenBot RAG       │  │  │
│                                 │  │  TF-IDF + Gemini    │  │  │
│                                 │  ├─────────────────────┤  │  │
│                                 │  │  SQLite (green.db)  │  │  │
│                                 │  └─────────────────────┘  │  │
│                                 │                            │  │
│                                 │   Serves /frontend/*       │  │
│                                 └──────────────┬────────────┘  │
│                                                │                │
│                                 ┌──────────────▼────────────┐  │
│                                 │   GREEN Web App            │  │
│                                 │   (Vanilla JS, 12 pages)   │  │
│                                 │   Chart.js · Leaflet.js    │  │
│                                 └───────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Request Flow — Camera Analysis

```
Browser  ──GET /api/camera/stream──▶  camera_router
                                          │
                                   MJPEG frame grab
                                          │
                              ┌───────────┴───────────┐
                              │ asyncio.gather         │
                    ┌─────────▼──────┐   ┌────────────▼──────────┐
                    │ EfficientNet   │   │ YOLOv8                │
                    │ Disease class  │   │ Pest bounding boxes    │
                    └─────────┬──────┘   └────────────┬──────────┘
                              └───────────┬───────────┘
                                   Merge results
                                          │
                                   Gemini enrichment
                                   (treatment advice)
                                          │
                                   Save → SQLite
                                          │
                              JSON response to browser
```

---

## 4. AI Models

### Model 1 — Disease Detection (EfficientNet-B0)

| Property | Value |
|---|---|
| File | `Models/best_efficientnet.pth` |
| Architecture | `timm` EfficientNet-B0 (1 280-d features) |
| Input | 224 × 224 RGB |
| Output | 11 softmax classes |
| Inference mode | `torch.inference_mode()` |

**Classes (index order must match training folder sort):**

| Index | Class | Crop |
|---|---|---|
| 0 | Cassava_Mosaic | Cassava |
| 1 | Corn_Brown_Spots | Maize |
| 2 | Corn_Healthy | Maize |
| 3 | Corn_Leaf_Blight | Maize |
| 4 | Corn_Mildew | Maize |
| 5 | Corn_Streak | Maize |
| 6 | Corn_Stripe | Maize |
| 7 | Corn_Yellowing | Maize |
| 8 | Tomato_Brown_Spots | Tomato |
| 9 | Tomato_Blight_Leaf | Tomato |
| 10 | Tomato_Healthy | Tomato |

### ONNX Export

Pre-converted models are available in the `Models/` folder (`model.onnx`, `model.tflite`).

An additional conversion script is provided to export `best.pt` to ONNX at 320 × 320 for optimised edge deployment:

```bash
python convert_to_onnx.py
# Output: best_320.onnx (≈ 11.6 MB, opset 12, FP32, onnxslim simplified)
# Latency: ~68 ms / image on CPU (Core i3)
```

---

## 5. Tech Stack

### Backend
| Layer | Technology |
|---|---|
| Web framework | FastAPI 0.115 + Uvicorn 0.32 |
| Database ORM | SQLAlchemy 2.0 (SQLite) |
| Authentication | `python-jose` JWT + `bcrypt` 4.x |
| Disease AI | PyTorch 2.5 + `timm` EfficientNet-B0 |
| Pest AI | Ultralytics YOLOv8 (8.4.38) |
| Chatbot retrieval | scikit-learn TF-IDF |
| Chatbot generation | Google Gemini `gemini-2.5-flash-lite` |
| Weather | OpenWeatherMap REST API |
| Image processing | Pillow |
| HTTP client | httpx + requests |
| Async concurrency | asyncio + ThreadPoolExecutor |

### Frontend
| Layer | Technology |
|---|---|
| Core | Vanilla JavaScript (ES2020, no framework) |
| Styling | CSS custom properties design system |
| Charts | Chart.js 4.x |
| Maps | Leaflet.js 1.9.4 (CartoDB tiles) |
| Fonts | Inter (Google Fonts) |
| Icons | Inline SVG |
| i18n | Custom `i18n.js` + `translations.json` (FR/EN) |

---

## 6. Project Structure

```
APP/
├── backend/
│   ├── main.py                  # FastAPI app entry point, lifespan, page routes
│   ├── config.py                # All env-dependent settings (loaded from .env)
│   ├── database.py              # SQLAlchemy engine + session factory
│   ├── models.py                # ORM models (User, DiseaseAnalysis, Parcel, Chat…)
│   ├── schemas.py               # Pydantic request/response schemas
│   ├── auth.py                  # JWT creation + get_current_user dependency
│   ├── inference.py             # EfficientNet-B0 disease inference engine
│   ├── yolo_inference.py        # YOLOv8 pest detection engine
│   ├── pest_inference.py        # Legacy pest model (kept for compatibility)
│   ├── requirements.txt         # pip dependencies
│   └── routers/
│       ├── auth_router.py       # POST /api/auth/register, /login, /me
│       ├── analysis_router.py   # GET/POST /api/analysis/* (history, upload)
│       ├── camera_router.py     # GET /api/camera/stream, /capture
│       ├── drone_router.py      # Legacy drone endpoints (redirects to camera)
│       ├── dashboard_router.py  # GET /api/dashboard/stats, /trends
│       ├── parcel_router.py     # CRUD /api/parcels/*
│       ├── chatbot_router.py    # POST/GET /api/chat/sessions/*
│       ├── weather_router.py    # GET /api/weather/*
│       └── diseases_router.py   # GET /api/diseases (reference DB)
│
├── frontend/
│   ├── index.html               # Login page
│   ├── register.html            # Registration page
│   ├── dashboard.html           # Main KPI dashboard
│   ├── camera.html              # Live rover stream + AI analysis
│   ├── history.html             # Analysis history with filters
│   ├── map.html                 # Interactive parcel map (Leaflet)
│   ├── calendar.html            # Cameroon agricultural calendar
│   ├── diseases.html            # Disease reference database (38 entries)
│   ├── chatbot.html             # GreenBot agronomic assistant
│   ├── economics.html           # Economic scenario simulator
│   ├── benchmark.html           # Local benchmark vs. regional averages
│   ├── marketplace.html         # Input marketplace (coming Q3 2026)
│   ├── profile.html             # User profile management
│   ├── settings.html            # App settings (theme, language, camera IP)
│   ├── drone.html               # Legacy page (redirects to camera)
│   ├── css/
│   │   ├── variables.css        # Design system tokens (colors, spacing, radii)
│   │   ├── main.css             # Base resets + typography
│   │   ├── app.css              # App shell (sidebar, header, layout)
│   │   ├── auth.css             # Login / register specific
│   │   └── camera.css           # Camera page specific
│   └── js/
│       ├── api.js               # Centralized API client (all fetch calls)
│       ├── app.js               # App boot, toast notifications, theme
│       ├── layout.js            # App shell injector (sidebar + header)
│       ├── auth.js              # Auth guard + token management
│       ├── utils.js             # Shared utilities
│       ├── i18n.js              # Internationalisation engine
│       └── translations.json    # FR / EN string translations
│
├── rag/
│   ├── chunks.json              # Agronomic knowledge corpus (text chunks)
│   └── embeddings_f32.bin       # Pre-computed embeddings (float32 binary)
│
├── Models/
│   ├── best_efficientnet.pth    # EfficientNet-B0 disease detection weights
│   ├── model.onnx               # ONNX version of the disease/pest model
│   ├── model.tflite             # TFLite version (mobile / edge deployment)
│   └── green.db                 # SQLite database (users, analyses, parcels…)
│
├── diseases.json                # Disease reference database (38 entries)
├── best.pt                      # YOLOv8 pest detection weights
├── best_320.onnx                # ONNX export of best.pt at 320 px (generated)
├── convert_to_onnx.py           # Script: export best.pt → ONNX 320 px
├── .env                         # Local secrets (NOT committed)
├── .gitignore
└── README.md
```

---

## 7. Prerequisites

| Requirement | Minimum version |
|---|---|
| Python | 3.10 |
| pip | 23+ |
| RAM | 4 GB (8 GB recommended — PyTorch + YOLO) |
| Storage | ~2 GB (models + dependencies) |
| Network | Wi-Fi access to rover camera IP |

> **GPU** is optional. All inference runs on CPU by default. For GPU acceleration, install the CUDA build of PyTorch and set `half=True` in `convert_to_onnx.py`.

---

## 8. Installation

### 1. Clone the repository

```bash
git clone https://github.com/TCHOUANANG-dimitri/app.git
cd app
```






### 2. Create a virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate
```

### 3. Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 4. Create the `.env` file

Copy the template below and fill in your actual keys:

```bash
# At the project root (APP/.env)
cp .env.example .env   # if the example exists, otherwise create manually
```

See [Environment Variables](#9-environment-variables) for all options.

### 5. Place the AI model files

The model weights are **not** committed to git (large binary files). The expected layout is:

```
APP/
├── best.pt                          ← YOLOv8 pest weights (root)
└── Models/
    ├── best_efficientnet.pth        ← EfficientNet-B0 disease weights
    ├── model.onnx                   ← ONNX model (disease/pest)
    └── model.tflite                 ← TFLite model (edge/mobile)
```

> **Important:** `config.py` defaults point to the project root for `best.pt` and `best_efficientnet.pth`.
> If you keep them in `Models/`, override the paths via `.env`:
>
> ```dotenv
> MODEL_PATH=Models/best_efficientnet.pth
> YOLO_MODEL_PATH=best.pt
> ```

---

## 9. Environment Variables

Create a `.env` file at the **project root** (`APP/.env`):

```dotenv
# ── Security ────────────────────────────────────────────────
SECRET_KEY=change-this-to-a-random-64-char-string-in-production

# ── Google Gemini (GreenBot chatbot + disease enrichment) ───
# Get your key at: https://aistudio.google.com/app/apikey
GEMINI_API_KEY=your_gemini_api_key_here

# ── OpenWeatherMap (weather widget) ─────────────────────────
# Get your key at: https://openweathermap.org/api
WEATHER_API_KEY=your_openweathermap_key_here

# ── Rover Camera ─────────────────────────────────────────────
# IP of the rover's camera stream (MJPEG over HTTP)
DEFAULT_CAMERA_IP=192.168.1.100
DEFAULT_CAMERA_PORT=8080

# ── Optional overrides ────────────────────────────────────────
# DATABASE_URL=sqlite:///./green.db   # default: project root
# DEBUG=true                          # enables /docs and /redoc
# CORS_ORIGINS=*                      # restrict in production
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | Yes | weak default | JWT signing key — change in production |
| `GEMINI_API_KEY` | Yes | `""` | Google Gemini API key for GreenBot |
| `WEATHER_API_KEY` | No | `""` | OpenWeatherMap key (weather widget) |
| `DEFAULT_CAMERA_IP` | No | `192.168.1.100` | Rover camera IP |
| `DEFAULT_CAMERA_PORT` | No | `8080` | Rover camera HTTP port |
| `DATABASE_URL` | No | SQLite at root | Full SQLAlchemy DB URL |
| `DEBUG` | No | `true` | Enables `/docs` and `/redoc` |

---

## 10. Running the Application

### Start the backend server

```bash
# From the project root
cd backend
uvicorn main:app --reload --port 8000
```

The server will:
1. Create all SQLite tables on first run
2. Start background warmup of EfficientNet + YOLO (parallel, ~1 s delay)
3. Load the RAG TF-IDF index
4. Serve the frontend at `http://localhost:8000`

### Access the app

| URL | Page |
|---|---|
| `http://localhost:8000` | Login |
| `http://localhost:8000/dashboard` | Dashboard |
| `http://localhost:8000/camera` | Live camera |
| `http://localhost:8000/docs` | API docs (DEBUG mode) |

### Health check

```bash
curl http://localhost:8000/api/health
```

```json
{
  "status": "ok",
  "app": "GREEN Agricultural Intelligence Platform",
  "version": "1.0.0",
  "models": {
    "efficientnet": "ready",
    "yolo": "ready",
    "rag_index": "ready"
  }
}
```

---

## 11. Application Pages

### Login & Register (`/`, `/register`)
User authentication with JWT. Password validation, error handling, redirect to dashboard on success.

### Dashboard (`/dashboard`)
Main KPI overview:
- Total analyses, disease rate, parcels, active chat sessions
- Trend chart (last 30 days)
- Recent analyses feed
- Weather widget (current location)

### Camera — Live Rover Feed (`/camera`)
- MJPEG stream from rover (configurable IP/port in Settings)
- **Single-frame capture** → dual AI analysis (disease + pest) in parallel
- Results displayed with confidence bars, treatment recommendations (Gemini)
- Captured frames saved to `frontend/assets/captures/`

### Analysis History (`/history`)
- Paginated analysis log with server-side filters:
  - Source (camera / upload / drone)
  - Result type (disease / healthy / pest)
  - Plant type (free text)
- Each entry shows disease class, confidence, pest detection, severity, GPS coordinates

### Parcel Map (`/map`)
- Leaflet.js map centered on Yaoundé (default)
- CartoDB tiles (light / dark based on theme)
- Add parcels via form + click-on-map coordinate picker
- Color-coded markers by crop (green = maize, amber = cassava, red = tomato)
- Disease analysis dots overlaid from history (colored by severity)

### Agricultural Calendar (`/calendar`)
- Cameroon dual-season crop schedule (Maize S1/S2, Cassava, Tomato S1/S2)
- Visual activity blocks: Planting, Growing, Harvest, Locust Risk
- Monthly agronomic tips (ok / caution / warning)
- Current month highlighted

### Disease Reference (`/diseases`)
- 38-entry knowledge base searchable by name or plant type
- Filter chips: All, Maize, Tomato, Cassava
- Detail panel: scientific name, affected crops, symptoms, recommended actions
- Covers 45+ plant types including cassava, maize, tomato, banana, cocoa, coffee, citrus

### GreenBot Chatbot (`/chatbot`)
- Session-based RAG chatbot powered by Google Gemini
- Context injection: user's recent analyses + parcels + weather
- Persistent chat sessions stored in SQLite
- Suggested starter questions

### Economic Simulator (`/economics`)
- Real-time ROI calculator with interactive sliders:
  - Crop type, cultivated area, expected yield, market price (XAF/kg)
  - Disease incidence %, treatment cost/ha, treatment effectiveness %
- Live output: gross revenue, loss with/without treatment, net profit, ROI %
- 4-scenario Chart.js bar chart (No Disease / No Treatment / With Treatment / Optimal)
- Market reference prices (XAF) for major Cameroonian crops

### Local Benchmark (`/benchmark`)
- Pulls real data from the user's account (scans, parcels, chat sessions)
- Weighted performance score (0–100):
  - Scan frequency 30%, chat engagement 20%, parcel coverage 20%, disease vigilance 30%
- Comparison cards vs. Cameroon regional averages
- Donut chart (disease / healthy / pest distribution)
- Grouped bar chart (scan activity by month)
- Personalised agronomic tips

### Marketplace (`/marketplace`)
- Coming Q3 2026 — online marketplace for agricultural inputs
- Preview: 28 mock products across Seeds, Plant Protection, Fertilizers, Bio-inputs, Equipment
- Category tabs + filter sidebar (crop compatibility, price range, supplier, region)
- Email notification registration for launch

### Profile & Settings (`/profile`, `/settings`)
- Update display name, bio, region
- Change password
- Theme toggle (light/dark), language switcher (FR/EN)
- Camera IP/port configuration
- Notification preferences

---

## 12. REST API Reference

> Full interactive docs available at `http://localhost:8000/docs` (when `DEBUG=true`).

### Authentication

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/register` | Create account |
| `POST` | `/api/auth/login` | Get JWT token |
| `GET` | `/api/auth/me` | Current user info |
| `PUT` | `/api/auth/me` | Update profile |
| `PUT` | `/api/auth/me/password` | Change password |

### Disease Analysis

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/analysis/history` | Paginated history (`?limit&offset&source&result_type&plant_type`) |
| `POST` | `/api/analysis/upload` | Upload image for analysis |
| `GET` | `/api/analysis/{id}` | Get single analysis |
| `DELETE` | `/api/analysis/{id}` | Delete analysis |

### Camera / Rover

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/camera/stream` | MJPEG proxy stream from rover |
| `POST` | `/api/camera/capture` | Grab frame + dual AI analysis |
| `GET` | `/api/camera/status` | Rover connectivity check |

### Parcels

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/parcels` | List user's parcels |
| `POST` | `/api/parcels` | Create parcel |
| `GET` | `/api/parcels/{id}` | Get parcel |
| `PUT` | `/api/parcels/{id}` | Update parcel |
| `DELETE` | `/api/parcels/{id}` | Delete parcel |

### GreenBot

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/chat/sessions` | Create session |
| `GET` | `/api/chat/sessions` | List sessions |
| `GET` | `/api/chat/sessions/{id}` | Get session + messages |
| `POST` | `/api/chat/sessions/{id}/messages` | Send message, get reply |
| `DELETE` | `/api/chat/sessions/{id}` | Delete session |

### Dashboard & Weather

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/dashboard/stats` | KPI summary |
| `GET` | `/api/dashboard/trends` | 30-day trend data |
| `GET` | `/api/weather/current` | Current weather (by coords or city) |
| `GET` | `/api/diseases` | Disease reference list (`?q=&plant=`) |
| `GET` | `/api/diseases/{id}` | Single disease entry |
| `GET` | `/api/health` | Server health + model status |

---

## 13. Database Schema

The SQLite database (`green.db`) is managed by SQLAlchemy. Tables are created automatically on first run.

```
users               — id, email, hashed_password, full_name, region, …
disease_analyses    — id, user_id, plant_type, detected_disease, confidence,
                      severity, pest_detected, pest_confidence, pest_severity,
                      source, latitude, longitude, image_path, created_at
parcels             — id, user_id, name, crop_type, area_ha, region,
                      latitude, longitude, description, created_at
chat_sessions       — id, user_id, title, created_at, updated_at
chat_messages       — id, session_id, role (user/assistant), content, created_at
```

---

## 14. ONNX Export

To convert the YOLOv8 pest model to ONNX for edge deployment (Raspberry Pi, Jetson Nano, etc.):

```bash
# From the project root — no need to activate backend venv if ultralytics is installed globally
python convert_to_onnx.py
```

**Output:** `best_320.onnx`

| Property | Value |
|---|---|
| Resolution | 320 × 320 px |
| Opset | 12 (broad runtime compatibility) |
| Precision | FP32 |
| Size | ~11.6 MB |
| Simplified | Yes (`onnxslim`) |
| Input | `images` — shape `(1, 3, 320, 320)` |
| Output | `output0` — shape `(1, 6, 2100)` |
| CPU latency | ~68 ms / frame (Intel Core i3) |

To run inference with the ONNX model:

```python
import onnxruntime as ort
import numpy as np

sess = ort.InferenceSession("best_320.onnx")
img  = np.zeros((1, 3, 320, 320), dtype=np.float32)  # replace with real frame
out  = sess.run(None, {"images": img})
# out[0].shape → (1, 6, 2100)
# 6 = [x_center, y_center, width, height, conf_class0, conf_class1]
```

---

## 15. Roadmap

| Feature | Status |
|---|---|
| EfficientNet disease detection | Done |
| YOLOv8 pest detection | Done |
| Parallel dual-model inference | Done |
| JWT authentication | Done |
| Live rover camera stream | Done |
| Analysis history with filters | Done |
| Parcel management (CRUD + map) | Done |
| GreenBot RAG chatbot | Done |
| Agricultural calendar | Done |
| Disease reference database | Done |
| Economic scenario simulator | Done |
| Local benchmark | Done |
| ONNX export script | Done |
| Marketplace backend | Q3 2026 |
| Mobile app (React Native) | Planned |
| ONNX runtime integration | Planned |
| Multi-user farm management | Planned |
| Offline mode (PWA) | Planned |

---

## Author

**TCHOUANANG DIMITRI**
Agricultural AI Platform — Cameroon
GitHub: [@TCHOUANANG-dimitri](https://github.com/TCHOUANANG-dimitri)

---

*GREEN is built for field conditions — designed to work on low-bandwidth connections, CPU-only hardware, and with crops and diseases specific to Central and West Africa.*
