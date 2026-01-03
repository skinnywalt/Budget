import streamlit as st
import pandas as pd
import hashlib
import plotly.express as px
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# --- GOOGLE SHEETS SETUP ---
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def connect_to_gsheet():
    # Connect using Streamlit Secrets
    credentials = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES
    )
    client = gspread.authorize(credentials)
    # Open the spreadsheet by name
    return client.open("budget_database")

# --- AUTHENTICATION FUNCTIONS ---
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    if make_hashes(password) == hashed_text:
        return True
    return False

def create_user(sheet, username, password):
    users_worksheet = sheet.worksheet("Users")
    # Check if user exists
    existing_users = users_worksheet.col_values(1) # Column 1 is usernames
    if username in existing_users:
        return False
    
    # Add new user
    users_worksheet.append_row([username, make_hashes(password)])
    return True

def login_user(sheet, username, password):
    users_worksheet = sheet.worksheet("Users")
    try:
        # Find the cell with the username
        cell = users_worksheet.find(username)
        # Get the password hash from the next column
        stored_hash = users_worksheet.cell(cell.row, cell.col + 1).value
        if check_hashes(password, stored_hash):
            return True
        return False
    except:
        return False

# --- DATA FUNCTIONS ---
def add_transaction(sheet, username, date, type_, category, amount, notes):
    ws = sheet.worksheet("Transactions")
    # Store dates as string for Sheets compatibility
    ws.append_row([str(date), username, type_, category, amount, notes])

def get_data(sheet, username):
    ws = sheet.worksheet("Transactions")
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    
    # If sheet is empty, return empty df
    if df.empty:
        return pd.DataFrame(columns=['Date', 'Username', 'Type', 'Category', 'Amount', 'Notes'])
    
    # Filter by username
    if 'Username' in df.columns:
        df = df[df['Username'] == username]
    
    # Convert types safely
    if not df.empty:
        df['Date'] = pd.to_datetime(df['Date'])
        df['Amount'] = pd.to_numeric(df['Amount'])
        
    return df

# --- MAIN APP ---
def main():
    st.set_page_config(page_title="Cloud Budget", layout="wide")
    
    try:
        sheet = connect_to_gsheet()
    except Exception as e:
        st.error(f"Connection Error: {e}")
        st.stop()

    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        st.session_state['username'] = ''

    # --- LOGIN PAGE ---
    if not st.session_state['logged_in']:
        st.title("🔐 Cloud Budget Login")
        menu = ["Login", "Sign Up"]
        choice = st.selectbox("Menu", menu)

        if choice == "Login":
            username = st.text_input("Username")
            password = st.text_input("Password", type='password')
            if st.button("Login"):
                if login_user(sheet, username, password):
                    st.session_state['logged_in'] = True
                    st.session_state['username'] = username
                    st.rerun()
                else:
                    st.error("Incorrect Username/Password")
        
        elif choice == "Sign Up":
            new_user = st.text_input("New Username")
            new_password = st.text_input("New Password", type='password')
            if st.button("Create Account"):
                # Initialize headers if first user
                try:
                    u_ws = sheet.worksheet("Users")
                    if not u_ws.row_values(1):
                        u_ws.append_row(["Username", "PasswordHash"])
                    
                    t_ws = sheet.worksheet("Transactions")
                    if not t_ws.row_values(1):
                        t_ws.append_row(["Date", "Username", "Type", "Category", "Amount", "Notes"])
                except:
                    pass

                if create_user(sheet, new_user, new_password):
                    st.success("Account created! Please log in.")
                else:
                    st.error("Username already taken.")

    # --- DASHBOARD ---
    else:
        st.sidebar.title(f"Hi, {st.session_state['username']}")
        if st.sidebar.button("Logout"):
            st.session_state['logged_in'] = False
            st.rerun()
            
        st.sidebar.header("Filters")
        today = datetime.now()
        selected_month = st.sidebar.slider("Month", 1, 12, today.month)
        
        # INPUT
        with st.expander("➕ Add New Transaction"):
            col1, col2, col3, col4, col5 = st.columns(5)
            t_date = col1.date_input("Date")
            t_type = col2.selectbox("Type", ["Income", "Need", "Want", "Saving"])
            t_cat = col3.text_input("Category")
            t_amt = col4.number_input("Amount", min_value=0.0)
            t_note = col5.text_input("Notes")
            
            if st.button("Add Entry"):
                add_transaction(sheet, st.session_state['username'], t_date, t_type, t_cat, t_amt, t_note)
                st.success("Added to Google Sheet!")
                st.rerun()

        # METRICS
        df = get_data(sheet, st.session_state['username'])
        
        if not df.empty:
            df = df[df['Date'].dt.month == selected_month]
            
            # Simple aggregations
            inc = df[df['Type'] == 'Income']['Amount'].sum() if not df[df['Type'] == 'Income'].empty else 0
            needs = df[df['Type'] == 'Need']['Amount'].sum() if not df[df['Type'] == 'Need'].empty else 0
            wants = df[df['Type'] == 'Want']['Amount'].sum() if not df[df['Type'] == 'Want'].empty else 0
            savings = df[df['Type'] == 'Saving']['Amount'].sum() if not df[df['Type'] == 'Saving'].empty else 0
            
            # Display
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Income", f"${inc}")
            m2.metric("Needs", f"${needs}")
            m3.metric("Wants", f"${wants}")
            m4.metric("Savings", f"${savings}")
            
            # Chart
            st.subheader("Breakdown")
            if needs + wants + savings > 0:
                fig = px.pie(names=['Needs', 'Wants', 'Savings'], values=[needs, wants, savings])
                st.plotly_chart(fig, use_container_width=True)
            
            # Data Table
            st.dataframe(df)

if __name__ == '__main__':
    main()