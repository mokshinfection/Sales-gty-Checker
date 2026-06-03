import streamlit as st
import pandas as pd
import sqlite3
import py7zr
import requests
import os
import glob # <-- ADD THIS IMPORT
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

# --- CONFIGURATION ---
DB_URL = "https://github.com/mokshinfection/Sales-gty-Checker/raw/main/sales.7z"
ARCHIVE_NAME = "sales.7z"
TABLE_NAME = "Combined_VSPC_Master"
TARGET_BRANCHES = ["Hoskote", "Nellore", "Neyveli", "Ramagundam", "Kotagudem"]

st.set_page_config(layout="wide", page_title="Inventory & Sales Tracker")

# --- DATA ACQUISITION & SETUP ---
@st.cache_resource
def setup_database():
    """Downloads the archive, extracts it, and dynamically finds the .db file."""
    # 1. Download if the archive doesn't exist
    if not os.path.exists(ARCHIVE_NAME):
        st.info("Downloading database from GitHub...")
        response = requests.get(DB_URL, stream=True)
        with open(ARCHIVE_NAME, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # 2. Extract the archive
        st.info("Extracting database...")
        with py7zr.SevenZipFile(ARCHIVE_NAME, mode='r') as z:
            z.extractall()
            
    # 3. DYNAMICALLY find the extracted .db file (even if it's in a subfolder)
    db_files = glob.glob("**/*.db", recursive=True)
    
    if db_files:
        print(f"Successfully found database: {db_files[0]}")
        return db_files[0] # Return the actual path to the extracted database
    else:
        st.error("CRITICAL: No .db file was found inside the extracted archive!")
        return "fallback.db"

db_path = setup_database()

def get_db_connection():
    return sqlite3.connect(db_path)

# ... (rest of your code below remains the same)
# --- DATA ACQUISITION & SETUP ---
@st.cache_resource
def setup_database():
    """Downloads the .7z file from GitHub, extracts it, and returns the DB path."""
    if not os.path.exists(DB_NAME):
        st.info("Downloading database from GitHub...")
        response = requests.get(DB_URL, stream=True)
        with open(ARCHIVE_NAME, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        st.info("Extracting database...")
        with py7zr.SevenZipFile(ARCHIVE_NAME, mode='r') as z:
            z.extractall()
    return DB_NAME

db_path = setup_database()

def get_db_connection():
    return sqlite3.connect(db_path)

# --- HELPER FUNCTIONS ---
def get_max_date(conn):
    """Gets the most recent Invoice Date from the DB to calculate trends against."""
    query = f"SELECT MAX(`Invoice Date`) FROM `{TABLE_NAME}`"
    max_date = pd.read_sql(query, conn).iloc[0, 0]
    # Fallback to today if DB is empty or date is unparseable
    if not max_date: return datetime.today()
    try:
        return pd.to_datetime(max_date)
    except:
        return datetime.today()

def calculate_trend_category(ratio):
    if pd.isna(ratio): return "No Data"
    if ratio < 0.7: return "Downward"
    elif ratio <= 1.14: return "Moderate"
    else: return "Upward"

def style_trend(val):
    """Applies CSS colors based on the Trend text."""
    if isinstance(val, str):
        if val == "Downward": return 'color: red; font-weight: bold'
        if val == "Moderate": return 'color: orange; font-weight: bold'
        if val == "Upward": return 'color: green; font-weight: bold'
    return ''

# --- UI: SIDEBAR & FILTERS ---
st.title("📦 Sales & Inventory Forecasting Dashboard")

with st.sidebar:
    st.header("Settings & Filters")
    
    # Date Filtering
    st.subheader("Analysis Date Range")
    date_option = st.radio("Select Range:", ["Last 3 Months", "Last 6 Months", "Last 12 Months", "Custom Range"])
    
    conn = get_db_connection()
    max_db_date = get_max_date(conn).date()
    
    if date_option == "Last 3 Months":
        start_date = max_db_date - relativedelta(months=3)
        end_date = max_db_date
    elif date_option == "Last 6 Months":
        start_date = max_db_date - relativedelta(months=6)
        end_date = max_db_date
    elif date_option == "Last 12 Months":
        start_date = max_db_date - relativedelta(months=12)
        end_date = max_db_date
    else:
        start_date = st.date_input("Start Date", max_db_date - relativedelta(months=1))
        end_date = st.date_input("End Date", max_db_date)

    # File Uploader to append Data
    st.markdown("---")
    st.subheader("Upload New Data")
    uploaded_file = st.file_uploader("Upload CSV/Excel to append to Database", type=["csv", "xlsx"])
    if uploaded_file is not None:
        if st.button("Process & Append Data"):
            try:
                new_data = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                new_data.to_sql(TABLE_NAME, conn, if_exists="append", index=False)
                st.success(f"Successfully appended {len(new_data)} rows!")
            except Exception as e:
                st.error(f"Error appending data: {e}")

# --- UI: EXCEL INPUT ENVIRONMENT ---
st.subheader("📥 Input Part Numbers & Quantities")

# Initialize Session State for the Data Editor to allow clearing
if "input_df" not in st.session_state:
    st.session_state.input_df = pd.DataFrame({"PartNumber": [""], "Order Qty": [0]})

col1, col2 = st.columns([4, 1])
with col1:
    # The editable grid
    edited_df = st.data_editor(st.session_state.input_df, num_rows="dynamic", use_container_width=True)
with col2:
    if st.button("Clear List", use_container_width=True):
        st.session_state.input_df = pd.DataFrame({"PartNumber": [""], "Order Qty": [0]})
        st.rerun()

# Filter out empty inputs
valid_inputs = edited_df[edited_df["PartNumber"].str.strip() != ""]

# --- DATA PROCESSING & AGGREGATION ---
if st.button("🚀 Analyze Parts", type="primary") and not valid_inputs.empty:
    st.markdown("---")
    st.subheader("📊 Results")
    
    part_numbers = valid_inputs["PartNumber"].tolist()
    parts_tuple = tuple(part_numbers) if len(part_numbers) > 1 else f"('{part_numbers[0]}')"
    
    # 1. Fetch Base Part Info (Description, Product Code, Latest Cost)
    # Assuming the most recent cost is desired, grouping by PartNumber
    base_query = f"""
        SELECT PartNumber, Description, `Product_Code`, AVG(Cost) as Unit_Cost
        FROM `{TABLE_NAME}`
        WHERE PartNumber IN {parts_tuple}
        GROUP BY PartNumber, Description, `Product_Code`
    """
    base_info = pd.read_sql(base_query, conn)
    
    # 2. Fetch Trend Data (Last 3M vs Last 12M based on max_db_date)
    date_3m_ago = max_db_date - relativedelta(months=3)
    date_12m_ago = max_db_date - relativedelta(months=12)
    
    trend_query = f"""
        SELECT 
            PartNumber,
            SUM(CASE WHEN `Invoice Date` >= '{date_3m_ago}' THEN qty ELSE 0 END) as Sales_3M,
            SUM(CASE WHEN `Invoice Date` >= '{date_12m_ago}' THEN qty ELSE 0 END) as Sales_12M
        FROM `{TABLE_NAME}`
        WHERE PartNumber IN {parts_tuple}
        GROUP BY PartNumber
    """
    trend_info = pd.read_sql(trend_query, conn)
    
    # Calculate Trend Ratio & Category
    trend_info["Sales_12M_Adj"] = trend_info["Sales_12M"].replace(0, 1) # Prevent Div by Zero
    trend_info["Trend_Ratio"] = trend_info["Sales_3M"] / (trend_info["Sales_12M_Adj"] / 4) # Annualized comparison
    trend_info["Trend"] = trend_info["Trend_Ratio"].apply(calculate_trend_category)
    
    # 3. Fetch Branch Data based on the selected Date Filter
    # NOTE: Assuming branch names are in the 'Name' or 'Area' column. Using 'Name' based on typical schema.
    branch_query = f"""
        SELECT 
            PartNumber,
            Name as Branch,
            SUM(qty) as Total_Sales_Qty,
            COUNT(`InvoiceNumber`) as Sales_Frequency
        FROM `{TABLE_NAME}`
        WHERE PartNumber IN {parts_tuple}
        AND `Invoice Date` BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY PartNumber, Name
    """
    branch_info = pd.read_sql(branch_query, conn)
    
    # --- MERGING ALL DATA ---
    results = pd.merge(valid_inputs, base_info, on="PartNumber", how="left")
    results = pd.merge(results, trend_info[["PartNumber", "Trend"]], on="PartNumber", how="left")
    
    # Pivot Branch Data to create columns for each location
    if not branch_info.empty:
        # Filter only for the target branches
        branch_filtered = branch_info[branch_info["Branch"].isin(TARGET_BRANCHES)]
        
        # Pivot Qty
        pivot_qty = branch_filtered.pivot(index="PartNumber", columns="Branch", values="Total_Sales_Qty").fillna(0)
        pivot_qty = pivot_qty.add_suffix(" Qty")
        
        # Pivot Freq
        pivot_freq = branch_filtered.pivot(index="PartNumber", columns="Branch", values="Sales_Frequency").fillna(0)
        pivot_freq = pivot_freq.add_suffix(" Freq")
        
        # Merge pivoted data
        results = pd.merge(results, pivot_qty, on="PartNumber", how="left").fillna(0)
        results = pd.merge(results, pivot_freq, on="PartNumber", how="left").fillna(0)
        
        # Calculate Grand Totals
        qty_cols = [c for c in results.columns if "Qty" in c and c != "Order Qty"]
        freq_cols = [c for c in results.columns if "Freq" in c]
        
        results["Total Branch Qty"] = results[qty_cols].sum(axis=1)
        results["Total Branch Freq"] = results[freq_cols].sum(axis=1)
        
    else:
        st.warning(f"No sales data found for the selected date range ({start_date} to {end_date}).")
    
    # Cleanup and rename for display
    results.rename(columns={"Unit_Cost": "Unit Cost", "Product_Code": "Product Code"}, inplace=True)
    
    # Render Output Table with Colored Trends
    st.dataframe(
        results.style.map(style_trend, subset=["Trend"]), 
        use_container_width=True,
        hide_index=True
    )
    
conn.close()
import pandas as pd
from datetime import datetime

def get_max_date(conn):
    query = f"SELECT MAX(`Invoice Date`) FROM `{TABLE_NAME}`"
    
    try:
        # This is where it's currently crashing
        max_date = pd.read_sql(query, conn).iloc[0, 0]
    except Exception as e:
        # This will print the exact reason to your Streamlit logs
        print(f"CRITICAL SQL ERROR: {e}")
        return datetime.today() # Fallback to prevent a full app crash

    if not pd.notna(max_date) or not max_date: 
        return datetime.today()
        
    try:
        return pd.to_datetime(max_date)
    except:
        return datetime.today()
