import streamlit as st
from streamlit_folium import st_folium
import pandas as pd
import folium
import ee
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import time
from google.oauth2 import service_account
from fpdf import FPDF
import tempfile
import os
from PIL import Image
from io import BytesIO
from staticmap import StaticMap, IconMarker
from folium.plugins import Geocoder
import openmeteo_requests

st.set_page_config(layout='wide')

# Function to initialize Earth Engine with credentials
def initialize_ee():
    # Get credentials from Streamlit secrets
    credentials = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://www.googleapis.com/auth/earthengine"]
    )
    # Initialize Earth Engine
    ee.Initialize(credentials)

initialize_ee()
# ee.Initialize()
# ee.Authenticate()
# ee.Initialize(project="rsc-gwab-lzp")

# 🌍 Function to Fetch NDVI from Google Earth Engine
@st.cache_data(show_spinner=False)
def get_ndvi(lat, lon):
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


# DEFAULT_CENTER = [35.26, -119.15]
# DEFAULT_ZOOM = 13

# 🌍 Interactive Map for Coordinate Selection
def display_map():
    # Center and zoom
    map_center = [31.709172, 34.800522]
    zoom = 15

    # Create map
    m = folium.Map(location=map_center, zoom_start=zoom, tiles=None)

    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
        attr='Map data © Google',
        name='Google Satellite',
        overlay=False,
        control=True
    ).add_to(m)

    m.add_child(folium.LatLngPopup())

    Geocoder(collapsed=False, add_marker=False).add_to(m)

    return st_folium(m, height=600, width=900, use_container_width=True)


# 📊 Function to Calculate Irrigation
def calc_irrigation(pNDVI, rain, et0, m_winter, irrigation_months, irrigation_factor):
    df = et0.copy()
    rain_eff = (rain * conversion_factor * 0.8) + m_winter
    
    m_start, m_end = irrigation_months
    irr_mnts = list(range(m_start, m_end + 1))
    
    # Apply growing season constraints and conversion
    is_active = df['month'].isin(range(3, 11)) | df['month'].isin(irr_mnts)
    df.loc[~is_active, 'ET0'] = 0
    df['ET0'] *= conversion_factor
    df['ETa'] = df['ET0'] * pNDVI / 0.7

    # Calculate Soil Water Index (SWI)
    eta_off_season = df.loc[~df['month'].isin(irr_mnts), 'ETa'].sum()
    swi = (rain_eff - eta_off_season - 50 * conversion_factor) / len(irr_mnts)

    # Calculate Irrigation
    df['irrigation'] = 0.0
    mask = df['month'].isin(irr_mnts)
    df.loc[mask, 'irrigation'] = (df.loc[mask, 'ETa'] - swi).clip(lower=0)
    df['irrigation'] *= irrigation_factor

    # Adjust for peak summer redistribution
    vst = df.loc[df['month'] == 7, 'irrigation'].iloc[0] * 0.2
    df.loc[df['month'] == 7, 'irrigation'] -= vst
    df.loc[df['month'] == 8, 'irrigation'] += vst * 0.4
    df.loc[df['month'] == 9, 'irrigation'] += vst * 0.6

    # Final balance and status
    df['SW1'] = (rain_eff - df['ETa'].cumsum() + df['irrigation'].cumsum()).clip(lower=0)
    df['alert'] = np.where(df['SW1'] == 0, 'drought', 'safe')

    return df


# 🌟 **Streamlit UI**
st.markdown("<h1 style='text-align: center;'>G-WaB: Geographic Water Budget</h1>", unsafe_allow_html=True)
st.markdown(
    "<p style='text-align: center; font-size: 20px'>A <a href=\"https://www.bard-isus.org/\"> <strong>BARD</strong></a> research report by: </p>"
    "<p style='text-align: center;'><a href=\"mailto:orsp@volcani.agri.gov.il\"> <strong>Or Sperling</strong></a> (ARO-Volcani), "
    "<a href=\"mailto:mzwienie@ucdavis.edu\"> <strong>Maciej Zwieniecki</strong></a> (UC Davis), "
    "<a href=\"mailto:zellis@ucdavis.edu\"> <strong>Zac Ellis</strong></a> (UC Davis), "
    "and <a href=\"mailto:niccolo.tricerri@unito.it\"> <strong>Niccolò Tricerri</strong></a> (UNITO - IUSS Pavia)  </p>",
    unsafe_allow_html=True)

