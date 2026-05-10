"""
InfoShare - Cloud-Based Photo Sharing Platform
FastAPI Backend with Azure SQL + Azure Blob Storage
"""

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import uvicorn
import jwt
import bcrypt
import pyodbc
import uuid
import os
import io
from datetime import datetime, timedelta
from typing import Optional, List
from PIL import Image
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv
import logging

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────
SECRET_KEY        = os.getenv("SECRET_KEY", "infoshare-super-secret-2025")
ALGORITHM         = "HS256"
TOKEN_EXPIRE_DAYS = 7

AZURE_SQL_SERVER   = os.getenv("AZURE_SQL_SERVER")
AZURE_SQL_DATABASE = os.getenv("AZURE_SQL_DATABASE")
AZURE_SQL_USER     = os.getenv("AZURE_SQL_USER")
AZURE_SQL_PASSWORD = os.getenv("AZURE_SQL_PASSWORD")

AZURE_STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
AZURE_CONTAINER_NAME            = os.getenv("AZURE_CONTAINER_NAME", "infoshare-photos")

# ─── Database ─────────────────────────────────────────────────────────────────
def get_db_connection():
    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={AZURE_SQL_SERVER};"
        f"DATABASE={AZURE_SQL_DATABASE};"
        f"UID={AZURE_SQL_USER};"
        f"PWD={AZURE_SQL_PASSWORD};"
        f"Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str)


def init_db():
    """Create tables if they don't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='users' AND xtype='U')
        CREATE TABLE users (
            id          UNIQUEIDENTIFIER DEFAULT NEWID() PRIMARY KEY,
            username    NVARCHAR(50)  UNIQUE NOT NULL,
            email       NVARCHAR(100) UNIQUE NOT NULL,
            password    NVARCHAR(255) NOT NULL,
            role        NVARCHAR(10)  NOT NULL DEFAULT 'consumer',  -- 'admin' or 'consumer'
            created_at  DATETIME      DEFAULT GETDATE()
        )
    """)
    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='photos' AND xtype='U')
        CREATE TABLE photos (
            id           UNIQUEIDENTIFIER DEFAULT NEWID() PRIMARY KEY,
            user_id      UNIQUEIDENTIFIER NOT NULL REFERENCES users(id),
            title        NVARCHAR(200) NOT NULL,
            caption      NVARCHAR(500),
            location     NVARCHAR(200),
            people       NVARCHAR(500),
            blob_url     NVARCHAR(500) NOT NULL,
            thumb_url    NVARCHAR(500),
            upload_date  DATETIME DEFAULT GETDATE(),
            view_count   INT DEFAULT 0
        )
    """)
    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='comments' AND xtype='U')
        CREATE TABLE comments (
            id         UNIQUEIDENTIFIER DEFAULT NEWID() PRIMARY KEY,
            photo_id   UNIQUEIDENTIFIER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
            user_id    UNIQUEIDENTIFIER NOT NULL REFERENCES users(id),
            content    NVARCHAR(1000) NOT NULL,
            created_at DATETIME DEFAULT GETDATE()
        )
    """)
    cursor.execute("""
        IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ratings' AND xtype='U')
        CREATE TABLE ratings (
            id       UNIQUEIDENTIFIER DEFAULT NEWID() PRIMARY KEY,
            photo_id UNIQUEIDENTIFIER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
            user_id  UNIQUEIDENTIFIER NOT NULL REFERENCES users(id),
            score    INT NOT NULL CHECK (score BETWEEN 1 AND 5),
            UNIQUE (photo_id, user_id)
        )
    """)
    conn.commit()
    conn.close()
    logger.info("Database initialised ✓")


# ─── Blob Storage ─────────────────────────────────────────────────────────────
def get_blob_client():
    return BlobServiceClient.from_connection_string(AZURE_STORAGE_CONNECTION_STRING)


def upload_image(file_bytes: bytes, filename: str, content_type: str) -> tuple[str, str]:
    """Upload original + thumbnail; return (blob_url, thumb_url)."""
    blob_client  = get_blob_client()
    container    = blob_client.get_container_client(AZURE_CONTAINER_NAME)

    # Create container with public access if it doesn't exist
    try:
        container.create_container(public_access="blob")
    except Exception:
        pass

    ext      = filename.rsplit(".", 1)[-1].lower()
    uid      = str(uuid.uuid4())
    blob_name  = f"photos/{uid}.{ext}"
    thumb_name = f"thumbs/{uid}.{ext}"

    # Upload original
    container.upload_blob(blob_name, file_bytes, content_settings={"content_type": content_type}, overwrite=True)

    # Generate & upload thumbnail
    img   = Image.open(io.BytesIO(file_bytes))
    img.thumbnail((400, 400))
    buf   = io.BytesIO()
    fmt   = "JPEG" if ext in ("jpg", "jpeg") else "PNG"
    img.save(buf, format=fmt)
    buf.seek(0)
    container.upload_blob(thumb_name, buf.read(), content_settings={"content_type": content_type}, overwrite=True)

    base     = f"https://{blob_client.account_name}.blob.core.windows.net/{AZURE_CONTAINER_NAME}"
    return f"{base}/{blob_name}", f"{base}/{thumb_name}"


