import folium
from streamlit_folium import st_folium
from folium.plugins import Geocoder

def display_map():
    """Displays an interactive map for coordinate selection."""
    map_center = [31.709172, 34.800522]
    zoom = 15

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
