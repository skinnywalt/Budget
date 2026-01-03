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
    credentials = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES
    )
    client = gspread.authorize(credentials)
    return client.open("budget_database")

# --- AUTHENTICATION ---
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    if make_hashes(password) == hashed_text:
        return True
    return False

def create_user(sheet, username, password):
    users_worksheet = sheet.worksheet("Users")
    if username in users_worksheet.col_values(1):
        return False
    users_worksheet.append_row([username, make_hashes(password)])
    return True

def login_user(sheet, username, password):
    users_worksheet = sheet.worksheet("Users")
    try:
        cell = users_worksheet.find(username)
        stored_hash = users_worksheet.cell(cell.row, cell.col + 1).value
        if check_hashes(password, stored_hash):
            return True
        return False
    except:
        return False

# --- DATA FUNCTIONS ---
def add_transaction(sheet, username, date, type_, category, amount, notes):
    ws = sheet.worksheet("Transactions")
    ws.append_row([str(date), username, type_, category, amount, notes])

def get_data(sheet, username):
    ws = sheet.worksheet("Transactions")
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    if df.empty:
        return pd.DataFrame(columns=['Date', 'Username', 'Type', 'Category', 'Amount', 'Notes'])
    
    if 'Username' in df.columns:
        df = df[df['Username'] == username]
    
    if not df.empty:
        df['Date'] = pd.to_datetime(df['Date'])
        df['Amount'] = pd.to_numeric(df['Amount'])
        df = df.sort_values(by='Date')
        
    return df

