import os
import requests
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
import google.generativeai as genai
import pytesseract
from PIL import Image
import io

# --- Load API keys safely ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Validate keys
if not GOOGLE_API_KEY or not SEARCH_ENGINE_ID:
    print("⚠ Google API Key or Search Engine ID not found. Google searches will not work.")
if not GEMINI_API_KEY:
    print("⚠ Gemini API Key not found. Fact-checking will not work.")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# --- Google Search Helper ---
def search_the_web_google(query):
    if not GOOGLE_API_KEY or not SEARCH_ENGINE_ID:
        return []  # skip search if key missing
    try:
        service = build("customsearch", "v1", developerKey=GOOGLE_API_KEY)
        res = service.cse().list(q=query, cx=SEARCH_ENGINE_ID, num=3).execute()
        return res.get('items', [])
    except Exception as e:
        print(f"Google API search error: {e}")
        return []

# --- Scraping ---
def scrape_url_content(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        paragraphs = soup.find_all('p')
        return ' '.join([p.get_text() for p in paragraphs])[:2500]
    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return ""

# --- OCR ---
def get_text_from_image(image_bytes):
    try:
        image = Image.open(io.BytesIO(image_bytes))
        return pytesseract.image_to_string(image).strip()
    except Exception as e:
        print(f"OCR error: {e}")
        return None

# --- Intent Recognition ---
def recognize_intent(user_input):
    greetings = ['hello', 'hi', 'vanakkam', 'hai', 'good morning', 'good evening']
    if user_input.strip().lower() in greetings:
        return "greeting"

    if not GEMINI_API_KEY:
        return "fact_checking_claim"  # fallback

    try:
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        prompt = f"""
        Analyze the user input and classify it into:
        1. fact_checking_claim
        2. general_question
        User Input: "{user_input}"
        Category:
        """
        response = model.generate_content(prompt)
        intent = response.text.strip().lower().replace('"', "")
        return 'fact_checking_claim' if 'fact_checking_claim' in intent else 'general_question'
    except Exception as e:
        print(f"Intent recognition error: {e}")
        return "fact_checking_claim"

# --- Fact-Checking ---
def verify_misinformation(claim):
    search_results = search_the_web_google(claim)
    if not search_results:
        return "Error: Could not fetch search results. Check API keys or quota."

    context, sources = "", []
    for i, result in enumerate(search_results):
        url = result.get("link")
        if url:
            content = scrape_url_content(url)
            context += f"Source [{i+1}]: {result.get('title')}\nURL: {url}\nContent: {content}\n\n"
            sources.append(url)

    if not GEMINI_API_KEY:
        return "Google search fetched content, but Gemini API key missing for analysis."

    try:
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        prompt = f"""
        You are a multilingual Misinformation Analyst.
        USER CLAIM: "{claim}"
        CONTEXT: {context}
        INSTRUCTIONS:
        1.Analyze the language of the *USER'S CLAIM.SPECIAL RULE:If the text is in the Roman alphabet,you MUST assume the language is **ENGLISH*
        2. Analyze context and give verdict.
        3. Report format: "Verdict: [Factually True/False/Misleading/Unverified]"
        Sources: {sources[:3]}
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Gemini analysis error: {e}"

# --- Main Handler ---
def freaksearch_handler(user_input, image_bytes=None):
    if image_bytes:
        text = get_text_from_image(image_bytes)
        if not text:
            return "Error: No text read from image."
    else:
        text = user_input

    if not text:
        return "Error: No input provided."

    intent = recognize_intent(text)
    if intent == "greeting":
        return "Hello! I am FreakSearch. Provide a claim to verify."
    elif intent == "fact_checking_claim":
        return verify_misinformation(text)
    else:
        return "I am FreakSearch. I only verify news claims."
