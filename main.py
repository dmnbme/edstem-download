from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager

LOGIN_URL = 'https://edstem.org/au/login'
LOGIN_SUCCESS_SELECTOR = '.text_qU_yO'
LOGIN_TIMEOUT_SECONDS = 120
COURSE_URL = 'https://edstem.org'

# launch chrome
options = Options()
options.add_experimental_option('detach', True)
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

driver.get(LOGIN_URL)

# wait for logging in
print('Please log in in the pop-up browser.')
try:
    WebDriverWait(driver, LOGIN_TIMEOUT_SECONDS).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, LOGIN_SUCCESS_SELECTOR))
    )
    print('Logged in successfully.')
except TimeoutException:
    print('Sorry. Timeout.')
    exit()

# after logged in
course_elements = driver.find_elements(By.CSS_SELECTOR, '.dash-courses a.dash-course')
courses = []
for course in course_elements:
    try:
        code = course.find_element(By.CSS_SELECTOR, '.dash-course-code').text.strip()
        name = course.find_element(By.CSS_SELECTOR, '.dash-course-name').text.strip()
        courses.append({'code': code, 'name': name})
    except NoSuchElementException:
        print('You have no courses.')

for course in courses:
    print(f"{course['code']} - {course['name']}")