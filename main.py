from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver import ActionChains
from urllib.parse import urljoin
from pathlib import Path
import time
import random

def rand_sleep():
    time.sleep(random.uniform(0, 2))

BASE_URL = 'https://edstem.org/'
LOGIN_URL = 'https://edstem.org/au/login'
LOGIN_SUCCESS_SELECTOR = '.text_qU_yO'
LOGIN_TIMEOUT_SECONDS = 120
DOWNLOAD_DIRECTORY = Path.cwd() / 'edstem_downloads'
# DOWNLOAD_DIRECTORY = Path(r'The_directory_you_want_to_use')

# launch chrome
options = Options()
options.add_experimental_option('detach', True)
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
driver.get(LOGIN_URL)

# log in
print('Please log in Edstem in the pop-up browser, then come back.')
try:
    WebDriverWait(driver, LOGIN_TIMEOUT_SECONDS).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, LOGIN_SUCCESS_SELECTOR))
    )
    print('Logged in successfully.')
    print('----------')
except TimeoutException:
    print('Sorry. Timeout. Check your connection.')
    exit()

# collect course code, name, link from dashboard
try:
    courses = []
    course_elements = driver.find_elements(By.CSS_SELECTOR, '.dash-courses a.dash-course')
    for course in course_elements:
        course_code = course.find_element(By.CSS_SELECTOR, '.dash-course-code').text.strip()
        course_name = course.find_element(By.CSS_SELECTOR, '.dash-course-name').text.strip()
        course_link = urljoin(BASE_URL, course.get_attribute('href'))
        courses.append({'code': course_code, 'name': course_name, 'link': course_link})
except NoSuchElementException:
    print('You have no courses.')

if courses:
    print('Fetched courses:')
    for i in range(len(courses)):
        print(f"{i}. {courses[i]['code']} | {courses[i]['name']} | {courses[i]['link']}")
    print('----------')
    while True:
        choice = input('Please input the number of the course you want to download: ').strip()
        if len(choice) != 1 or int(choice) not in range(len(courses)):
            print('Invalid choice.')
            continue
        else:
            course_dl = int(choice)
            break

    LESSON_URL = courses[course_dl]['link'] + '/lessons'
    driver.get(LESSON_URL)

# collect lesson titles and links from lesson page
try:
    WebDriverWait(driver, LOGIN_TIMEOUT_SECONDS).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, '.table-listing-row.lesi-row'))
    )
except TimeoutException:
    print('Sorry. Timeout. Please check your connection.')
    exit()

lessons = []
print('----------')
print('Fetched lessons:')
module_sections = driver.find_elements(By.CSS_SELECTOR, '.lesi-list-container > div')
for module in module_sections:
    try:
        module_name = module.find_element(By.CSS_SELECTOR, '.lesson-module-header-name').text.strip()
    except NoSuchElementException:
        module_name = ''

    print(f'Module: {module_name}')
    for row in module.find_elements(By.CSS_SELECTOR, '.table-listing-row.lesi-row'):
        lesson_element = row.find_element(By.CSS_SELECTOR, 'a.tabliscel-flex')
        lesson_title = lesson_element.find_element(By.CSS_SELECTOR, '.tablistext-text').text.strip()
        lesson_link = urljoin(BASE_URL, lesson_element.get_attribute('href'))
        lessons.append({'module': module_name, 'title': lesson_title, 'link': lesson_link})
        print(f'{lesson_title} | {lesson_link}')

# download each lesson
for download in lessons:
    download_path = (DOWNLOAD_DIRECTORY / courses[course_dl]['code'] / download['module']).resolve()
    driver.execute_cdp_cmd("Page.setDownloadBehavior", {
    "behavior": "allow",
    "downloadPath": str(download_path)
})

    rand_sleep() # prevent being limited for operating too frequently
    driver.get(download['link'])
    wait = WebDriverWait(driver, 5)
    rand_sleep()
    # click button more for menu
    more_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.navbar-button[aria-haspopup='menu']")))
    rand_sleep()
    more_btn.click()
    rand_sleep()
    # simulate mouseup event on preview lesson button in the menu
    try:
        menu_item = wait.until(EC.visibility_of_element_located((By.XPATH, "//tr[contains(@class,'root')][.//div[@class='text_if9SO' and normalize-space()='Preview Lesson']]")))
    except TimeoutException:
        try:
            view_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@class,'actdlg-action')][normalize-space()='View your submissions']")))
            view_btn.click()
        except:
            print(f"{download['title']}: Unsupported lesson type.")
            continue
    rand_sleep()
    ActionChains(driver).move_to_element(menu_item).pause(0.1).click_and_hold().pause(0.1).release().perform()
    rand_sleep()
    download_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(@class,'navbar-button')]//span[normalize-space()='Download PDF']/..")))
    rand_sleep()
    download_btn.click()
    time.sleep(3)
    driver.get(LESSON_URL)