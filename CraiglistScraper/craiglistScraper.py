from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from collections import defaultdict
import re
import time
import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv("C:\\PythonProjects\\CraiglistScraper\\Keys.env")
API_KEY = os.getenv('OPENAI_API_KEY')
from docx import Document

import sqlite3

zip_codes = [
    "94102",  # San Francisco, CA
    "94014",  # Daly City, CA
    "94080",  # South San Francisco, CA
    "94401",  # San Mateo, CA
    "94010",  # Burlingame, CA
    "94025",  # Menlo Park, CA
    "94301",  # Palo Alto, CA
    "94040",  # Mountain View, CA
    "95014",  # Cupertino, CA
    "95110",  # San Jose, CA
    "94501",  # Alameda, CA
    "94577",  # San Leandro, CA
    "94601",  # Oakland, CA
    "94702",  # Berkeley, CA
    "94801",  # Richmond, CA
    "94536",  # Fremont, CA
    "94544",  # Hayward, CA
    "94546",  # Castro Valley, CA
    "94553",  # Martinez, CA
    "94583",  # San Ramon, CA
    "94901"   # San Rafael, CA
]


keywords = ["boot", "camp", "academy", "enroll", "bootcamp"]
def contains_keywords(title):
    return any(re.search(r'\b' + re.escape(keyword) + r'\b', title, re.IGNORECASE) for keyword in keywords)

