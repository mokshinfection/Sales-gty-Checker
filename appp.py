import streamlit as st
import pandas as pd
import py7zr
import requests
import os
import io
from datetime import datetime
from dateutil.relativedelta import relativedelta

# --- CONFIGURATION ---
st.set_page_config(layout="wide", page_title="Sales Qty Checker")

GITHUB_7Z_URL = "https://github.com/mokshinfection/Sales-gty-Checker/raw/main/sales.7z"
EXTRACT_DIR = "data"
CSV_FILE_PATH = os.path.join(EXTRACT_DIR, "sales.csv") # Assuming the file inside is sales.csv

# --- DATA LOADING & PROCESSING ---
@st.cache_data
def download_and_extract_data():
    if not os.path.exists(EXTRACT_DIR):
        os.makedirs(EXTRACT_DIR)
    
    # Download 7z if it doesn't exist locally
    archive_path = os.path.join(EXTRACT_DIR, "sales.7z")
    if not os.path.exists(archive_path):
        st.info("Downloading data from GitHub... Please wait.")
        response = requests.get(GITHUB_7Z_URL)
        with open(archive_path, 'wb') as f:
            f.write(response.content)
            
    # Extract 7z
    if not os.path.exists(CSV_FILE_PATH):
        with py7zr.SevenZipFile(archive_path, mode='r') as z:
            z.extractall(path=EXTRACT_DIR)
            
    # Load into Pandas (Find the first CSV in the extracted folder)
    extracted_files = [f for f in os.listdir(EXTRACT_DIR) if f.endswith('.csv')]
    if not extracted_files:
        st.error("No CSV file found inside the .7z archive.")
        return pd.DataFrame()
        
    df = pd.read_csv(os.path.join(EXTRACT_DIR, extracted_files[0]))
    
    # Ensure Invoice Date is datetime
    df['Invoice Date'] = pd.to_datetime(df['Invoice Date'], errors='coerce')
    return df


# Initialize session state for the database
if 'master_df' not in st.session_state:
    st.session_state.master_df = download_and_extract_data()

# Initialize session state for the input grid
if 'input_grid' not in st.session_state:
    st.session_state.input_grid = pd.DataFrame(columns=["PartNumber", "Order Qty"], data=[["", 0] for _ in range(5)])

# --- HELPER FUNCTIONS ---
def color_trend(val):
    if pd.isna(val) or val == "":
        return ""
    try:
        val_float = float(val)
        if val_float < 0.7:
            return 'background-color: #ffcccc; color: black;' # Red / Downward
        elif 0.7 <= val_float <= 1.14:
            return 'background-color: #ffffcc; color: black;' # Yellow / Moderate
        elif val_float >= 1.15:
            return 'background-color: #ccffcc; color: black;' # Green / Upward
    except:
        return ""
    return ""

def clear_list():
    st.session_state.input_grid = pd.DataFrame(columns=["PartNumber", "Order Qty"], data=[["", 0] for _ in range(5)])

# --- UI LAYOUT ---
st.title("📦 Parts Order & Sales Analysis")

# 1. Sidebar - Data Upload & Filters
with st.sidebar:
    st.header("Upload New Data")
    uploaded_file = st.file_uploader("Upload CSV to append to database", type=['csv'])
    if uploaded_file:
        new_data = pd.read_csv(uploaded_file)
        new_data['Invoice Date'] = pd.to_datetime(new_data['Invoice Date'], errors='coerce')
        st.session_state.master_df = pd.concat([st.session_state.master_df, new_data], ignore_index=True)
        st.success("Data appended successfully!")
        
    st.header("Time Filter")
    filter_option = st.selectbox("Select Date Range", ["Last 3 Months", "Last 6 Months", "Last 12 Months", "Custom Range"])
    
    max_date = st.session_state.master_df['Invoice Date'].max()
    if pd.isna(max_date): max_date = datetime.today()
    
    start_date, end_date = None, max_date
    if filter_option == "Last 3 Months":
        start_date = max_date - relativedelta(months=3)
    elif filter_option == "Last 6 Months":
        start_date = max_date - relativedelta(months=6)
    elif filter_option == "Last 12 Months":
        start_date = max_date - relativedelta(months=12)
    else:
        start_date = st.date_input("Start Date", max_date - relativedelta(months=3))
        end_date = st.date_input("End Date", max_date)
        start_date = pd.to_datetime(start_date)
        end_date = pd.to_datetime(end_date)

