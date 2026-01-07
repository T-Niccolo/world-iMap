import streamlit as st
import ee
import pandas as pd
from datetime import datetime

@st.cache_data(show_spinner=False)
def get_ndvi(lat, lon):
    """Fetches NDVI from Google Earth Engine."""
    poi = ee.Geometry.Point([lon, lat])
    today = datetime.now()
    if today.month < 6:
        today = today.replace(year=today.year - 1)

    img = ee.ImageCollection('COPERNICUS/S2_HARMONIZED') \
        .filterDate(f"{today.year}-05-01", f"{today.year}-06-01") \
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 10)) \
        .median()

    ndvi = img.normalizedDifference(['B8', 'B4']).reduceRegion(
        ee.Reducer.mean(), poi, 50).get('nd').getInfo()

    return round(ndvi, 2) if ndvi else None

@st.cache_data(show_spinner=False)
def get_rain(lat, lon):
    """Fetches rainfall data from Google Earth Engine."""
    today = datetime.today()
    if today.month < 3:
        today = today.replace(year=today.year - 1)

    poi = ee.Geometry.Point([lon, lat])
    rain_sum = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY') \
        .filterDate(f"{today.year - 1}-11-01", f"{today.year}-04-01") \
        .sum() \
        .reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=poi,
            scale=5000
        ).get('precipitation')

    return round(rain_sum.getInfo() or 0.0, 1)

@st.cache_data(show_spinner=False)
def get_et0(lat, lon):
    """Fetches ET0 data from Google Earth Engine."""
    poi = ee.Geometry.Point([lon, lat])
    dataset = ee.ImageCollection("IDAHO_EPSCOR/TERRACLIMATE") \
        .filterDate("2019-01-01", "2024-12-31") \
        .select('pet')

    stats = ee.FeatureCollection(ee.List.sequence(1, 12).map(
        lambda m: ee.Feature(None, {
            'month': m,
            'ET0': dataset.filter(ee.Filter.calendarRange(m, m, 'month')).mean() \
                .reduceRegion(ee.Reducer.mean(), poi, 4638.3).get('pet')
        })
    )).getInfo()
    
    return pd.DataFrame([{
        'month': int(f['properties']['month']),
        'ET0': round(f['properties']['ET0'] * 0.1 or 0, 2)
    } for f in stats['features']])
