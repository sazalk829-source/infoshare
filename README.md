# InfoShare – Cloud-Native Photo Sharing Platform
### COM769 Scalable Advanced Software Systems · Coursework 2

A scalable, cloud-native photo sharing web application built with **FastAPI**, deployed on **Microsoft Azure**, using **Azure SQL Database**, **Azure Blob Storage**, and **GitHub Actions CI/CD**.

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          FRONTEND                               │
│            Azure Static Web Apps (HTML/CSS/JS)                  │
│                   Tailwind CSS + Vanilla JS                     │
└────────────────────────────┬────────────────────────────────────┘
                             │ REST API calls
┌────────────────────────────▼────────────────────────────────────┐
│                          BACKEND                                │
│              Azure Web App Service (FastAPI + Uvicorn)          │
│              Auto-scaling PaaS · SSL · GitHub CD                │
└──────────┬─────────────────────────────────────┬───────────────┘
           │                                     │
┌──────────▼──────────┐             ┌────────────▼────────────────┐
│   Azure SQL Database│             │    Azure Blob Storage        │
│  (Users, Photos,    │             │  (Original images +          │
│   Comments, Ratings)│             │   400×400 thumbnails)        │
└─────────────────────┘             └─────────────────────────────┘
           │
┌──────────▼──────────┐
│  GitHub Actions      │
│  CI/CD Pipeline      │
│  (Test → Deploy)     │
└─────────────────────┘
```

---

## 📁 Project Structure

```
infoshare/
├── backend/
│   ├── main.py              # FastAPI application (all endpoints)
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── startup.sh           # Azure Web App startup script
│   ├── .env.example         # Environment variable template
│   └── tests/
│       └── test_api.py      # Pytest test suite
├── frontend/
│   └── index.html           # Complete SPA frontend
├── .github/
│   └── workflows/
│       └── ci-cd.yml        # GitHub Actions pipeline
├── docker-compose.yml       # Local dev environment
└── README.md
```

---

## 🚀 Quick Start (Local Development)

### Prerequisites

- Python 3.11+
- [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)
- An Azure account (free tier works)

### Step 1 – Clone & set up environment

```bash
git clone https://github.com/YOUR_USERNAME/infoshare.git
cd infoshare/backend
cp .env.example .env
# Edit .env with your Azure credentials
```

### Step 2 – Install dependencies

```bash
pip install -r requirements.txt
```

### Step 3 – Run the backend

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API is now at **http://localhost:8000**  
Interactive docs: **http://localhost:8000/docs**

### Step 4 – Open the frontend

Open `frontend/index.html` in a browser (or serve with any static server).

> **Important:** If you're using CORS with a local file, either serve the frontend via a local HTTP server or update the `API` constant in `index.html` to match your backend URL.

```bash
# Simple local static server
cd frontend
python -m http.server 3000
# Then open http://localhost:3000
```

---

## ☁️ Azure Deployment (Step-by-Step)

### 1. Create Azure Resources

```bash
# Login
az login

# Create Resource Group
az group create --name infoshare-rg --location uksouth

# Create SQL Server
az sql server create \
  --name infoshare-sql \
  --resource-group infoshare-rg \
  --location uksouth \
  --admin-user sqladmin \
  --admin-password "YourP@ssword123"

# Create SQL Database (Free tier)
az sql db create \
  --resource-group infoshare-rg \
  --server infoshare-sql \
  --name infoshare \
  --edition GeneralPurpose \
  --compute-model Serverless \
  --family Gen5 \
  --capacity 1

# Allow Azure services through firewall
az sql server firewall-rule create \
  --resource-group infoshare-rg \
  --server infoshare-sql \
  --name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0

# Create Storage Account
az storage account create \
  --name infosharestorage \
  --resource-group infoshare-rg \
  --location uksouth \
  --sku Standard_LRS

# Create Web App (Python 3.11)
az webapp create \
  --resource-group infoshare-rg \
  --plan infoshare-plan \
  --name infoshare-api \
  --runtime "PYTHON:3.11" \
  --sku B1

# Set startup command
az webapp config set \
  --resource-group infoshare-rg \
  --name infoshare-api \
  --startup-file "startup.sh"
```

### 2. Configure App Settings

```bash
az webapp config appsettings set \
  --resource-group infoshare-rg \
  --name infoshare-api \
  --settings \
    AZURE_SQL_SERVER="infoshare-sql.database.windows.net" \
    AZURE_SQL_DATABASE="infoshare" \
    AZURE_SQL_USER="sqladmin" \
    AZURE_SQL_PASSWORD="YourP@ssword123" \
    AZURE_STORAGE_CONNECTION_STRING="<your-connection-string>" \
    AZURE_CONTAINER_NAME="infoshare-photos" \
    SECRET_KEY="your-long-random-secret" \
    ADMIN_SECRET="your-admin-secret"
