# Automate - Smart Admission AI Platform

A modern full-stack application for automated student admission document extraction, verification, and batch management.

---

## 📁 Repository Structure

```
Automate/
├── Backend/                    # FastAPI Backend Application
│   ├── app/                    # Application source code
│   │   ├── api/                # FastAPI routes & endpoint controllers
│   │   ├── core/               # App configuration & security settings
│   │   ├── db/                 # Database initialization & MongoDB models
│   │   ├── models/             # Beanie ODM document models
│   │   ├── repositories/       # Data access repositories
│   │   ├── schemas/            # Pydantic schemas / DTOs
│   │   ├── services/           # Business logic & AI/OCR services
│   │   └── utils/              # Helper utilities
│   ├── test/                   # Pytest test suite
│   ├── uploads/                # File storage for uploads, templates & backups
│   ├── .env                    # Backend environment settings
│   ├── pyrefly.json            # Pyrefly Python language server config
│   ├── pyrightconfig.json      # Pyright type checker config
│   └── requirements.txt        # Python package dependencies
│
├── Frontend/                   # React + TypeScript + Vite Frontend
│   ├── src/                    # React source code
│   │   ├── assets/             # Images & static assets
│   │   ├── components/         # Reusable UI components
│   │   ├── layouts/            # Page layout wrappers
│   │   ├── pages/              # Views and pages
│   │   ├── routes/             # App routing and protection
│   │   ├── services/           # Axios API services
│   │   ├── store/              # Zustand state management
│   │   └── types/              # TypeScript interface definitions
│   ├── public/                 # Static public files
│   ├── .env                    # Frontend environment settings
│   ├── package.json            # NPM package dependencies
│   └── vite.config.ts          # Vite build configuration
│
├── .gitignore                  # Git ignore rules for root, Backend & Frontend
└── README.md                   # Project documentation
```

---

## 🚀 Getting Started

### 1. Backend Setup

```bash
cd Backend
# Activate Virtual Environment (Windows)
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run Development Server
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend Setup

```bash
cd Frontend
# Install dependencies
npm install

# Run Development Server
npm run dev
```