#connecting and setting up a database
conn = sqlite3.connect("C:\\Users\\Mika\\CraiglistScraper\\craiglist_posts.db")
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS posts
               (post_name TEXT,
                missing_skills TEXT,
                post_link TEXT,
                company_name TEXT
               )''')   
conn.commit()

def insert_post(title, missing_skills, company_name, post_link):
    cursor.execute("INSERT INTO posts (post_name, missing_skills, company_name, post_link) VALUES (?, ?, ?, ?)",
                   (title, missing_skills, company_name, post_link))
    conn.commit()

#created another table
cursor.execute('''
CREATE TABLE IF NOT EXISTS company_posts (
    company_name TEXT PRIMARY KEY,
    post_count INTEGER DEFAULT 0,
    contact_info TEXT
)''')
conn.commit()


def update_company_data(company_name, contact_info=None):
    try:
        cursor.execute("SELECT post_count FROM company_posts WHERE company_name = ?", (company_name,))
        result = cursor.fetchone()
        if result:
            new_count = result[0] + 1
            cursor.execute("UPDATE company_posts SET post_count = ? WHERE company_name = ?", (new_count, company_name))
        else:
            new_count = 1
            cursor.execute("INSERT INTO company_posts (company_name, post_count) VALUES (?, 1)", (company_name,))
        
        if new_count >= 2 and contact_info:
            cursor.execute("UPDATE company_posts SET contact_info = ? WHERE company_name = ?", (contact_info, company_name))
        
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")

def get_companies_ordered_by_posts():
    cursor.execute("SELECT company_name, post_count, contact_info FROM company_posts ORDER BY post_count DESC")
    return cursor.fetchall()

def update_contact_info_for_active_companies():

    cursor.execute("SELECT company_name, contact_info FROM company_posts WHERE post_count >= 2")
    active_companies = cursor.fetchall()
    
    for company in active_companies:
        company_name, current_contact_info = company
        
       
        if current_contact_info and current_contact_info != "No contact information found":
            print(f"Skipping {company_name} as it already has contact information.")
            continue
        
        cursor.execute("SELECT post_link FROM posts WHERE company_name = ? ORDER BY ROWID LIMIT 1", (company_name,))
        post_links = cursor.fetchall()
        
        contact_info = "No contact information found"
        
        for post_link in post_links:
            if post_link:
                driver.get(post_link[0])  
                contact_info = find_contact_info(driver)
                if "No contact information found" not in contact_info:
                    
                    cursor.execute("UPDATE company_posts SET contact_info = ? WHERE company_name = ?", (contact_info, company_name))
                    conn.commit()
                    print(f"Contact information found for {company_name}: {contact_info}")
                    break
        else:
           
            cursor.execute("UPDATE company_posts SET contact_info = ? WHERE company_name = ?", (contact_info, company_name))
            conn.commit()
            print(f"No sufficient contact information found for {company_name}")






def post_exists(cursor, title, link):
    cursor.execute("SELECT COUNT(*) FROM posts WHERE post_name = ? AND post_link = ?", (title, link))
    return cursor.fetchone()[0] > 0

#test function to print out the database
def print_database():
    cursor.execute("SELECT * FROM posts")
    rows = cursor.fetchall()
    print("Database contents:")
    for row in rows:
        print(row)


genai.configure(api_key=API_KEY)

model = genai.GenerativeModel('gemini-1.5-flash')

options = Options()
options.add_experimental_option('excludeSwitches', ['enable-logging'])

service = Service(executable_path="C:\\PythonProjects\\chromedriver.exe")
driver = webdriver.Chrome(service=service)


#setting up time control so that free google gemini-api won't exceed it's limit
api_requests = 0

#Setting up document with the worker's resume and skills
document = Document("C:\\Users\\Mika\\CraiglistScraper\\TestResume.docx")
text = []
for par in document.paragraphs:
    text.append(par.text)
text = " ".join(text)

#create a function that will look for contacts for me
def find_contact_info(driver):
    global api_requests
    page_html_text = driver.page_source
    
    
    potential_contacts = re.findall(r'[\w\.-]+@[\w\.-]+', page_html_text)  # Find any email addresses
    potential_links = re.findall(r'<a [^>]*href="([^"]*)"[^>]*>([^<]*apply[^<]*|[^<]*contact[^<]*|[^<]*website[^<]*)</a>', page_html_text, re.IGNORECASE)
    
  
    contact_info = potential_contacts + [link[0] for link in potential_links if "craigslist" not in link[0]]

    if not contact_info:
        task = (f"Analyze the following HTML content and extract any contact information such as email addresses, phone numbers, or external links to apply or contact the company. "
        "Please return only the contact information found, such as email addresses, phone numbers, or external (non-Craigslist) links. "
        "Ignore any internal Craigslist links like 'flag', 'privacy policy', 'terms of use', or other similar URLs. "
        "If no contact information is found, simply return 'No contact information found'. "
        f"Here is the HTML content: '{page_html_text}'")
        response = model.generate_content(task)
        api_requests += 1
        check_api_limit()
        contact_info = response.text if hasattr(response, 'text') else response

    if contact_info:
        contact_info_str = " | ".join(contact_info) if isinstance(contact_info, list) else contact_info
        return f"Contact Information: {contact_info_str}"
    else:
        return "No contact information found"
    


#check api requests function 
def check_api_limit():
    global api_requests 
    if api_requests >= 15:
        print("REQUEST LIMIT REACHED")
        time.sleep(61) 
        api_requests = 0 


def reorder_companies_by_post_count():
    cursor.execute("SELECT company_name, post_count, contact_info FROM company_posts ORDER BY post_count DESC")
    companies_ordered = cursor.fetchall()


    cursor.execute("DROP TABLE IF EXISTS company_posts")
    cursor.execute('''
    CREATE TABLE company_posts (
        company_name TEXT PRIMARY KEY,
        post_count INTEGER DEFAULT 0,
        contact_info TEXT
    )''')
    conn.commit()

    for company in companies_ordered:
        cursor.execute("INSERT INTO company_posts (company_name, post_count, contact_info) VALUES (?, ?, ?)",
                       (company[0], company[1], company[2]))
    conn.commit()

try:
    for zip_code in zip_codes:  
        url = f"https://portland.craigslist.org/search/sof?postal={zip_code}#search=1~thumb~0~0"
        driver.get(url)
        wait = WebDriverWait(driver, 30)
        posts = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".results.cl-results-page .cl-search-result.cl-search-view-mode-thumb")))
        main_tab = driver.window_handles[0]  

        for post in posts:
            try:
                link = post.find_element(By.CSS_SELECTOR, ".cl-app-anchor.text-only.posting-title").get_attribute('href')
                driver.execute_script("window.open();")
                driver.switch_to.window(driver.window_handles[1])
                driver.get(link)
                title = driver.find_element(By.CSS_SELECTOR, ".postingtitletext").text

                # Filter out posts with unwanted keywords in the title
                if contains_keywords(title):
                    print(f"Filtered out post: {title}")
                    driver.close()
                    driver.switch_to.window(main_tab)
                    continue

                try:
                    company_name_element = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".company-name"))
                    )
                    company_name = company_name_element.text
                except Exception as e:
                    print(f"Company name not found in {title} : {e}")
                    company_name = "Unknown"  # Assign a default

                # Check if the post is already in the database
                if not post_exists(cursor, title, link):
                    description = wait.until(EC.presence_of_element_located((By.ID, "postingbody"))).text
                    task = (f"Analyze the following text: '{description}'. "
                            f"Then, compare the job requirements mentioned in the text to the worker's skills: {text}. "
                            "List only the skills that the worker is missing in order to be qualified for the job in the form of a list like this: [..., ..., ...]. "
                            "Do not write anything else other than what is requested.")
                    response = model.generate_content(task)
                    api_requests += 1
                    check_api_limit()                  
                    update_company_data(company_name)
                    insert_post(title, response.text, company_name, link)
                    driver.close()
                    driver.switch_to.window(main_tab)
                else:
                    print(f"Title is already in the database: {title}")
                    driver.close()
                    driver.switch_to.window(main_tab)
            except Exception as e:
                print(f"Error: {e}")
                driver.close()
                driver.switch_to.window(main_tab)
            check_api_limit()
            time.sleep(1)
finally:
    update_contact_info_for_active_companies()
    reorder_companies_by_post_count()
    print_database()
    cursor.close()
    conn.close()
    driver.quit()
