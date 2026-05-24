import csv
import time
import re
import random
import requests
from bs4 import BeautifulSoup


cities = {

    "Islamabad": 3,
    "Lahore": 1,
    "Karachi": 2,
    "Rawalpindi": 41,
    "Faisalabad": 16,
    "Multan": 17,
    "Peshawar": 19,
    "Quetta": 18,
    "Sialkot": 37,
    "Hyderabad": 24,
    "Bahawalpur": 23,
    "Gujranwala": 5,
    "Abbottabad": 20,
    "Murree": 43,
    "Haripur": 25,
    "Sargodha": 10,
    "Sukkur": 31,
    "Gujrat": 36,
    "Rahim Yar Khan": 40,
    "Wah": 84,
    "Mardan": 21,
    "Okara": 39,
    "Jhelum": 38,
    "Mingora": 45
}


headers = {
    "User-Agent": "Mozilla/5.0"
}

alldata = []


def cleaning(text):

    if text:
        return " ".join(text.split())

    return "Not Available"


def convert_price(price):

    if not price:
        return None

    price = price.lower().replace(",", "")

    num = re.findall(r"[\d.]+", price)

    if len(num) == 0:
        return None

    number = float(num[0])

    if "crore" in price:
        number = number * 10000000

    elif "lakh" in price:
        number = number * 100000

    elif "million" in price:
        number = number * 1000000

    return int(number)


def convert_area(area):

    if not area:
        return None

    area = area.lower().replace(",", "")

    num = re.findall(r"[\d.]+", area)

    if len(num) == 0:
        return None

    number = float(num[0])

    if "kanal" in area:
        number = number * 5445

    elif "marla" in area:
        number = number * 272.25

    return round(number, 2)


def property(cityname, cityid, page):

    url = f"https://www.zameen.com/Homes/{cityname}-{cityid}-{page}.html"

    print(f"\nOpening: {cityname} | Page: {page}")

    response = requests.get(
        url,
        headers=headers
    )

    if response.status_code != 200:

        print("Failed to open page")
        return []

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    links = []

    cards = soup.find_all("a")

    for card in cards:

        href = card.get("href")

        if not href:
            continue

        if str(href).startswith("/Property/"):

            full_link = "https://www.zameen.com" + href

            if full_link not in links:
                links.append(full_link)

    return links


def scrape_property(link):

    print(f"Scraping: {link}")

    response = requests.get(
        link,
        headers=headers
    )

    if response.status_code != 200:

        print("Failed Property")
        return None

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    title = "Not Available"

    if soup.title:
        title = cleaning(soup.title.text)

    text = soup.get_text(" ", strip=True)

    price = "Not Available"
    price_num = None

    area = "Not Available"
    area_sqft = None

    bedrooms = None
    bathrooms = None

    city = "Not Available"
    sub_location = "Not Available"
    full_location = "Not Available"

    property_type = "House"

    built_year = None
    parking = 0
    servant = 0
    store = 0
    kitchens = 0
    drawing = 0
    dining = 0
    study = 0
    prayer = 0
    powder = 0
    lounge = 0
    laundry = 0
    floors = None
    furnished = 0


    price_match = re.search(
        r"PKR\s*([\d.,]+\s*(Crore|Lakh|Million)?)",
        text,
        re.IGNORECASE
    )

    if price_match:

        price = price_match.group()
        price_num = convert_price(price)


    area_match = re.search(
        r"([\d.]+)\s*(Marla|Kanal|sq ft|square feet)",
        text,
        re.IGNORECASE
    )

    if area_match:

        area = area_match.group()
        area_sqft = convert_area(area)


    bed_match = re.search(
        r"(\d+)\s+bed",
        text,
        re.IGNORECASE
    )

    if bed_match:
        bedrooms = int(bed_match.group(1))


    bath_match = re.search(
        r"(\d+)\s+bath",
        text,
        re.IGNORECASE
    )

    if bath_match:
        bathrooms = int(bath_match.group(1))


    for c in cities.keys():

        if c.lower() in text.lower():

            city = c
            break


    h1 = soup.find("h1")

    if h1:
        full_location = cleaning(h1.text)
        sub_location = cleaning(h1.text)


    lis = soup.find_all("li")

    for li in lis:

        t = li.get_text(" ", strip=True).lower()

        if "parking" in t:

            n = re.findall(r"\d+", t)

            if len(n) > 0:
                parking = int(n[0])

        if "kitchen" in t:

            n = re.findall(r"\d+", t)

            if len(n) > 0:
                kitchens = int(n[0])

        if "floor" in t:

            n = re.findall(r"\d+", t)

            if len(n) > 0:
                floors = int(n[0])

        if "drawing" in t:
            drawing = 1

        if "dining" in t:
            dining = 1

        if "study" in t:
            study = 1

        if "prayer" in t:
            prayer = 1

        if "powder" in t:
            powder = 1

        if "laundry" in t:
            laundry = 1

        if "servant" in t:
            servant = 1

        if "store room" in t:
            store = 1

        if "furnished" in t:
            furnished = 1

        if "lounge" in t:
            lounge = 1

        if "built in year" in t:

            n = re.findall(r"\d+", t)

            if len(n) > 0:
                built_year = int(n[0])


    data = {

        "Title": title,

        "Price": price,
        "Price_in_PKR": price_num,

        "Area": area,
        "Area_in_Sqft": area_sqft,

        "City": city,
        "Sub_Location": sub_location,
        "Location": full_location,
        "Full_Location": full_location,

        "Bedrooms": bedrooms,
        "Bathrooms": bathrooms,

        "Property_Type": property_type,

        "Built_Year": built_year,
        "Parking_Spaces": parking,
        "Servant_Quarters": servant,
        "Store_Rooms": store,
        "Kitchens": kitchens,
        "Drawing_Rooms": drawing,
        "Dining_Rooms": dining,
        "Study_Rooms": study,
        "Prayer_Rooms": prayer,
        "Powder_Rooms": powder,
        "Lounge_or_Sitting_Rooms": lounge,
        "Laundry_Rooms": laundry,
        "Floors": floors,
        "Furnished": furnished,

        "URL": link
    }

    return data


def save_to_csv(data, filename="pakistan_properties.csv"):

    keys = data[0].keys()

    with open(
        filename,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=keys
        )

        writer.writeheader()

        writer.writerows(data)

    print(f"\nSaved in {filename}")


def main():

    per_city = 1

    max_failed_pages = 2

    for cityname, cityid in cities.items():

        citycount = 0

        failed_pages = 0

        print(f"\n========== {cityname} ==========")

        for page in range(1, 400):

            links = property(
                cityname,
                cityid,
                page
            )

            print(f"Found {len(links)} links")

            if len(links) == 0:

                failed_pages += 1

                print(f"Failed Pages: {failed_pages}")

            else:

                failed_pages = 0


            if failed_pages >= max_failed_pages:

                print(f"Stopping {cityname}")

                break


            for link in links:

                if citycount >= per_city:
                    break

                info = scrape_property(link)

                if info:

                    alldata.append(info)

                    citycount += 1

                    print(f"{cityname}: {citycount}")


                sleep_time = random.uniform(2, 4)

                #time.sleep(sleep_time)


                if len(alldata) % 50 == 0:

                    save_to_csv(alldata)


            if citycount >= per_city:

                print(f"Completed {cityname}")

                break


    if len(alldata) > 0:

        save_to_csv(alldata)

    print(f"\nTotal Properties: {len(alldata)}")


if __name__ == "__main__":

    main()