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

# ee.Initi11-alize(project="ee-orsperling")
# ee.Authenticate()


# 🌍 Function to Fetch NDVI from Google Earth Engine
@st.cache_data(show_spinner=False)
def get_ndvi(lat, lon):
    poi = ee.Geometry.Point([lon, lat])
    img = ee.ImageCollection('COPERNICUS/S2_HARMONIZED') \
        .filterDate(f"{datetime.now().year - 1}-05-01", f"{datetime.now().year - 1}-06-01") \
        .median()

    ndvi = img.normalizedDifference(['B8', 'B4']).reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=poi,
        scale=50
    ).get('nd')

    try:
        return round(ndvi.getInfo(), 2) if ndvi.getInfo() is not None else None
    except Exception as e:
        return None


@st.cache_data(show_spinner=False)
def get_rain(lat, lon):
    # Determine start date: Nov 1 of this or last year
    today = datetime.today()
    start_year = today.year - 1 if today.month < 11 else today.year
    start_date = f"{start_year}-11-01"

    # Build API URL
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": today.strftime("%Y-%m-%d"),
        "daily": "rain_sum",
        "timezone": "auto"
    }

    # Fetch and parse data
    openmeteo = openmeteo_requests.Client()
    responses = openmeteo.weather_api(url, params=params)
    response = responses[0]

    # Extract rain and time values
    time = response.Daily().Time()
    rain = response.Daily().Variables(0).ValuesAsNumpy()

    # Build DataFrame
    df = pd.DataFrame({"time": pd.to_datetime(time), "rain": rain})

    # Return total rainfall
    return round(df["rain"].sum(skipna=True), 1)


@st.cache_data(show_spinner=False)
def get_et0(lat, lon):
    today = datetime.today()
    start_date = f"{today.year - 5}-01-01"
    end_date = f"{today.year - 1}-12-31"

    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "et0_fao_evapotranspiration",
        "timezone": "auto"
    }

    openmeteo = openmeteo_requests.Client()
    responses = openmeteo.weather_api(url, params=params)
    response = responses[0]

    # Build dataframe

    daily=response.Daily()
    
    time = pd.date_range(
        start = pd.to_datetime(daily.Time(), unit = "s", utc = True),
        end = pd.to_datetime(daily.TimeEnd(), unit = "s", utc = True),
        freq = pd.Timedelta(seconds = daily.Interval()),
        inclusive = "left"
    )

    et0 = response.Daily().Variables(0).ValuesAsNumpy()

    # Build DataFrame
    df = pd.DataFrame({"time": time, "et0": et0})

    df["year"] = df["time"].dt.year
    df["month"] = df["time"].dt.month
    
    # Step 1: sum ET₀ per (year, month)
    monthly_sums = df.groupby(["year", "month"])["et0"].sum().reset_index()

    # Step 2: average monthly sums across years
    avg_monthly_et0 = monthly_sums.groupby("month")["et0"].mean().reset_index()
    avg_monthly_et0["et0"] = avg_monthly_et0["et0"]

    avg_monthly_et0.rename(columns={"et0": "ET0"}, inplace=True)

    return avg_monthly_et0


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

    rain1 = (rain + m_winter) * conversion_factor

    mnts = list(range(irrigation_months[0], irrigation_months[1] + 1))

    df.loc[~df['month'].isin(range(3, 11)), 'ET0'] = 0  # Zero ET0 for non-growing months
    df['ET0'] *= conversion_factor  # Convert ET0 to inches with 90% efficiency

    # Adjust ETa based on NDVI
    df['ETa'] = df['ET0'] * pNDVI / 0.7

    # # Soil water balance
    SWI = (rain1 - df.loc[~df['month'].isin(mnts), 'ETa'].sum() - 50 * conversion_factor) / len(mnts)

    df.loc[df['month'].isin(mnts), 'irrigation'] = df['ETa'] - SWI
    df['irrigation'] = df['irrigation'].clip(lower=0)
    df['irrigation'] = df['irrigation'].fillna(0)
    df["irrigation"] *= irrigation_factor

    vst = df.loc[df['month'] == 7, 'irrigation'] * 0.1
    df.loc[df['month'] == 7, 'irrigation'] *= 0.8
    df.loc[df['month'].isin([8, 9]), 'irrigation'] += vst.values[0] if not vst.empty else 0

    df['SW1'] = (rain1 - df['ETa'].cumsum() + df['irrigation'].cumsum()).clip(lower=0)

    df['alert'] = np.where(df['SW1'] == 0, 'drought', 'safe')

    return df


