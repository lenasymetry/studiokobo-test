# App minimale de diagnostic Streamlit Cloud (à supprimer ensuite).
import plotly.graph_objects as go
import streamlit as st

st.title("Test Streamlit Cloud")
st.plotly_chart(go.Figure(go.Scatter3d(x=[0, 1], y=[0, 1], z=[0, 1])))
