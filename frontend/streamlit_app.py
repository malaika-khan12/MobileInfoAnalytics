"""Streamlit analytics view using the same product data and constraints."""
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Mobile Analytics", page_icon="📱", layout="wide")
st.title("Mobile market intelligence")
st.caption("Fixture-backed analysis · six governed sources · refreshed 18 Aug 2026")

source = st.sidebar.multiselect(
    "Sources",
    ["MyMobile", "Daraz", "GSMArena", "Mega.pk", "WhataMobile", "WhatMobile"],
    default=["MyMobile", "Daraz", "GSMArena", "Mega.pk", "WhataMobile", "WhatMobile"],
)
period = st.sidebar.selectbox("Period", ["Last 30 days", "Last 7 days", "Last 90 days"])

metrics = [("15,284", "Known devices", "+6.8%"), ("48,921", "Active offers", "+4.2%"),
           ("96.4%", "Field completeness", "+1.1%"), ("93.7%", "Collection success", "−0.6%")]
for column, (value, label, delta) in zip(st.columns(4), metrics):
    column.metric(label, value, delta)

trend = pd.DataFrame({
    "Date": pd.date_range("2026-08-01", periods=12),
    "Devices": [11140, 11480, 11710, 11960, 12340, 12720, 13110, 13680, 14120, 14590, 15020, 15284],
    "Offers": [35100, 36400, 37200, 38600, 39750, 41100, 42900, 44300, 45500, 46900, 48120, 48921],
}).set_index("Date")
st.subheader("Catalogue growth")
st.line_chart(trend)

left, right = st.columns(2)
with left:
    st.subheader("Brand share")
    st.bar_chart(pd.DataFrame({"Share": [31, 24, 17, 12, 9, 7]}, index=["Samsung", "Xiaomi", "Apple", "Infinix", "Oppo", "Other"]))
with right:
    st.subheader("Source health")
    st.dataframe(pd.DataFrame({
        "Source": source or ["No source selected"],
        "Status": ["Healthy" if item != "GSMArena" else "Rate limited" for item in source] or ["—"],
        "Period": [period] * max(1, len(source)),
    }), use_container_width=True, hide_index=True)

st.info("This interface uses deterministic fixture data. Connect the Flask API contracts before labelling values as live.")
