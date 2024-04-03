import asyncio
import json
import time
import warnings
import aiohttp
import requests

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

warnings.filterwarnings("ignore", category=DeprecationWarning)


class DigikalaProductScraper:
    def __init__(self):
        self.driver = None

    @staticmethod
    async def _get_proxy():
        proxy_url = 'https://www.sslproxies.org/'
        async with aiohttp.ClientSession() as session:
            async with session.get(proxy_url) as response:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                table = soup.select_one("table:nth-of-type(1)")
                rows = table.tbody.find_all('tr')
                for row in rows:
                    tds = row.find_all('td')
                    ip = tds[0].text.strip()
                    port = tds[1].text.strip()
                    proxy = f"https://{ip}:{port}"
                    try:
                        response = requests.get('https://api.ipify.org', proxies={"https": proxy}, timeout=2)
                        if ip not in response.text:
                            continue
                        return proxy
                    except Exception as e:
                        print(e)
                        continue
        return None

    def _scroll_to_end(self):
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        while True:
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(5)
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
        return self.driver.execute_script("scrollBy(0,250);")

    def _scroll_to_comments_and_wait_for_load(self):
        comments_nav = self.driver.find_element(By.XPATH, '//li[contains(text(), "دیدگاه‌ها")]')
        self._scroll_to_element_and_click(comments_nav)
        time.sleep(0.5)
        WebDriverWait(self.driver, 20).until(
            EC.all_of(
                EC.any_of(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, '[data-cro-id="pdp-comments-more"]')
                    ),
                    EC.presence_of_element_located(
                        (By.XPATH, "//span[contains(@class, 'text-body2-strong') and contains(text(), 'بعدی')]")
                    ),
                ),
                EC.invisibility_of_element_located(
                    (By.CSS_SELECTOR, 'div#ReactModalPortal a[href="/"]')
                )
            )
        )
        time.sleep(1)

    def _scroll_to_element_and_click(self, element):
        self.driver.execute_script("arguments[0].scrollIntoView();", element)
        self.driver.execute_script("arguments[0].click();", element)

    def _run_scrape_for_url(self, url, sort_by):
        print("Waiting for page to load...")
        self.driver.get(url)
        self._scroll_to_end()

        print("Waiting for comments to load...")
        self._scroll_to_comments_and_wait_for_load()

        print("Updating comments sort...")
        sort_option = self.driver.find_element(
            By.XPATH, f'//span[@data-cro-id="pdp-comment-sort" and contains(text(), "{sort_by}")]'
        )
        self._scroll_to_element_and_click(sort_option)
        self._scroll_to_comments_and_wait_for_load()

        print("Loading the full comment page...")
        found_more_button = False
        while True:
            try:
                view_more_button = self.driver.find_element(
                    By.CSS_SELECTOR,
                    '[data-cro-id="pdp-comments-more"]',
                )
                self._scroll_to_element_and_click(view_more_button)
                found_more_button = True
                self._scroll_to_comments_and_wait_for_load()
            except NoSuchElementException:
                if not found_more_button:
                    raise
                break

        print("Extracting product details...")
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        title = soup.select_one('h1.text-h4').get_text(strip=True)
        rating_img = soup.select_one('img[alt="امتیاز"]')
        rating = rating_img.parent.parent.find_next_sibling('p', class_='text-body-2').get_text(strip=True)
        intab = '۱۲۳۴۵۶۷۸۹۰١٢٣٤٥٦٧٨٩٠'
        outtab = '12345678901234567890'
        translation_table = str.maketrans(intab, outtab)
        rating = float(rating.translate(translation_table))

        print("Extracting comments...")
        comments = []
        while True:
            try:
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')
                comments_soup = soup.select('#commentSection article')
                for comment in comments_soup:
                    comment_title = comment.select_one('p.text-h5')
                    if comment_title:
                        comment_title = comment_title.get_text(strip=True)
                    else:
                        comment_title = None

                    comment_text = comment.select_one('p.text-body-1.text-neutral-900.mb-1.pt-3.break-words')\
                        .get_text(strip=True)

                    comment_author = comment.select_one('p.text-caption.text-neutral-400.inline')\
                        .get_text(strip=True)

                    recommends_value = comment.select_one('div.flex.items-center.pt-2 > p')
                    if recommends_value:
                        recommends_value = recommends_value.get_text(strip=True)
                    recommends = None
                    match recommends_value:
                        case 'پیشنهاد می‌کنم':
                            recommends = 'yes'
                        case 'پیشنهاد نمی‌کنم':
                            recommends = 'no'
                        case 'مطمئن نیستم':
                            recommends = 'unsure'

                    pros_and_cons = comment.select('div.flex > p.text-body-2')
                    pros = []
                    cons = []
                    for item in pros_and_cons:
                        if '#addSimple' in str(item.find_previous_sibling('div')):
                            pros.append(item.get_text(strip=True))
                        elif '#removeSimple' in str(item.find_previous_sibling('div')):
                            cons.append(item.get_text(strip=True))

                    comment_stars_raw = comment.select_one('div.absolute.right-0.top-0.overflow-hidden').attrs['style']
                    comment_stars = int(comment_stars_raw[7:-2]) // 20

                    comments.append({
                        "author": comment_author,
                        "stars": comment_stars,
                        "recommends": recommends,
                        "title": comment_title,
                        "text": comment_text,
                        "pros": pros,
                        "cons": cons,
                        "raw": str(comment),
                    })

                next_button_text = self.driver.find_element(
                    By.XPATH, "//span[contains(@class, 'text-body2-strong') and contains(text(), 'بعدی')]"
                )
                if next_button_text.is_displayed():
                    next_button = next_button_text.find_element(By.XPATH, "./..")
                    self._scroll_to_element_and_click(next_button)
                    self._scroll_to_comments_and_wait_for_load()
                else:
                    break
            except Exception as e:
                print(e)
                break

        data = {
            'title': title,
            'rating': rating,
            'comments': comments,
        }

        filename = f'{title}_digikala_product_comments.json'
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        print("Done!")

    def scrape_url(self, url, sort_by, *, use_proxies):
        print(f"Scraping URL: {url}, Sorting by {sort_by}")
        options = webdriver.ChromeOptions()
        options.add_argument('--no-sandbox')
        options.add_argument("start-maximized")
        if use_proxies:
            print("Trying to find a valid proxy...")
            proxy = asyncio.run(self._get_proxy())
            if not proxy:
                raise RuntimeError("No valid proxy found.")
            options.add_argument(f'--proxy-server={proxy}')
        self.driver = webdriver.Chrome(options=options)
        self._run_scrape_for_url(url, sort_by)
        self.driver.quit()


