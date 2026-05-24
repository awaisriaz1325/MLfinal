import pickle
import pandas as pd

from flask import Flask
from flask import render_template
from flask import request


app = Flask(__name__)


data = pd.read_csv("pakistan_properties.csv")


with open("model.pkl", "rb") as file:

    model = pickle.load(file)


locations = sorted(
    data["Location"].dropna().unique()
)


@app.route("/", methods=["GET", "POST"])
def home():

    prediction = ""

    if request.method == "POST":

        area = float(request.form["area"])

        bedrooms = int(request.form["bedrooms"])

        bathrooms = int(request.form["bathrooms"])

        location = request.form["location"]

        property_type = request.form["property_type"]

        built_year = request.form["built_year"]

        parking = request.form["parking"]

        kitchens = request.form["kitchens"]

        floors = request.form["floors"]

        furnished = request.form["furnished"]


        row = data[
            data["Location"] == location
        ]


        if len(row) > 0:

            row = row.iloc[0]

            city = row["City"]

            sub_location = row["Sub_Location"]

        else:

            city = "Islamabad"

            sub_location = location


        sample = {

            "Area_in_Sqft": area,

            "City": city,

            "Sub_Location": sub_location,

            "Location": location,

            "Bedrooms": bedrooms,

            "Bathrooms": bathrooms,

            "Property_Type": property_type,

            "Built_Year": built_year,

            "Parking_Spaces": parking,

            "Servant_Quarters": 0,

            "Store_Rooms": 0,

            "Kitchens": kitchens,

            "Drawing_Rooms": 1,

            "Dining_Rooms": 1,

            "Study_Rooms": 0,

            "Prayer_Rooms": 0,

            "Powder_Rooms": 0,

            "Lounge_or_Sitting_Rooms": 1,

            "Laundry_Rooms": 0,

            "Floors": floors,

            "Furnished": furnished
        }


        final = pd.DataFrame([sample])


        prediction = model.predict(final)[0]

        prediction = "PKR {:,}".format(
            int(prediction)
        )


    return render_template(
        "index.html",
        prediction=prediction,
        locations=locations
    )


if __name__ == "__main__":

    app.run(debug=True)