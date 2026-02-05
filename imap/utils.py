import streamlit as st
import ee
from google.oauth2 import service_account

def initialize_ee():
    # ee.Initialize(project="rsc-gwab-lzp")
    # """Initializes the Earth Engine API with credentials."""
     credentials = service_account.Credentials.from_service_account_info(
         st.secrets["gcp_service_account"],
         scopes=["https://www.googleapis.com/auth/earthengine"]
     )
     ee.Initialize(credentials)