# 2. Main Area - Interactive Excel Environment
st.subheader("1. Enter Part Numbers")
col1, col2 = st.columns([4, 1])

with col1:
    edited_df = st.data_editor(
        st.session_state.input_grid, 
        num_rows="dynamic",
        use_container_width=True,
        key="editor"
    )
with col2:
    st.button("Clear List", on_click=clear_list, use_container_width=True)

# 3. Processing and Output
if st.button("Analyze Parts", type="primary"):
    df = st.session_state.master_df
    
    # Filter valid inputs
    query_parts = edited_df[edited_df["PartNumber"].str.strip() != ""]
    
    if query_parts.empty:
        st.warning("Please enter at least one valid Part Number.")
    else:
        results = []
        # Areas of interest
        target_areas = ["Hoskote", "Nellore", "Neyveli", "Ramagundam", "Kotagudem"]
        
        # Calculate time cutoffs for trend
        trend_12m_start = max_date - relativedelta(months=12)
        trend_3m_start = max_date - relativedelta(months=3)
        
        # Filter DB based on user selected global date range
        mask_global = (df['Invoice Date'] >= start_date) & (df['Invoice Date'] <= end_date)
        df_filtered = df.loc[mask_global]

        for index, row in query_parts.iterrows():
            p_num = str(row['PartNumber']).strip()
            order_qty = row['Order Qty']
            
            # Extract Part Data
            part_data = df[df['PartNumber'] == p_num]
            part_data_filtered = df_filtered[df_filtered['PartNumber'] == p_num]
            
            if part_data.empty:
                results.append({"Part Number": p_num, "Description": "Not Found", "Order Qty": order_qty})
                continue
                
            # Static Details (take first instance)
            desc = part_data['Description'].iloc[0]
            prod_code = part_data['Product_Code'].iloc[0]
            unit_cost = part_data['Cost'].iloc[0]
            
            # Trend Calculation (Always uses last 12 and last 3 months from dataset's max date)
            qty_12m = part_data[(part_data['Invoice Date'] >= trend_12m_start) & (part_data['Invoice Date'] <= max_date)]['qty'].sum()
            qty_3m = part_data[(part_data['Invoice Date'] >= trend_3m_start) & (part_data['Invoice Date'] <= max_date)]['qty'].sum()
            
            trend = 0
            if qty_12m > 0:
                trend = round(qty_3m / qty_12m, 2)
            
            # Area Metrics calculation based on the globally filtered timeframe
            row_result = {
                "Part Number": p_num,
                "Description": desc,
                "Product Code": prod_code,
                "Order Qty": order_qty,
                "Unit Cost": unit_cost,
                "Trend": trend
            }
            
            total_sales_qty = part_data_filtered['qty'].sum()
            total_freq = part_data_filtered['InvoiceNumber'].nunique() # Unique invoices = frequency
            
            for area in target_areas:
                area_data = part_data_filtered[part_data_filtered['Area'] == area]
                row_result[f"{area} Qty"] = area_data['qty'].sum()
                row_result[f"{area} Freq"] = area_data['InvoiceNumber'].nunique()
                
            row_result["Total Sales Qty"] = total_sales_qty
            row_result["Total Freq"] = total_freq
            
            results.append(row_result)
            
        final_df = pd.DataFrame(results)
        
        st.subheader("2. Analysis Results")
        
        # Apply conditional formatting to the Trend column
        if "Trend" in final_df.columns:
            styled_df = final_df.style.applymap(color_trend, subset=['Trend'])
            st.dataframe(styled_df, use_container_width=True)
        else:
            st.dataframe(final_df, use_container_width=True)