def save_map_as_image_static(lat, lon, zoom=15, size=(600, 450), marker_path='img/Marker.png', marker_width=50):
    # Esri satellite tile provider
    esri_satellite_url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"

    # Create static map
    m = StaticMap(size[0], size[1], url_template=esri_satellite_url)

    # Open and resize marker image by width (keeping aspect ratio)
    with Image.open(marker_path) as img:
        # Get original aspect ratio
        aspect_ratio = img.height / img.width
        new_height = int(marker_width * aspect_ratio)
        resized_img = img.resize((marker_width, new_height), Image.Resampling.LANCZOS)

        buffer = BytesIO()
        resized_img.save(buffer, format='PNG')
        buffer.seek(0)

    # Create and add marker
    marker = IconMarker((lon, lat), buffer, offset_x=marker_width // 2, offset_y=new_height)
    m.add_marker(marker)

    # Render and save
    image = m.render(zoom=zoom)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_file:
        image_path = tmp_file.name
        image.save(image_path)

    return image_path


# 🌟 **Streamlit UI**
st.markdown("<h1 style='text-align: center;'>G-WaB: Geographic Water Budget</h1>", unsafe_allow_html=True)
st.markdown(
    "<p style='text-align: center; font-size: 20px'>A <a href=\"https://www.bard-isus.org/\"> <strong>BARD</strong></a> research report by: </p>",
    unsafe_allow_html=True)
st.markdown(
    "<p style='text-align: center;'>For further information contact: <a href=\"mailto:orsp@volcani.agri.gov.il\"> <strong>Or Sperling</strong></a> (ARO-Volcani), <a href=\"mailto:mzwienie@ucdavis.edu\"> <strong>Maciej Zwieniecki</strong></a> (UC Davis), <a href=\"mailto:zellis@ucdavis.edu\"> <strong>Zac Ellis</strong></a> (UC Davis), and <a href=\"mailto:niccolo.tricerri@unito.it\"> <strong>Niccolò Tricerri</strong></a> (UNITO - IUSS Pavia)  </p>",
    unsafe_allow_html=True)

# 📌 **User Inputs**
# 🌍 Unit system selection

# st.sidebar.caption('This is a research report. For further information contact **Or Sperling** (orsp@volcani.agri.gov.il; ARO-Volcani), **Maciej Zwieniecki** (mzwienie@ucdavis.edu; UC Davis), or **Niccolo Tricerri** (niccolo.tricerri@unito.it; University of Turin).')
st.sidebar.image("img/Logo.png", caption="**i**rrigation - **M**onthly **A**nnual **P**lanner")

st.sidebar.header("Farm Data")
unit_system = st.sidebar.radio("Select Units", ["Metric (mm)", "Imperial (inches)"], help='What measures do you use?')

unit_label = "inches" if "Imperial" in unit_system else "mm"
conversion_factor = 0.03937 if "Imperial" in unit_system else 1

# Layout: 2 columns (map | output)
col2, col1 = st.columns([6, 4])

if "map_clicked" not in st.session_state:
    st.session_state.map_clicked = False

with col1:
    st.header("Select Location")

    # 🗺️ **Map Selection**
    map_data = display_map()

    if isinstance(map_data, dict) and (coords := map_data.get("last_clicked")) and {"lat", "lng"} <= coords.keys():
        st.info(
            "Report updated. Change you parameters or select any new location. You can generate and download a pdf report")

    else:
        st.info("🖱️ Click a location on the map to begin. The searchbar can help you find the zone of interest.")

with col2:
    # --- Sliders (trigger irrigation calc only)
    m_winter = st.sidebar.slider(f"Winter Irrigation ({unit_label})", 0, int(round(700 * conversion_factor)), 0,
                                 step=int(round(20 * conversion_factor)),
                                 help="Did you irrigate in winter? If yes, how much?")
                                 
    irrigation_months = st.sidebar.slider("Irrigation Months", 1, 12, (3, 10), step=1,
                                          help="During which months will you irrigate?")

    # --- Handle map click
    if map_data and isinstance(map_data, dict) and "last_clicked" in map_data:
        coords = map_data["last_clicked"]

        # ✅ Only proceed if coords is valid
        if coords and "lat" in coords and "lng" in coords:

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

            IF = 0.33 / (1 + np.exp(20 * (ndvi - 0.6))) + 1
            pNDVI = ndvi * IF

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

                # 📈 Plot
                st.subheader('Monthly Illustration:')
                fig, ax = plt.subplots()

                # Add drought bars (SW1 = 0) only if they exist
                ax.bar(df_irrigation.loc[df_irrigation['SW1'] > 0, 'month'],
                       df_irrigation.loc[df_irrigation['SW1'] > 0, 'irrigation'], alpha=1, label="Irrigation")

                if (df_irrigation['SW1'] == 0).any():
                    ax.bar(df_irrigation.loc[df_irrigation['SW1'] == 0, 'month'],
                           df_irrigation.loc[df_irrigation['SW1'] == 0, 'irrigation'], alpha=1, label="Drought",
                           color='#FF4B4B')

                # Add a shaded area for SW1 behind the bars
                ax.fill_between(
                    df_irrigation['month'],  # X-axis values (months)
                    0,  # Start of the shaded area (baseline)
                    df_irrigation['SW1'],  # End of the shaded area (SW1 values)
                    color='#74ac72',  # Green color for the shaded area
                    alpha=0.4,  # Transparency
                    label="Soil Water"
                )

                # Iterate through the data to conditionally color the bars
                bar_colors = ['#FF4B4B' if sw1 == 0 else '#3897c5' for sw1 in df_irrigation['SW1']]

                # Set plot limits and labels
                ax.set_ylim(bottom=-3.7 * conversion_factor)
                ax.set_xlabel("Month")
                ax.set_ylabel(f"Water Amount ({unit_label})")
                ax.legend()

                # Display the plot
                st.pyplot(fig)

                # 📊 Table
                st.subheader('Weekly Recommendations:')
                
                # Filter by selected irrigation months
                start_month, end_month = irrigation_months
                filtered_df = df_irrigation[df_irrigation['month'].between(start_month, end_month)]


                filtered_df['month'] = pd.to_datetime(filtered_df['month'], format='%m').dt.month_name()
                filtered_df[['ET0', 'ETa', 'week_irrigation']] = filtered_df[['ET0', 'ETa', 'irrigation']] / 4

                # round ET0 and irrigation to the nearest 5 if units are mm
                if "Imperial" in unit_system:
                    filtered_df[['ET0', 'week_irrigation']] = filtered_df[['ET0', 'week_irrigation']].round(1)
                else:
                    filtered_df[['ET0', 'week_irrigation']] = (filtered_df[['ET0', 'week_irrigation']]/5).round()*5

                st.dataframe(
                    filtered_df[['month', 'ET0', 'week_irrigation', 'alert']]
                    .rename(columns={
                        'month': 'Month',
                        'ET0': f'ET₀ ({unit_label})',
                        'ETa': f'ETa ({ unit_label})',
                        'week_irrigation_volume': f'Irrigation Volume ({unit_label})',
                        # 'week_irrigation_hours': f'Irrigation time (hours)',
                        'alert': 'Alert'
                    }).round(1),
                    hide_index=True
                )


                # Function to create a PDF report
                def create_pdf_report(fig, df_irrigation, ndvi, total_irrigation, unit_label, NotesText, lat, lon):

                    pdf = FPDF()
                    pdf.add_page()

                    pdf.set_font("Arial", 'B', 20)
                    pdf.cell(0, 10, "ALMOND - iMAP", ln=True, align="L")
                    pdf.set_font("Arial", 'B', 14)
                    pdf.cell(0, 9, "irrigation Monthly Annual Planner Report for ALMOND orchards", ln=True, align="L")
                    pdf.image("img/Logo.png", x=137, y=10, w=80)

                    pdf.ln(2)
                    pdf.set_font("Arial", size=13)
                    # pdf.cell(0, 8, f"NDVI: {ndvi}", ln=True)

                    month_names = pd.to_datetime(irrigation_months, format='%m').month_name()
                    month_names_str = ' - '.join(month_names)
                    pdf.cell(0, 8, f"Selected irrigation period: {month_names_str}", ln=True)
                    pdf.cell(0, 8, f"Seasonal ET0: {df_irrigation['ET0'].sum():.0f} {unit_label}", ln=True)

                    # pdf.cell(0, 8, f"Total Irrigation: {total_irrigation:.2f} {unit_label}", ln=True)
                    # pdf.cell(0, 8, f"Irrigation rate: {irrigation_rate:.2f} {unit_label}/hour", ln=True)

                    pdf.set_font("Arial", style='I', size=13)
                    half_width = (pdf.w - 2 * pdf.l_margin) - 50

                    pdf.multi_cell(half_width, 8, f"Notes: {NotesText}")

                    pdf.ln(4)
                    pdf.cell(0, 8, "Weekly plan:", ln=True)

                    # Filter by selected irrigation months
                    start_month, end_month = irrigation_months
                    filtered_df = df_irrigation[df_irrigation['month'].between(start_month, end_month)]

                    
                    filtered_df['month'] = pd.to_datetime(filtered_df['month'], format='%m').dt.month_name()
                    filtered_df[['ET0', 'ETa', 'week_irrigation_volume']] = filtered_df[['ET0', 'ETa', 'irrigation']] / 4

                    selected_columns_df = (
                        filtered_df[['month', 'ET0', 'ETa', 'week_irrigation_volume', 'alert']]
                        .rename(columns={
                            'month': 'Month',
                            'ET0': f'ET0 ({unit_label})',
                            'ETa': f'ETa ({unit_label})',
                            'week_irrigation_volume': f'Irrigation Volume ({unit_label})',
                            # 'week_irrigation_hours': f'Irrigation time (hours)',
                            'alert': 'Alert'
                        })
                        .round(1))

                    # Add table headers
                    headers = selected_columns_df.columns.tolist()

                    # Set custom column widths for each column
                    column_widths = [25, 35, 35, 55, 28]  # Define a width for each column

                    # Set font for headers
                    pdf.set_font("Arial", 'B', 12)
                    for i, header in enumerate(headers):
                        pdf.cell(column_widths[i], 10, header, border=1, align='C')  # Use the respective column width
                    pdf.ln()  # Line break after headers

                    # Set font for data rows
                    pdf.set_font("Arial", '', 12)

                    # Iterate over each row of the filtered DataFrame
                    for index, row in selected_columns_df.iterrows():
                        for i, value in enumerate(row):
                            pdf.cell(column_widths[i], 10, str(value), border=1,
                                     align='C')  # Use respective width for each column
                        pdf.ln()  # Line break after each row

                    pdf.ln(3)

                    pdf.set_font("Arial", size=13)
                    pdf.cell(0, 8,
                             f"data for Location (lat: {round(lat, 3)} lon: {round(lon, 3)}) - NDVI: {ndvi} - Total Irrigation: {total_irrigation:.2f} {unit_label}",
                             ln=True, align='C')
                    pdf.cell(0, 8, f"", ln=True)

                    pdf.ln(3)

                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmpfile:
                        fig.savefig(tmpfile.name, format="PNG", bbox_inches='tight')
                        tmpfile.seek(0)
                        image_path = tmpfile.name

                    image_width = 100
                    image_height = 95

                    bottom_margin = pdf.b_margin
                    y_position = pdf.h - bottom_margin - image_height

                    pdf.image(image_path, x=pdf.l_margin, y=y_position, w=image_width)
                    os.remove(image_path)

                    image_path = save_map_as_image_static(lat, lon)
                    image_width = 87
                    image_height = 93
                    right_margin = pdf.r_margin
                    bottom_margin = pdf.b_margin

                    # Calculate X and Y for bottom-right positioning
                    x_position = pdf.w - right_margin - image_width
                    y_position = pdf.h - bottom_margin - image_height

                    pdf.image(image_path, x=x_position, y=y_position, w=image_width)
                    os.remove(image_path)

                    current_date = datetime.now().strftime("%B %d, %Y")
                    pdf.set_y(-33)
                    pdf.set_font("Arial", size=11)
                    pdf.cell(0, 10, current_date, 0, 0, 'L')
                    pdf.cell(0, 10, "Report from Or, Maciej, Zac, and Niccolò.", 0, 0, 'R')

                    pdf_bytes = pdf.output(dest="S").encode("latin1")
                    return pdf_bytes


                NotesText = st.text_input("Add your notes for the report:")

                if all(key in st.session_state for key in ["ndvi", "et0"]):
                    if "pdf_ready" not in st.session_state:
                        st.session_state["pdf_ready"] = False
                    if "pdf_downloaded" not in st.session_state:
                        st.session_state["pdf_downloaded"] = False

                    if st.button("⚙️ Generate PDF Report"):
                        with st.spinner("🛠️ Generating PDF report..."):
                            pdf_data = create_pdf_report(
                                fig, df_irrigation, st.session_state["ndvi"],
                                total_irrigation, unit_label, NotesText, lat, lon
                            )
                            st.session_state["pdf_data"] = pdf_data
                            st.session_state["pdf_ready"] = True
                            st.session_state["pdf_downloaded"] = False
                            st.success("✅ PDF report generated!")

                    # Show download button only if PDF is ready and not yet downloaded
                    if st.session_state["pdf_ready"] and not st.session_state["pdf_downloaded"]:
                        # Create a download button that also sets the "downloaded" flag
                        if st.download_button(
                                label="📄 Download PDF Report",
                                data=st.session_state["pdf_data"],
                                file_name="iMAP_Report.pdf",
                                mime="application/pdf"
                        ):
                            st.session_state["pdf_downloaded"] = True  # hide button after download
                else:
                    st.error("❌ No weather data available to generate the report.")




            else:
                st.error("❌ No weather data found for this location.")
        else:
            st.markdown("""
            <style>
            .centered-stats {
                text-align: center;
                font-size: 27px;
                font-weight: bold;
                margin-top: 15px;
            }

            .tooltip-icon {
              display: inline-block;
              width: 17px;
              height: 17px;
              background-color: #3498db;
              color: white;
              border-radius: 50%;
              text-align: center;
              font-size: 12px;
              line-height: 16px;
              margin-left: 3px;
              cursor: help;
              vertical-align: middle;
            }
            .tooltip-icon::after {
              content: "i";
            }
            </style>
            """, unsafe_allow_html=True)

            st.markdown(f"""
            <div class="centered-stats">
              <span title="Potential Normalized Difference Vegetation Index — shows vegetation health."> <span class="tooltip-icon"></span> NDVI</span>: 0.00 | 
              <span title="Potential Total Evapotranspiration for the season"> <span class="tooltip-icon"></span> ET₀</span>: 00 {unit_label} | 
              <span title="Total amount of water suggested for the season."> <span class="tooltip-icon"></span> Irrigation</span>: 00 {unit_label}
            </div>
            """, unsafe_allow_html=True)
            image = Image.open("img/ExampleGraph.png")  # Assuming "images" folder in your repo
            st.image(image, caption="Example image of the graphical output", use_container_width=True)

    else:
        st.info("🖱️ Click a location on the map to begin.")