# 📌 **User Inputs**
# 🌍 Unit system selection

# st.sidebar.caption('This is a research report. For further information contact **Or Sperling** (orsp@volcani.agri.gov.il; ARO-Volcani), **Maciej Zwieniecki** (mzwienie@ucdavis.edu; UC Davis), or **Niccolo Tricerri** (niccolo.tricerri@unito.it; University of Turin).')
st.sidebar.image("img/Marker.png")

st.sidebar.header("Farm Data")

use_imperial = st.sidebar.toggle("Use Imperial Units (inches)")

unit_system = "Imperial (inches)" if use_imperial else "Metric (mm)"
unit_label = "inches" if use_imperial else "mm"
conversion_factor = 0.03937 if use_imperial else 1

# --- Sliders (trigger irrigation calc only)
m_winter = st.sidebar.slider(f"Winter Irrigation ({unit_label})", 0, int(round(700 * conversion_factor)), 0,
                                step=int(round(20 * conversion_factor)),
                                help="Did you irrigate in winter? If yes, how much?")
                                
irrigation_months = st.sidebar.slider("Irrigation Months", 1, 12, (3, 10), step=1,
                                        help="During which months will you irrigate?")

# Layout: 2 columns (map | output)
col2, col1 = st.columns([6, 4])

with col1:

    # 🗺️ **Map Selection**
    map_data = display_map()

