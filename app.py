import streamlit as st

st.title("My First App")

st.write("Welcome Dr Sagar 👨‍⚕️")

name = st.text_input("Enter your name")

if name:
    st.success(f"Hello {name}")