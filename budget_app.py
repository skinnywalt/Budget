import streamlit as st
import pandas as pd
import hashlib
import plotly.express as px
from datetime import datetime, date
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

def delete_transaction(sheet, row_index):
    ws = sheet.worksheet("Transactions")
    ws.delete_rows(row_index)

def get_data(sheet, username):
    ws = sheet.worksheet("Transactions")
    data = ws.get_all_values()
    
    if not data:
        return pd.DataFrame(columns=['Date', 'Username', 'Type', 'Category', 'Amount', 'Notes', 'RowIndex'])
    
    headers = data[0]
    rows = data[1:]
    
    df = pd.DataFrame(rows, columns=headers)
    df['RowIndex'] = range(2, len(rows) + 2)
    
    if 'Username' in df.columns:
        df = df[df['Username'] == username]
    
    if not df.empty:
        df['Date'] = pd.to_datetime(df['Date'])
        df['Amount'] = pd.to_numeric(df['Amount'])
        df = df.sort_values(by='Date')
        
    return df

# --- MAIN APP ---
def main():
    st.set_page_config(page_title="Future-Proof Budget", layout="wide")
    
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
        st.title("🔐 Future-Proof Budget Login")
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

    # --- MAIN APPLICATION ---
    else:
        st.sidebar.title(f"Wallet: {st.session_state['username']}")
        if st.sidebar.button("Logout"):
            st.session_state['logged_in'] = False
            st.rerun()

        # --- TABS ---
        tab1, tab2 = st.tabs(["📊 Dashboard", "📝 Manage Transactions"])

        # ==========================
        # TAB 1: DASHBOARD
        # ==========================
        with tab1:
            st.sidebar.header("View Settings")
            period_options = ["All Time"] + [datetime(2025, i, 1).strftime('%B') for i in range(1, 13)]
            selected_period = st.sidebar.selectbox("Time Period", period_options)
            
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

            df = get_data(sheet, st.session_state['username'])
            
            if not df.empty:
                # --- LOGIC SPLIT: PAST vs FUTURE ---
                today_date = datetime.now().date()
                
                # 1. Past Data
                past_df = df[df['Date'].dt.date <= today_date].copy()
                past_df['Signed_Amount'] = past_df.apply(lambda x: x['Amount'] if x['Type'] == 'Income' else -x['Amount'], axis=1)
                current_net_worth = past_df['Signed_Amount'].sum()
                
                # 2. Future Data
                future_df = df[df['Date'].dt.date > today_date].copy()
                future_needs = future_df[future_df['Type'] == 'Need']['Amount'].sum()
                
                # 3. Savings Analysis
                total_savings_cash = past_df[past_df['Type'] == 'Saving']['Amount'].sum()
                free_savings = total_savings_cash - future_needs

                # --- TOP METRICS ---
                st.markdown(f"### 🏦 Current Standing (As of {today_date})")
                
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("💰 Current Wallet", f"${current_net_worth:,.2f}", 
                          help="Money you physically have right now. Does NOT include future bills.")
                
                m2.metric("🛡️ Free Savings", f"${free_savings:,.2f}", 
                          delta=f"-${future_needs:,.2f} Reserved" if future_needs > 0 else "All Clear",
                          help="Total Savings minus any Future Needs you have scheduled.")
                
                m3.metric("📅 Future Needs", f"${future_needs:,.2f}")
                
                if selected_period != "All Time":
                    month_df = df[df['Date'].dt.strftime('%B') == selected_period]
                    month_spend = month_df[month_df['Type'].isin(['Need', 'Want'])]['Amount'].sum()
                    m4.metric(f"{selected_period} Spending", f"${month_spend:,.2f}")
                else:
                    m4.metric("Total Debt Paid", f"${past_df[past_df['Type'] == 'Debt']['Amount'].sum():,.2f}")

                st.divider()

                # --- VISUALIZATIONS ---
                if selected_period == "All Time":
                    st.subheader("📈 Projection: History + Future")
                    
                    df_proj = df.copy()
                    df_proj['Signed_Amount'] = df_proj.apply(lambda x: x['Amount'] if x['Type'] == 'Income' else -x['Amount'], axis=1)
                    df_proj['Running_Balance'] = df_proj['Signed_Amount'].cumsum()
                    
                    # Color status
                    df_proj['Status'] = df_proj['Date'].dt.date.apply(lambda x: 'Future' if x > today_date else 'History')
                    
                    fig_trend = px.line(df_proj, x='Date', y='Running_Balance', 
                                        color='Status', 
                                        markers=True,
                                        color_discrete_map={'History': 'blue', 'Future': 'orange'},
                                        title="Balance Trajectory (Blue = Real, Orange = Projected)")
                    
                    # === FIX: Convert 'today_date' to numeric milliseconds for Plotly ===
                    # We combine today's date with min time (00:00:00) then get timestamp * 1000
                    today_numeric = datetime.combine(today_date, datetime.min.time()).timestamp() * 1000
                    
                    fig_trend.add_vline(x=today_numeric, line_dash="dash", line_color="green", annotation_text="Today")
                    
                    st.plotly_chart(fig_trend, use_container_width=True)

                else:
                    # MONTHLY VIEW
                    st.subheader(f"📊 {selected_period} Outlook")
                    month_df = df[df['Date'].dt.strftime('%B') == selected_period]
                    
                    if not month_df.empty:
                        c1, c2 = st.columns(2)
                        with c1:
                            st.caption("Income vs Expenses")
                            inc = month_df[month_df['Type'] == 'Income']['Amount'].sum()
                            exp = month_df[month_df['Type'].isin(['Need', 'Want', 'Debt'])]['Amount'].sum()
                            bar_data = pd.DataFrame({"Cat": ["Income", "Expenses"], "Val": [inc, exp]})
                            fig_bar = px.bar(bar_data, x="Cat", y="Val", color="Cat", color_discrete_map={"Income": "green", "Expenses": "red"})
                            st.plotly_chart(fig_bar, use_container_width=True)
                        
                        with c2:
                            st.caption("Expense Breakdown")
                            exp_only = month_df[month_df['Type'] != 'Income']
                            if not exp_only.empty:
                                fig_pie = px.pie(exp_only, values='Amount', names='Category', hole=0.4)
                                st.plotly_chart(fig_pie, use_container_width=True)
                    else:
                        st.info(f"No transactions found for {selected_period}.")

        # ==========================
        # TAB 2: MANAGE
        # ==========================
        with tab2:
            st.header("📝 Transaction Manager")
            df_all = get_data(sheet, st.session_state['username'])
            
            if not df_all.empty:
                df_all = df_all.sort_values(by='Date', ascending=False)
                df_all['Delete_Label'] = (
                    "Row " + df_all['RowIndex'].astype(str) + " | " + 
                    df_all['Date'].dt.strftime('%Y-%m-%d') + " | $" + 
                    df_all['Amount'].astype(str) + " | " + 
                    df_all['Category']
                )
                
                to_del = st.selectbox("Select Transaction to Delete", df_all['Delete_Label'])
                if st.button("🗑️ Delete Selected", type="primary"):
                    row_idx = int(to_del.split(" | ")[0].replace("Row ", ""))
                    delete_transaction(sheet, row_idx)
                    st.success("Deleted!")
                    st.rerun()
                
                st.dataframe(df_all.drop(columns=['Delete_Label']), use_container_width=True)

if __name__ == '__main__':
    main()