if __name__ == '__main__':
    products = [
        {
            'url': 'https://www.digikala.com/product/dkp-12017522/%D9%87%D9%86%D8%AF%D8%B2%D9%81%D8%B1%DB%8C-%D9%84%DB%8C%D8%AA%D9%88-%D9%85%D8%AF%D9%84-le-16/',
            'sort_by': "جدیدترین"
        },
        {
            'url': 'https://www.digikala.com/product/dkp-11096212/%DA%AF%D9%88%D8%B4%DB%8C-%D9%85%D9%88%D8%A8%D8%A7%DB%8C%D9%84-%D8%B1%DB%8C%D9%84%D9%85%DB%8C-%D9%85%D8%AF%D9%84-narzo-50a-prime-%D8%AF%D9%88-%D8%B3%DB%8C%D9%85-%DA%A9%D8%A7%D8%B1%D8%AA-%D8%B8%D8%B1%D9%81%DB%8C%D8%AA-128-%DA%AF%DB%8C%DA%AF%D8%A7%D8%A8%D8%A7%DB%8C%D8%AA-%D9%88-%D8%B1%D9%85-4-%DA%AF%DB%8C%DA%AF%D8%A7%D8%A8%D8%A7%DB%8C%D8%AA/',
            'sort_by': "جدیدترین",
        },
    ]
    scraper = DigikalaProductScraper()
    for product in products:
        scraper.scrape_url(product['url'], product['sort_by'], use_proxies=False)