# ─── JWT ─────────────────────────────────────────────────────────────────────
security = HTTPBearer()

def create_token(user_id: str, role: str) -> str:
    payload = {
        "sub":  user_id,
        "role": role,
        "exp":  datetime.utcnow() + timedelta(days=TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    return decode_token(credentials.credentials)


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ─── App ──────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(
    title="InfoShare API",
    description="Cloud-based photo sharing platform – COM769 Coursework 2",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/auth/register", tags=["Auth"])
def register(
    username: str = Form(...),
    email:    str = Form(...),
    password: str = Form(...),
):
    """Register a new consumer account."""
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    conn   = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, 'consumer')",
            username, email, hashed,
        )
        conn.commit()
        return {"message": "Registered successfully"}
    except pyodbc.IntegrityError:
        raise HTTPException(status_code=400, detail="Username or email already exists")
    finally:
        conn.close()


@app.post("/api/auth/login", tags=["Auth"])
def login(
    username: str = Form(...),
    password: str = Form(...),
):
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, password, role FROM users WHERE username = ?", username)
    row = cursor.fetchone()
    conn.close()
    if not row or not bcrypt.checkpw(password.encode(), row[1].encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(str(row[0]), row[2])
    return {"access_token": token, "token_type": "bearer", "role": row[2]}


@app.post("/api/auth/create-admin", tags=["Auth"])
def create_admin(
    username: str = Form(...),
    email:    str = Form(...),
    password: str = Form(...),
    admin_secret: str = Form(...),
):
    """Create an admin account using a secret key (set ADMIN_SECRET env var)."""
    expected = os.getenv("ADMIN_SECRET", "infoshare-admin-2025")
    if admin_secret != expected:
        raise HTTPException(status_code=403, detail="Wrong admin secret")
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    conn   = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, 'admin')",
            username, email, hashed,
        )
        conn.commit()
        return {"message": "Admin account created"}
    except pyodbc.IntegrityError:
        raise HTTPException(status_code=400, detail="Username or email already exists")
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# PHOTO ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/photos/upload", tags=["Photos"])
async def upload_photo(
    title:    str        = Form(...),
    caption:  str        = Form(""),
    location: str        = Form(""),
    people:   str        = Form(""),
    file:     UploadFile = File(...),
    user:     dict       = Depends(require_admin),
):
    """Upload a photo (admin/creator only)."""
    if file.content_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
        raise HTTPException(status_code=400, detail="Only image files are allowed")

    contents = await file.read()
    if len(contents) > 16 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 16 MB)")

    blob_url, thumb_url = upload_image(contents, file.filename, file.content_type)

    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO photos (user_id, title, caption, location, people, blob_url, thumb_url)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        user["sub"], title, caption, location, people, blob_url, thumb_url,
    )
    conn.commit()
    conn.close()
    return {"message": "Photo uploaded successfully", "blob_url": blob_url}


@app.get("/api/photos", tags=["Photos"])
def list_photos(
    search: Optional[str] = None,
    page:   int           = 1,
    limit:  int           = 12,
):
    """List/search photos (public)."""
    offset = (page - 1) * limit
    conn   = get_db_connection()
    cursor = conn.cursor()

    if search:
        like = f"%{search}%"
        cursor.execute(
            """SELECT p.id, p.title, p.caption, p.location, p.people,
                      p.blob_url, p.thumb_url, p.upload_date, p.view_count,
                      u.username,
                      ISNULL(AVG(CAST(r.score AS FLOAT)), 0) AS avg_rating,
                      COUNT(DISTINCT r.id) AS rating_count
               FROM photos p
               JOIN users  u ON p.user_id = u.id
               LEFT JOIN ratings r ON r.photo_id = p.id
               WHERE p.title LIKE ? OR p.caption LIKE ?
                  OR p.location LIKE ? OR p.people LIKE ?
               GROUP BY p.id, p.title, p.caption, p.location, p.people,
                        p.blob_url, p.thumb_url, p.upload_date, p.view_count, u.username
               ORDER BY p.upload_date DESC
               OFFSET ? ROWS FETCH NEXT ? ROWS ONLY""",
            like, like, like, like, offset, limit,
        )
    else:
        cursor.execute(
            """SELECT p.id, p.title, p.caption, p.location, p.people,
                      p.blob_url, p.thumb_url, p.upload_date, p.view_count,
                      u.username,
                      ISNULL(AVG(CAST(r.score AS FLOAT)), 0) AS avg_rating,
                      COUNT(DISTINCT r.id) AS rating_count
               FROM photos p
               JOIN users  u ON p.user_id = u.id
               LEFT JOIN ratings r ON r.photo_id = p.id
               GROUP BY p.id, p.title, p.caption, p.location, p.people,
                        p.blob_url, p.thumb_url, p.upload_date, p.view_count, u.username
               ORDER BY p.upload_date DESC
               OFFSET ? ROWS FETCH NEXT ? ROWS ONLY""",
            offset, limit,
        )

    rows = cursor.fetchall()
    conn.close()

    photos = []
    for r in rows:
        photos.append({
            "id":           str(r[0]),
            "title":        r[1],
            "caption":      r[2],
            "location":     r[3],
            "people":       r[4],
            "blob_url":     r[5],
            "thumb_url":    r[6],
            "upload_date":  r[7].isoformat() if r[7] else None,
            "view_count":   r[8],
            "uploader":     r[9],
            "avg_rating":   round(float(r[10]), 1),
            "rating_count": r[11],
        })
    return {"photos": photos, "page": page, "limit": limit}