with col2:

    # --- Handle map click
    if map_data and map_data["last_clicked"] is not None and "lat" in map_data["last_clicked"]:
        
        coords = map_data["last_clicked"]
        lat, lon = coords["lat"], coords["lng"]
        location = (lat, lon)

        # Check if location changed
        now = time.time()
        last_loc = st.session_state.get("last_location")
        last_time = st.session_state.get("last_location_time", 0)

        # location_changed = (last_loc != location) and (now - last_time > 5)

        if location != last_loc or (now - last_time > 5):
            # Update session state with the new location and timestamp
            st.session_state["last_location"] = location
            st.session_state["last_location_time"] = now

            # Fetch and store weather data
            st.session_state["et0"] = get_et0(lat, lon)
            st.session_state["rain"] = get_rain(lat, lon)
            st.session_state["ndvi"] = get_ndvi(lat, lon)

        # Retrieve stored values
        rain = st.session_state.get("rain")
        ndvi = st.session_state.get("ndvi")
        et0 = st.session_state.get("et0")

        # IF = 0.33 / (1 + np.exp(20 * (ndvi - 0.6))) + 1
        # pNDVI = ndvi * IF
        pNDVI=.8*(1-np.exp(-3*ndvi))

        if rain is not None and ndvi is not None and et0 is not None:
            
            total_rain = rain * conversion_factor
            m_rain = st.sidebar.slider(f"Fix Rain to Field ({unit_label})", 0, int(round(1000 * conversion_factor)),
                                        int(total_rain), step=1, disabled=False,
                                        help="Do you know a better value? Do you think less water was retained in the soil?")

            # 🔄 Always recalculate irrigation when sliders or location change
            df_irrigation = calc_irrigation(pNDVI, m_rain , et0, m_winter, irrigation_months, 1)

            total_irrigation = df_irrigation['irrigation'].sum()
            m_irrigation = st.sidebar.slider(f"Water Allocation ({unit_label})", 0,
                                                int(round(1500 * conversion_factor)),
                                                int(total_irrigation), step=int(round(20 * conversion_factor)),
                                                help="Here's the recommended irrigation. Are you constrained by water availability, or considering extra irrigation for salinity management?")

            irrigation_factor = m_irrigation / total_irrigation

            # ✅ Adjust ET0 in the table
            df_irrigation = calc_irrigation(pNDVI, m_rain, et0, m_winter, irrigation_months, irrigation_factor)
            total_irrigation = df_irrigation['irrigation'].sum()


            st.markdown(f"<p style='text-align: center; font-size: 30px;'>Rain: {rain * conversion_factor:.2f} {unit_label} | ET₀: {df_irrigation['ET0'].sum():.0f} {unit_label}</p>", unsafe_allow_html=True)
            st.markdown(f"<p style='text-align: center; font-size: 30px;'>NDVI: {ndvi:.2f} | pNDVI: {pNDVI:.2f}| Irrigation: {total_irrigation:.0f} {unit_label}</p>", unsafe_allow_html=True)

            # 📊 Table
            st.subheader('Seasonal Water Budget:')
            
            # Filter by selected irrigation months
            start_month, end_month = irrigation_months
            filtered_df = df_irrigation[df_irrigation['month'].between(start_month, end_month)]


            filtered_df['month'] = pd.to_datetime(filtered_df['month'], format='%m').dt.month_name()
            # filtered_df[['ET0', 'week_irrigation']] = filtered_df[['ET0', 'irrigation']] #/ 4

            # round ET0 and irrigation to the nearest 5 if units are mm
            if "Imperial" in unit_system:
                filtered_df[['ET0', 'irrigation']] = filtered_df[['ET0', 'irrigation']].round(1)
            else:
                filtered_df[['ET0', 'irrigation']] = (filtered_df[['ET0', 'irrigation']]/5).round()*5

            st.dataframe(
                filtered_df[['month', 'ET0', 'irrigation', 'alert']]
                .rename(columns={
                    'month': 'Month',
                    'ET0': f'ET₀ ({unit_label})',
                    'irrigation': f'Irrigation ({unit_label} )',
                    # 'FWB': 'SW1',
                    'alert': 'Alert'
                }).round(1),
                hide_index=True
            )
            
            # 📈 Plot
            fig, ax = plt.subplots()

            # Filter data for plotting
            start_month, end_month = irrigation_months
            plot_df = df_irrigation[df_irrigation['month'].between(start_month, end_month)].copy()
            plot_df['cumsum_irrigation'] = plot_df['irrigation'].cumsum()

            # plot_df['month'] = pd.to_datetime(plot_df['month'], format='%m')

            # Add drought bars (SW1 = 0) only if they exist
            ax.bar(plot_df.loc[plot_df['SW1'] > 0, 'month'],
                    plot_df.loc[plot_df['SW1'] > 0, 'cumsum_irrigation'], alpha=1, label="Irrigation")

            if (plot_df['SW1'] == 0).any():
                ax.bar(plot_df.loc[plot_df['SW1'] == 0, 'month'],
                        plot_df.loc[plot_df['SW1'] == 0, 'cumsum_irrigation'], alpha=1, label="Deficit Irrigation",
                        color='#FF4B4B')

            # Add a shaded area for SW1 behind the bars
            ax.fill_between(
                plot_df['month'],  # X-axis values (months)
                0,  # Start of the shaded area (baseline)
                plot_df['SW1'],  # End of the shaded area (SW1 values)
                color='#74ac72',  # Green color for the shaded area
                alpha=0.4,  # Transparency
                label="Water Budget"
            )

            # Set plot limits and labels
            ax.set_xlabel("Month")
            ax.set_ylabel(f"Water ({unit_label})")
            ax.legend()

            # Display the plot
            st.pyplot(fig)


        else:
            st.error("❌ No weather data available to generate the report.")
                
    else:
        st.info("Click you field ---->")
        image = Image.open("img/ExampleGraph.png")  # Assuming "images" folder in your repo
        st.image(image, caption="Example image of the graphical output", use_container_width=True)

