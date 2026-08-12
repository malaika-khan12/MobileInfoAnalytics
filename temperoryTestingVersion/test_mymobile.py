from playwright.sync_api import sync_playwright

url = "https://mymobile.pk/products/iphone-18-pro-max/"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    page.goto(url)

    price = page.locator("#dpPrice").inner_text()

    print("Price:", price)

    browser.close()