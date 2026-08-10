"""Small visual layer shared by all Streamlit pages."""
from __future__ import annotations

import streamlit as st


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        .block-container {max-width: 1440px; padding-top: 1.5rem; padding-bottom: 4rem;}
        h1, h2, h3 {letter-spacing: -0.02em; color: #17202A;}
        [data-testid="stMetric"] {background: #fff; border: 1px solid #DFE4EA;
          border-radius: 12px; padding: 14px 16px;}
        [data-testid="stMetricValue"] {font-variant-numeric: tabular-nums;}
        [data-testid="stSidebar"] {border-right: 1px solid #DFE4EA;}
        .stButton > button, .stDownloadButton > button {border-radius: 8px; min-height: 44px;}
        :focus-visible {outline: 3px solid rgba(49,92,244,.35)!important; outline-offset: 2px;}
        @media (max-width: 768px) {
          .block-container {padding-left: 1rem; padding-right: 1rem;}
          [data-testid="stHorizontalBlock"] {flex-wrap: wrap;}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
