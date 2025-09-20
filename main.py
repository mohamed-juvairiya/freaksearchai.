# backend/main.py

import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))  # ensures current folder is in path
from dotenv import load_dotenv
load_dotenv()

from model import freaksearch_handler, get_text_from_image

from pathlib import Path
import mysql.connector
from mysql.connector import Error
from passlib.context import CryptContext

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import List

# Import your custom AI model
from model import freaksearch_handler, get_text_from_image  # Assuming you have OCR support

# --- Password hashing ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- Database configuration ---
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

# --- Uploads directory ---
BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

# --- FastAPI app ---
app = FastAPI()


# --- Database connection ---
def get_db_connection():
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        if conn.is_connected():
            return conn
    except Error as e:
        print(f"❌ DB connection error: {e}")
        return None


# --- Password helpers ---
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password):
    return pwd_context.hash(password)


# --- Pydantic models ---
class UserRegister(BaseModel):
    username: str
    password: str
    email: str
    full_name: str


class UserLogin(BaseModel):
    username: str
    password: str


class ChatPart(BaseModel):
    text: str


class ChatMessage(BaseModel):
    role: str
    parts: List[ChatPart]


class ChatRequest(BaseModel):
    message: str
    chatHistory: List[ChatMessage]


# --- User auth endpoints ---
@app.post("/api/register")
async def register_user(user: UserRegister):
    conn = get_db_connection()
    if not conn:
        return JSONResponse(status_code=500, content={"detail": "Database connection failed."})
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = %s OR email = %s", (user.username, user.email))
        if cursor.fetchone():
            return JSONResponse(status_code=400, content={"detail": "Username or email already exists."})

        hashed_pw = hash_password(user.password)
        cursor.execute(
            "INSERT INTO users (username, password_hash, email, full_name, status) VALUES (%s, %s, %s, %s, %s)",
            (user.username, hashed_pw, user.email, user.full_name, "active")
        )
        conn.commit()
        return {"message": f"User '{user.username}' registered successfully."}
    finally:
        conn.close()


@app.post("/api/login")
async def login_user(user: UserLogin):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed.")
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE username = %s", (user.username,))
    db_user = cursor.fetchone()
    conn.close()

    if not db_user or not verify_password(user.password, db_user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    if db_user["status"] != "active":
        raise HTTPException(status_code=403, detail="User account is inactive.")

    return {
        "message": "Login successful!",
        "user": {
            "id": db_user["user_id"],
            "username": db_user["username"],
            "email": db_user["email"],
            "full_name": db_user["full_name"],
            "status": db_user["status"]
        }
    }


# --- Chat history ---
@app.get("/api/chat-history")
async def get_chat_history(user_id: int):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed.")

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, input_text FROM submission WHERE user_id = %s ORDER BY id DESC", (user_id,))
    submissions = cursor.fetchall()
    conn.close()
    return {"history": submissions}


@app.post("/api/save-chat")
async def save_chat(user_id: int = Form(...), input_text: str = Form(...)):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed.")

    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO submission (user_id, input_text) VALUES (%s, %s)", (user_id, input_text))
        conn.commit()
        return {"message": "Chat saved successfully", "id": cursor.lastrowid}
    finally:
        conn.close()


# --- Chatbot endpoint (only your AI) ---
@app.post("/api/chatbot")
async def handle_chat(request: ChatRequest):
    user_message = request.message
    final_response = freaksearch_handler(user_message)
    return {"text": final_response}


# --- File upload endpoint ---
@app.post("/api/upload-media")
async def upload_media(file: UploadFile = File(...)):
    file_path = UPLOADS_DIR / file.filename
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())
    return {"message": f"File '{file.filename}' uploaded successfully."}


# --- Serve frontend ---
@app.get("/")
async def serve_landing_page():
    return FileResponse(BASE_DIR / "landing.html")


@app.get("/chat")
async def serve_chat_page():
    return FileResponse(BASE_DIR / "chat.html")
