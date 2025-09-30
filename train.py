import ee

ee.Authenticate()
ee.Initialize(project="ee-orsperling")

poi = ee.Geometry.Point([34.81261853908583, 31.392933669029375])

img = ee.ImageCollection('COPERNICUS/S2_HARMONIZED') \
        .filterDate("2025-05-01", "2025-06-01") \
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 10)) \
        .median()

# Get mean value of B4 band at the point
b4 = img.reduceRegion(
    reducer=ee.Reducer.mean(),
    geometry=poi,
    scale=50
).get('B4')

print(round(b4.getInfo(), 2))


filtered_collection = ee.ImageCollection('COPERNICUS/S2_HARMONIZED') \
        .filterBounds(poi) \
        .filterDate("2025-05-01", "2025-06-01") \
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 10))

def get_b4_value(image):
        # Get the image capture date.
        date = image.date().format('YYYY-MM-dd')
        # Extract the B4 value at the point.
        b4_value = image.reduceRegion(
            reducer=ee.Reducer.first(), # .first() is efficient for a single pixel
            geometry=poi,
            scale=10  # Use native 10m resolution for B4 band for accuracy
        ).get('B4')
        # Return a feature with the date and value as properties.
        return ee.Feature(None, {'date': date, 'B4': b4_value})

# Apply the function to the collection.
all_records = filtered_collection.map(get_b4_value)

# 5. Fetch the computed data from GEE's servers and print it.
record_list = all_records.getInfo()['features']

for record in record_list:
    properties = record['properties']
    date = properties['date']
    b4 = properties.get('B4') # Use .get() to handle potential null values
    b4_str = f"{b4:.2f}" if b4 is not None else "No Data"
    print(f"Date: {date}, B4 Value: {b4_str}")

