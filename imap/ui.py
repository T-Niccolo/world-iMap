import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from PIL import Image

def display_header():
    """Displays the header of the Streamlit app."""
    st.markdown("<h1 style='text-align: center;'>G-WaB: Geographic Water Budget</h1>", unsafe_allow_html=True)
    st.markdown(
        "<p style='text-align: center; font-size: 20px'>A <a href=\"https://www.bard-isus.org/\"> <strong>BARD</strong></a> research report by: </p>"
        "<p style='text-align: center;'><a href=\"mailto:orsp@volcani.agri.gov.il\"> <strong>Or Sperling</strong></a> (ARO-Volcani), "
        "<a href=\"mailto:mzwienie@ucdavis.edu\"> <strong>Maciej Zwieniecki</strong></a> (UC Davis), "
        "<a href=\"mailto:zellis@ucdavis.edu\"> <strong>Zac Ellis</strong></a> (UC Davis), "
        "and <a href=\"mailto:niccolo.tricerri@unito.it\"> <strong>Niccolò Tricerri</strong></a> (UNITO - IUSS Pavia)  </p>",
        unsafe_allow_html=True)

def display_sidebar(conversion_factor, unit_label):
    """Displays the sidebar with user inputs."""
    st.sidebar.image("img/Marker.png")
    st.sidebar.header("Farm Data")
    use_imperial = st.sidebar.toggle("Use Imperial Units (inches)")
    unit_system = "Imperial (inches)" if use_imperial else "Metric (mm)"
    unit_label = "inches" if use_imperial else "mm"
    conversion_factor = 0.03937 if use_imperial else 1

    m_winter = st.sidebar.slider(f"Winter Irrigation ({unit_label})", 0, int(round(700 * conversion_factor)), 0,
                                step=int(round(20 * conversion_factor)),
                                help="Did you irrigate in winter? If yes, how much?")
                                
    irrigation_months = st.sidebar.slider("Irrigation Months", 1, 12, (3, 10), step=1,
                                        help="During which months will you irrigate?")
    
    return use_imperial, unit_system, unit_label, conversion_factor, m_winter, irrigation_months

def display_results(rain, ndvi, pNDVI, et0, df_irrigation, total_irrigation, unit_label, conversion_factor, irrigation_months):
    """Displays the results, including table and plot."""
    st.markdown(f"<p style='text-align: center; font-size: 30px;'>Rain: {rain * conversion_factor:.2f} {unit_label} | ET₀: {df_irrigation['ET0'].sum():.0f} {unit_label}</p>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align: center; font-size: 30px;'>NDVI: {ndvi:.2f} | pNDVI: {pNDVI:.2f}| Irrigation: {total_irrigation:.0f} {unit_label}</p>", unsafe_allow_html=True)

    st.subheader('Seasonal Water Budget:')
    
    start_month, end_month = irrigation_months
    filtered_df = df_irrigation[df_irrigation['month'].between(start_month, end_month)]

    filtered_df['month'] = pd.to_datetime(filtered_df['month'], format='%m').dt.month_name()

    if "Imperial" in unit_label:
        filtered_df[['ET0', 'irrigation']] = filtered_df[['ET0', 'irrigation']].round(1)
    else:
        filtered_df[['ET0', 'irrigation']] = (filtered_df[['ET0', 'irrigation']]/5).round()*5

    st.dataframe(
        filtered_df[['month', 'ET0', 'irrigation', 'alert']]
        .rename(columns={
            'month': 'Month',
            'ET0': f'ET₀ ({unit_label})',
            'irrigation': f'Irrigation ({unit_label} )',
            'alert': 'Alert'
        }).round(1),
        hide_index=True
    )
    
    fig, ax = plt.subplots()

    start_month, end_month = irrigation_months
    plot_df = df_irrigation[df_irrigation['month'].between(start_month-1, end_month)].copy()
    plot_df['cumsum_irrigation'] = plot_df['irrigation'].cumsum()

    ax.bar(plot_df.loc[plot_df['SW1'] > 0, 'month'],
            plot_df.loc[plot_df['SW1'] > 0, 'cumsum_irrigation'], alpha=1, label="Irrigation")

    if (plot_df['SW1'] == 0).any():
        ax.bar(plot_df.loc[plot_df['SW1'] == 0, 'month'],
                plot_df.loc[plot_df['SW1'] == 0, 'cumsum_irrigation'], alpha=1, label="Deficit Irrigation",
                color='#FF4B4B')

    ax.fill_between(
        plot_df['month'],
        0,
        plot_df['SW1'],
        color='#74ac72',
        alpha=0.4,
        label="Water Budget"
    )

    ax.set_xlabel("Month")
    ax.set_ylabel(f"Water ({unit_label})")
    ax.legend()

    st.pyplot(fig)

def display_no_data_message():
    """Displays a message when no weather data is available."""
    st.error("❌ No weather data available to generate the report.")

def display_initial_message():
    """Displays the initial message and example image."""
    st.info("Click you field ---->")
    image = Image.open("img/ExampleGraph.png")
    st.image(image, caption="Example image of the graphical output", use_container_width=True)