# --- MAIN APP ---
def main():
    st.set_page_config(page_title="Smart Budget", layout="wide")
    
    try:
        sheet = connect_to_gsheet()
    except Exception as e:
        st.error(f"Connection Error: {e}")
        st.stop()

    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        st.session_state['username'] = ''

    # --- LOGIN SCREEN ---
    if not st.session_state['logged_in']:
        st.title("🔐 Smart Budget Login")
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
                try:
                    u_ws = sheet.worksheet("Users")
                    if not u_ws.row_values(1): u_ws.append_row(["Username", "PasswordHash"])
                    t_ws = sheet.worksheet("Transactions")
                    if not t_ws.row_values(1): t_ws.append_row(["Date", "Username", "Type", "Category", "Amount", "Notes"])
                except: pass
                if create_user(sheet, new_user, new_password): st.success("Created! Login now.")
                else: st.error("Username taken.")

    # --- MAIN DASHBOARD ---
    else:
        st.sidebar.title(f"Wallet: {st.session_state['username']}")
        if st.sidebar.button("Logout"):
            st.session_state['logged_in'] = False
            st.rerun()
            
        # Filters
        st.sidebar.header("View Settings")
        # Generate Month List
        period_options = ["All Time"] + [datetime(2025, i, 1).strftime('%B') for i in range(1, 13)]
        selected_period = st.sidebar.selectbox("Time Period", period_options)
        
        # --- INPUT SECTION ---
        with st.expander("➕ Update Wallet / Add Transaction", expanded=False):
            col1, col2, col3, col4, col5 = st.columns(5)
            t_date = col1.date_input("Date")
            t_type = col2.selectbox("Type", ["Income", "Need", "Want", "Saving", "Debt"]) 
            t_cat = col3.text_input("Category")
            t_amt = col4.number_input("Amount", min_value=0.0, step=10.0)
            t_note = col5.text_input("Notes")
            
            if st.button("Record Transaction"):
                add_transaction(sheet, st.session_state['username'], t_date, t_type, t_cat, t_amt, t_note)
                st.success("Logged!")
                st.rerun()

        # --- DATA PROCESSING ---
        df = get_data(sheet, st.session_state['username'])
        
        if not df.empty:
            # 1. ALWAYS calculate global Running Balance (Current Net Worth)
            df['Signed_Amount'] = df.apply(lambda x: x['Amount'] if x['Type'] == 'Income' else -x['Amount'], axis=1)
            df['Running_Balance'] = df['Signed_Amount'].cumsum()
            current_net_worth = df['Running_Balance'].iloc[-1]

            # 2. Filter Data based on selection
            filtered_df = df.copy()
            if selected_period != "All Time":
                filtered_df = filtered_df[filtered_df['Date'].dt.strftime('%B') == selected_period]

            # --- TOP METRICS ---
            # These change based on the filter (Monthly Stats vs All Time Stats)
            income_period = filtered_df[filtered_df['Type'] == 'Income']['Amount'].sum()
            expenses_period = filtered_df[filtered_df['Type'].isin(['Need', 'Want', 'Saving', 'Debt'])]['Amount'].sum()
            savings_period = filtered_df[filtered_df['Type'] == 'Saving']['Amount'].sum()
            
            st.markdown(f"### 🏦 Snapshot: {selected_period}")
            
            # Layout: 4 columns. 
            # First column is ALWAYS Total Net Worth (Does not change with filter).
            # Next 3 columns are Specific to the selected month/period.
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("💰 Total Wallet", f"${current_net_worth:,.2f}", help="Your total cash right now (All Time).")
            m2.metric("Income", f"${income_period:,.2f}")
            m3.metric("Expenses", f"${expenses_period:,.2f}", delta="-Outflow", delta_color="inverse")
            m4.metric("Savings", f"${savings_period:,.2f}")
            
            st.divider()

            # --- HYBRID VISUALIZATION LOGIC ---
            
            # CASE A: "All Time" Selected -> Show TRENDS (Line Chart)
            if selected_period == "All Time":
                st.subheader("📈 Wealth Growth (All Time)")
                if not df.empty:
                    fig_trend = px.line(df, x='Date', y='Running_Balance', markers=True, 
                                        title="Net Worth Over Time")
                    st.plotly_chart(fig_trend, use_container_width=True)
                
                # Show Total Pie Chart
                st.subheader("Total Spending Habits")
                expenses_only = df[df['Type'].isin(['Need', 'Want', 'Debt'])]
                if not expenses_only.empty:
                    fig_pie = px.pie(expenses_only, values='Amount', names='Type', hole=0.4)
                    st.plotly_chart(fig_pie, use_container_width=True)

            # CASE B: Specific Month Selected -> Show BUDGET (Bar/Pie Charts)
            else:
                st.subheader(f"📊 Budget Breakdown: {selected_period}")
                
                if not filtered_df.empty:
                    c1, c2 = st.columns(2)
                    
                    with c1:
                        # Income vs Expenses Bar Chart
                        st.caption("Income vs Outflow")
                        # Simple dataframe for bar chart
                        bar_data = pd.DataFrame({
                            "Category": ["Income", "Expenses"],
                            "Amount": [income_period, expenses_period]
                        })
                        fig_bar = px.bar(bar_data, x="Category", y="Amount", color="Category", 
                                         color_discrete_map={"Income": "green", "Expenses": "red"})
                        st.plotly_chart(fig_bar, use_container_width=True)
                    
                    with c2:
                        # Detailed Pie Chart (Where did the money go?)
                        st.caption("Expense Categories")
                        expenses_only = filtered_df[filtered_df['Type'] != 'Income']
                        if not expenses_only.empty:
                            fig_pie = px.pie(expenses_only, values='Amount', names='Category', hole=0.4)
                            st.plotly_chart(fig_pie, use_container_width=True)
                        else:
                            st.info("No expenses logged this month.")
                else:
                    st.info(f"No transactions found for {selected_period}.")

            # --- RAW DATA ---
            with st.expander("View Transaction History"):
                st.dataframe(filtered_df[['Date', 'Type', 'Category', 'Amount', 'Notes']].sort_values(by='Date', ascending=False), 
                             use_container_width=True)

if __name__ == '__main__':
    main()