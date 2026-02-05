import streamlit as st
import time
import numpy as np
from imap.utils import initialize_ee
from imap.data import get_et0, get_rain, get_ndvi
from imap.map import display_map
from imap.calculation import calc_irrigation
from imap.ui import display_header, display_sidebar, display_results, display_no_data_message, display_initial_message

def main():
    st.set_page_config(layout='wide')
    initialize_ee()
    display_header()

    use_imperial, unit_system, unit_label, conversion_factor, m_winter, irrigation_months = display_sidebar(1, "mm")

    col2, col1 = st.columns([6, 4])

    with col1:
        map_data = display_map()

    with col2:
        if map_data and map_data["last_clicked"] is not None and "lat" in map_data["last_clicked"]:
            coords = map_data["last_clicked"]
            lat, lon = coords["lat"], coords["lng"]
            location = (lat, lon)

            now = time.time()
            last_loc = st.session_state.get("last_location")
            last_time = st.session_state.get("last_location_time", 0)

            if location != last_loc or (now - last_time > 5):
                st.session_state["last_location"] = location
                st.session_state["last_location_time"] = now
                st.session_state["et0"] = get_et0(lat, lon)
                st.session_state["rain"] = get_rain(lat, lon)
                st.session_state["ndvi"] = get_ndvi(lat, lon)

            rain = st.session_state.get("rain")
            ndvi = st.session_state.get("ndvi")
            et0 = st.session_state.get("et0")

            if rain is not None and ndvi is not None and et0 is not None:
                pNDVI = 0.8 * (1 - np.exp(-3 * ndvi))
                total_rain = rain * conversion_factor
                m_rain = st.sidebar.slider(f"Fix Rain to Field ({unit_label})", 0, int(round(1000 * conversion_factor)),
                                            int(total_rain), step=1, disabled=False,
                                            help="Do you know a better value? Do you think less water was retained in the soil?")

                df_irrigation = calc_irrigation(pNDVI, m_rain, et0, m_winter, irrigation_months, 1, conversion_factor)
                total_irrigation = df_irrigation['irrigation'].sum()
                m_irrigation = st.sidebar.slider(f"Water Allocation ({unit_label})", 0,
                                                    int(round(1500 * conversion_factor)),
                                                    int(total_irrigation), step=int(round(20 * conversion_factor)),
                                                    help="Here's the recommended irrigation. Are you constrained by water availability, or considering extra irrigation for salinity management?")
                
                irrigation_factor = m_irrigation / total_irrigation if total_irrigation > 0 else 0
                df_irrigation = calc_irrigation(pNDVI, m_rain, et0, m_winter, irrigation_months, irrigation_factor, conversion_factor)
                total_irrigation = df_irrigation['irrigation'].sum()

                display_results(rain, ndvi, pNDVI, et0, df_irrigation, total_irrigation, unit_label, conversion_factor, irrigation_months)
            else:
                display_no_data_message()
        else:
            display_initial_message()
