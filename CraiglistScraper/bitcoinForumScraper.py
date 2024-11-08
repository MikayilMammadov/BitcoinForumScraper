import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
import time
import sqlite3
from docx import Document
import re
import os
from dotenv import load_dotenv

load_dotenv("C:\\PythonProjects\\CraiglistScraper\\Keys.env")
API_KEY = os.getenv('OPENAI_API_KEY')
model = genai.GenerativeModel('gemini-1.5-flash')


api_requests = 0
def check_api_limit():
    global api_requests 
    if api_requests >= 15:
        print("REQUEST LIMIT REACHED")
        time.sleep(61) 
        api_requests = 0 
        
conn = sqlite3.connect("C:\\Users\\Mika\\CraiglistScraper\\craiglist_posts.db")
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS bitcoinForum_posts (
    post_name TEXT,
    missing_skills TEXT,
    post_link TEXT,
    company_name TEXT
)''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS bitcoinForum_company_posts (
    company_name TEXT PRIMARY KEY,
    post_count INTEGER DEFAULT 0,
    contact_info TEXT,
    profile_link TEXT
)''')
conn.commit()

def post_exists(cursor, title, link):
    cursor.execute("SELECT COUNT(*) FROM bitcoinForum_posts WHERE post_name = ? AND post_link = ?", (title, link))
    return cursor.fetchone()[0] > 0

document = Document("C:\\Users\\Mika\\CraiglistScraper\\TestResume.docx")
text = []
for par in document.paragraphs:
    text.append(par.text)
resume_text = " ".join(text)


def find_contact_info(soup, text):
    global api_requests
    emails = re.findall(r'[\w\.-]+@[\w\.-]+', text)
    emails = [email for email in emails if "bitcointalk.org" not in email]
    telegrams = re.findall(r't.me/[\w]+', text)
    phone_numbers = re.findall(r'\+?\d[\d -]{8,12}\d', text)
    contact_info = emails + telegrams + phone_numbers
    
    if not contact_info:
        task = f"Анализируйте HTML на наличие контактной информации: '{soup}'"
        response = model.generate_content(task)
        api_requests += 1
        check_api_limit()
        return response.text
    
    return ', '.join(contact_info)

def update_company_data(company_name, profile_link):
    cursor.execute("SELECT post_count, contact_info, profile_link FROM bitcoinForum_company_posts WHERE company_name = ?", (company_name,))
    result = cursor.fetchone()

    if result:
        post_count = result[0] + 1
        cursor.execute("UPDATE bitcoinForum_company_posts SET post_count = ? WHERE company_name = ?", (post_count, company_name))

        if post_count >= 2:
            if not result[1] or result[1] == "No contact information found":
                cursor.execute("SELECT post_link FROM bitcoinForum_posts WHERE company_name = ? ORDER BY ROWID ASC LIMIT 1", (company_name,))
                first_post_link = cursor.fetchone()
                if first_post_link:
                    try:
                        response = requests.get(first_post_link[0])
                        response.raise_for_status()
                        mini_soup = BeautifulSoup(response.text, 'html.parser')
                        contact_info = find_contact_info(mini_soup)
                        cursor.execute("UPDATE bitcoinForum_company_posts SET contact_info = ? WHERE company_name = ?", (contact_info, company_name))
                    except requests.RequestException as e:
                        print(f"Request error while fetching post for contact info: {e}")
                
            if not result[2] or result[2] == "No profile link":
                cursor.execute("UPDATE bitcoinForum_company_posts SET profile_link = ? WHERE company_name = ?", (profile_link, company_name))
    else:
        cursor.execute("INSERT INTO bitcoinForum_company_posts (company_name, post_count, contact_info, profile_link) VALUES (?, 1, 'No contact information found', ?)",
                       (company_name, "No profile link"))

    conn.commit()


def generate_ai_content(task):
    global api_requests
    try:
        response = model.generate_content(task)
        api_requests += 1
        check_api_limit()
        
        if hasattr(response, 'text') and response.text:
            return response.text
        else:
            if hasattr(response, 'candidate') and response.candidate.safety_ratings:
                safety_ratings = response.candidate.safety_ratings
                print(f"Response blocked due to safety filters: {safety_ratings}")
                return "Response blocked due to content safety filters."
            else:
                return "No AI response or invalid response structure."
    except Exception as e:
        print(f"Error during AI content generation: {e}")
        return "Error in generating AI response."

url = 'https://bitcointalk.org/index.php?board=185.0'
response = requests.get(url)
soup = BeautifulSoup(response.text, 'html.parser')
posts = soup.find_all('td', class_='windowbg')

try:
    for post in posts:
        title_link = post.find('a')
        if title_link:
            title = title_link.text
            link = title_link['href']
            # filter out titles 
            if "ищу работу" in title.lower():
                continue

            # get the single post page
            if not post_exists(cursor, title, link):
                try:
                    mini_response = requests.get(link)
                    mini_response.raise_for_status()
                    mini_soup = BeautifulSoup(mini_response.text, 'html.parser')
                    description_tag = mini_soup.find('div', class_='post')
                    if description_tag:
                        description = description_tag.text.strip()
                        profile_info = mini_soup.find('td', class_='poster_info')
                        profile_name = profile_info.find('a').text.strip() if profile_info and profile_info.find('a') else 'Unknown'
                        profile_link = profile_info.find('a')['href'] if profile_info and profile_info.find('a') else ''

                        task = (f"Проанализируйте следующий текст: '{description}'. Затем сравните требования к работе, указанные в тексте, с навыками работника: {resume_text}. Перечислите только те навыки, которых не хватает работнику для соответствия данной работе, ТОЛЬКО в виде списка: [..., ..., ...].")
                        missing_skills = generate_ai_content(task)
                        print(f"Title: {title}, Link: {link}, AI Analysis: {missing_skills}")
                        cursor.execute("INSERT INTO bitcoinForum_posts (post_name, missing_skills, post_link, company_name) VALUES (?, ?, ?, ?)",
                                    (title, missing_skills, link, profile_name))
                        update_company_data(profile_name, profile_link)
                    else:
                        print(f"Title: {title}, Link: {link}, Description: Not found")
                except requests.RequestException as e:
                    print(f"Request error for {link}: {e}")
                except Exception as e:
                    print(f"Error parsing HTML for {link}: {e}")
except Exception as e:
    print(f"An unexpected error occurred: {e}")
finally:
    conn.commit()
    cursor.close()
    conn.close()