@app.get("/api/photos/{photo_id}", tags=["Photos"])
def get_photo(photo_id: str):
    """Get a single photo and increment view count."""
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE photos SET view_count = view_count + 1 WHERE id = ?", photo_id)
    cursor.execute(
        """SELECT p.id, p.title, p.caption, p.location, p.people,
                  p.blob_url, p.thumb_url, p.upload_date, p.view_count,
                  u.username,
                  ISNULL(AVG(CAST(r.score AS FLOAT)), 0) AS avg_rating,
                  COUNT(DISTINCT r.id) AS rating_count
           FROM photos p
           JOIN users u ON p.user_id = u.id
           LEFT JOIN ratings r ON r.photo_id = p.id
           WHERE p.id = ?
           GROUP BY p.id, p.title, p.caption, p.location, p.people,
                    p.blob_url, p.thumb_url, p.upload_date, p.view_count, u.username""",
        photo_id,
    )
    row = cursor.fetchone()
    conn.commit()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Photo not found")

    return {
        "id":           str(row[0]),
        "title":        row[1],
        "caption":      row[2],
        "location":     row[3],
        "people":       row[4],
        "blob_url":     row[5],
        "thumb_url":    row[6],
        "upload_date":  row[7].isoformat() if row[7] else None,
        "view_count":   row[8],
        "uploader":     row[9],
        "avg_rating":   round(float(row[10]), 1),
        "rating_count": row[11],
    }


@app.delete("/api/photos/{photo_id}", tags=["Photos"])
def delete_photo(photo_id: str, user: dict = Depends(require_admin)):
    """Delete a photo (admin only)."""
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM photos WHERE id = ?", photo_id)
    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="Photo not found")
    conn.commit()
    conn.close()
    return {"message": "Photo deleted"}


# ═══════════════════════════════════════════════════════════════════════════════
# COMMENT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/photos/{photo_id}/comments", tags=["Comments"])
def add_comment(
    photo_id: str,
    content:  str  = Form(...),
    user:     dict = Depends(get_current_user),
):
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO comments (photo_id, user_id, content) VALUES (?, ?, ?)",
        photo_id, user["sub"], content,
    )
    conn.commit()
    conn.close()
    return {"message": "Comment added"}


@app.get("/api/photos/{photo_id}/comments", tags=["Comments"])
def get_comments(photo_id: str):
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT c.id, c.content, c.created_at, u.username
           FROM comments c JOIN users u ON c.user_id = u.id
           WHERE c.photo_id = ?
           ORDER BY c.created_at DESC""",
        photo_id,
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {"id": str(r[0]), "content": r[1], "created_at": r[2].isoformat(), "username": r[3]}
        for r in rows
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# RATING ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/photos/{photo_id}/rate", tags=["Ratings"])
def rate_photo(
    photo_id: str,
    score:    int  = Form(...),
    user:     dict = Depends(get_current_user),
):
    if not 1 <= score <= 5:
        raise HTTPException(status_code=400, detail="Score must be between 1 and 5")
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """IF EXISTS (SELECT 1 FROM ratings WHERE photo_id=? AND user_id=?)
               UPDATE ratings SET score=? WHERE photo_id=? AND user_id=?
           ELSE
               INSERT INTO ratings (photo_id, user_id, score) VALUES (?,?,?)""",
        photo_id, user["sub"],
        score, photo_id, user["sub"],
        photo_id, user["sub"], score,
    )
    conn.commit()
    conn.close()
    return {"message": "Rating saved"}


# ═══════════════════════════════════════════════════════════════════════════════
# STATS ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/stats", tags=["Stats"])
def get_stats():
    conn   = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM photos")
    total_photos = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE role='consumer'")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(view_count) FROM photos")
    total_views = cursor.fetchone()[0] or 0
    cursor.execute("SELECT COUNT(*) FROM comments")
    total_comments = cursor.fetchone()[0]
    conn.close()
    return {
        "total_photos":   total_photos,
        "total_users":    total_users,
        "total_views":    total_views,
        "total_comments": total_comments,
    }


@app.get("/", tags=["Health"])
def health():
    return {"status": "ok", "app": "InfoShare", "version": "1.0.0"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