```

### 3. Deploy Frontend to Azure Static Web Apps

```bash
az staticwebapp create \
  --name infoshare-web \
  --resource-group infoshare-rg \
  --source https://github.com/YOUR_USERNAME/infoshare \
  --location "westeurope" \
  --branch main \
  --app-location "frontend" \
  --login-with-github
```

### 4. Set up GitHub Actions CI/CD

In your GitHub repository → **Settings → Secrets and variables → Actions**, add:

| Secret | Value |
|--------|-------|
| `AZURE_WEBAPP_PUBLISH_PROFILE` | Download from Azure Portal → Web App → Get publish profile |
| `AZURE_STATIC_WEB_APPS_API_TOKEN` | From `az staticwebapp secrets list` |

Push to `main` to trigger automatic deployment.

---

## 🔐 First Admin Account

After deployment, create your admin account via the API:

```bash
curl -X POST https://infoshare-api.azurewebsites.net/api/auth/create-admin \
  -F "username=admin" \
  -F "email=admin@example.com" \
  -F "password=SecurePass123" \
  -F "admin_secret=your-admin-secret"
```

> The admin secret is the value of `ADMIN_SECRET` in your environment.

---

## 🐳 Docker (Local with Docker Compose)

```bash
# Start everything (API + SQL Server + Nginx)
docker-compose up -d

# Stop
docker-compose down
```

Make sure to update the `.env` file inside `backend/` before running.

---

## 🧪 Running Tests

```bash
cd backend
pip install pytest httpx pytest-asyncio
pytest tests/ -v
```

---

## 📡 API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/` | — | Health check |
| `POST` | `/api/auth/register` | — | Register consumer account |
| `POST` | `/api/auth/login` | — | Login (returns JWT) |
| `POST` | `/api/auth/create-admin` | Admin secret | Create admin account |
| `GET` | `/api/photos` | — | List/search photos |
| `GET` | `/api/photos/{id}` | — | Get photo + increment view |
| `POST` | `/api/photos/upload` | Admin | Upload photo with metadata |
| `DELETE` | `/api/photos/{id}` | Admin | Delete photo |
| `GET` | `/api/photos/{id}/comments` | — | Get comments |
| `POST` | `/api/photos/{id}/comments` | User | Post comment |
| `POST` | `/api/photos/{id}/rate` | User | Rate photo (1–5) |
| `GET` | `/api/stats` | — | Platform statistics |
| `GET` | `/docs` | — | Swagger interactive docs |

---

## 🔑 User Roles

| Role | Can Do |
|------|--------|
| **Admin** | Upload photos, set metadata, delete photos, view dashboard |
| **Consumer** | Browse, search, view, comment, and rate photos |
| **Guest** | Browse and search only |

---

## ⚙️ Advanced Features

1. **JWT Authentication** – Stateless token-based auth with role-based access control
2. **Automatic Thumbnail Generation** – Pillow resizes images to 400×400px on upload
3. **CI/CD Pipeline** – GitHub Actions auto-tests and deploys on every push to `main`
4. **Azure Blob Storage** – Scalable object storage with public read access
5. **Full-text Search** – Across title, caption, location, and people fields
6. **Real-time View Counter** – Updated on every photo view

---

## 📊 Scalability

- **Horizontal scaling**: Azure Web App auto-scales on load
- **Stateless API**: JWT tokens enable multi-instance deployment
- **Serverless DB**: Azure SQL Serverless scales compute automatically
- **Blob Storage**: Virtually unlimited, replicated photo storage
- **CDN-ready**: Blob Storage URLs can be fronted by Azure CDN
- **Pagination**: All list endpoints paginated (default 12/page)

---

## 🛠 Technologies

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI 0.115, Python 3.11, Uvicorn |
| Database | Azure SQL Database (SQL Server) via pyodbc |
| Storage | Azure Blob Storage |
| Auth | JWT (PyJWT), bcrypt password hashing |
| Image processing | Pillow |
| Frontend | HTML5, Tailwind CSS, Vanilla JS |
| Hosting | Azure Web App Service (PaaS) |
| Static hosting | Azure Static Web Apps |
| CI/CD | GitHub Actions |
| Containers | Docker, Docker Compose |

---

## 📝 References

[1] Microsoft Corporation, *Cloud Application Architecture Guide*, Microsoft Press, 2017.  
[2] Azure Architecture Centre (2024), Microsoft. https://learn.microsoft.com/en-us/azure/architecture/  
[3] Ramírez, S., *FastAPI Documentation*, 2024. https://fastapi.tiangolo.com  
[4] Microsoft, *Azure Blob Storage documentation*, 2024. https://learn.microsoft.com/en-us/azure/storage/blobs/  
[5] IEEE, "IEEE Citation Reference." https://www.ieee.org/documents/ieeecitationref.pdf  
