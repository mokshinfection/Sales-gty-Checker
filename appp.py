import streamlit as st
import pandas as pd
import time
import io
from datetime import datetime
from dateutil.relativedelta import relativedelta

# --- CONFIGURATION ---
st.set_page_config(layout="wide", page_title="Sales Qty Checker")

GITHUB_PARQUET_URL = "https://github.com/mokshinfection/Sales-gty-Checker/raw/main/sales.parquet"

# --- BULLETPROOF DATA LOADING ---
@st.cache_data(ttl=3600)
def load_fast_data():
    try:
        bust_url = f"{GITHUB_PARQUET_URL}?v={int(time.time())}"
        df = pd.read_parquet(bust_url)
        
        df.columns = df.columns.astype(str).str.strip().str.replace('"', '', regex=False).str.replace('\n', '', regex=False)
        
        if 'Invoice Date' not in df.columns:
            possible_cols = [col for col in df.columns if 'date' in col.lower()]
            if possible_cols:
                actual_date_col = possible_cols[0]
                df.rename(columns={actual_date_col: 'Invoice Date'}, inplace=True)
            else:
                st.error(f"CRITICAL ERROR: No date column found! Columns: {df.columns.tolist()}")
                
        if 'Invoice Date' in df.columns:
            df['Invoice Date'] = pd.to_datetime(df['Invoice Date'], errors='coerce')
            
        return df
    except Exception as e:
        st.error(f"Error loading hosted data: {e}")
        return pd.DataFrame()

# Initialize session state for the database
if 'master_df' not in st.session_state:
    st.session_state.master_df = load_fast_data()

# Initialize session state for the input grid and dynamic key
if 'input_grid' not in st.session_state:
    st.session_state.input_grid = pd.DataFrame(columns=["PartNumber", "Order Qty"], data=[["", 0] for _ in range(5)])
if 'editor_key' not in st.session_state:
    st.session_state.editor_key = 0

# --- HELPER FUNCTIONS ---
def clear_list():
    # 1. Clear the underlying dataframe
    st.session_state.input_grid = pd.DataFrame(columns=["PartNumber", "Order Qty"], data=[["", 0] for _ in range(5)])
    # 2. Increment the key to force Streamlit to completely forget the old widget's edits
    st.session_state.editor_key += 1

# --- UI LAYOUT ---
st.title("📦 Parts Order & Sales Analysis")

# 1. Sidebar - Data Upload & Filters
with st.sidebar:
    st.header("Upload New Data")
    uploaded_file = st.file_uploader("Upload CSV to append to database", type=['csv'])
    if uploaded_file:
        new_data = pd.read_csv(uploaded_file)
        new_data.columns = new_data.columns.astype(str).str.strip().str.replace('"', '', regex=False)
        
        for variant in ['Invoice_Date', 'InvoiceDate', 'INVOICE DATE']:
            if variant in new_data.columns and 'Invoice Date' not in new_data.columns:
                new_data.rename(columns={variant: 'Invoice Date'}, inplace=True)
                
        if 'Invoice Date' in new_data.columns:
            new_data['Invoice Date'] = pd.to_datetime(new_data['Invoice Date'], errors='coerce')
            
        st.session_state.master_df = pd.concat([st.session_state.master_df, new_data], ignore_index=True)
        st.success("New data appended successfully!")
        
    st.header("Time Filter")
    filter_option = st.selectbox("Select Date Range", ["Last 3 Months", "Last 6 Months", "Last 12 Months", "Custom Range"])
    
    if not st.session_state.master_df.empty and 'Invoice Date' in st.session_state.master_df.columns:
        max_date = st.session_state.master_df['Invoice Date'].max()
        if pd.isna(max_date): 
            max_date = datetime.today()
    else:
        max_date = datetime.today()
    
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
    # Notice the key uses the dynamic counter now
    edited_df = st.data_editor(
        st.session_state.input_grid, 
        num_rows="dynamic",
        use_container_width=True,
        key=f"editor_{st.session_state.editor_key}"
    )
with col2:
    st.button("Clear List", on_click=clear_list, use_container_width=True)

# 3. Processing and Output
if st.button("Analyze Parts", type="primary"):
    df = st.session_state.master_df
    
    if df.empty:
        st.error("The base database is currently empty. Please verify your source file.")
    else:
        query_parts = edited_df[edited_df["PartNumber"].astype(str).str.strip() != ""]
        
        if query_parts.empty:
            st.warning("Please enter at least one valid Part Number.")
        else:
            results = []
            target_areas = ["Hoskote", "Nellore", "Neyveli", "Ramagundam", "Kotagudem"]
            
            trend_12m_start = max_date - relativedelta(months=12)
            trend_3m_start = max_date - relativedelta(months=3)
            
            mask_global = (df['Invoice Date'] >= start_date) & (df['Invoice Date'] <= end_date)
            df_filtered = df.loc[mask_global]

            for index, row in query_parts.iterrows():
                p_num = str(row['PartNumber']).strip()
                order_qty = row['Order Qty']
                
                part_data = df[df['PartNumber'].astype(str) == p_num]
                part_data_filtered = df_filtered[df_filtered['PartNumber'].astype(str) == p_num]
                
                if part_data.empty:
                    results.append({"Part Number": p_num, "Description": "Not Found", "Order Qty": order_qty})
                    continue
                    
                desc = part_data['Description'].iloc[0] if 'Description' in part_data.columns else "N/A"
                prod_code = part_data['Product_Code'].iloc[0] if 'Product_Code' in part_data.columns else "N/A"
                
                # Unit Cost Logic
                total_part_cost = part_data['Cost'].sum() if 'Cost' in part_data.columns else 0
                total_part_qty = part_data['qty'].sum() if 'qty' in part_data.columns else 0
                unit_cost = int(total_part_cost / total_part_qty) if total_part_qty > 0 else 0
                
                qty_12m = part_data[(part_data['Invoice Date'] >= trend_12m_start) & (part_data['Invoice Date'] <= max_date)]['qty'].sum() if 'qty' in part_data.columns else 0
                qty_3m = part_data[(part_data['Invoice Date'] >= trend_3m_start) & (part_data['Invoice Date'] <= max_date)]['qty'].sum() if 'qty' in part_data.columns else 0
                
                # Trend Arrow Logic
                trend_ratio = (qty_3m / qty_12m) if qty_12m > 0 else 0
                if qty_12m == 0:
                    trend_display = "➖ No Data"
                elif trend_ratio < 0.7:
                    trend_display = "⬇️ Down"
                elif trend_ratio <= 1.14:
                    trend_display = "➡️ Moderate"
                else:
                    trend_display = "⬆️ Up"
                
                row_result = {
                    "Part Number": p_num,
                    "Description": desc,
                    "Product Code": prod_code,
                    "Order Qty": order_qty,
                    "Unit Cost": unit_cost,
                    "Trend": trend_display
                }
                
                total_sales_qty = part_data_filtered['qty'].sum() if 'qty' in part_data_filtered.columns else 0
                total_freq = part_data_filtered['InvoiceNumber'].nunique() if 'InvoiceNumber' in part_data_filtered.columns else 0
                
                for area in target_areas:
                    if 'Area' in part_data_filtered.columns:
                        area_data = part_data_filtered[part_data_filtered['Area'] == area]
                        row_result[f"{area} Qty"] = area_data['qty'].sum() if 'qty' in area_data.columns else 0
                        row_result[f"{area} Freq"] = area_data['InvoiceNumber'].nunique() if 'InvoiceNumber' in area_data.columns else 0
                    else:
                        row_result[f"{area} Qty"] = 0
                        row_result[f"{area} Freq"] = 0
                    
                row_result["Total Sales Qty"] = total_sales_qty
                row_result["Total Freq"] = total_freq
                
                results.append(row_result)
                
            final_df = pd.DataFrame(results)
            st.subheader("2. Analysis Results")
            st.dataframe(final_df, use_container_width=True)
            
            # --- DOWNLOAD AS EXCEL BUTTON ---
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                final_df.to_excel(writer, index=False, sheet_name='Sales Analysis')
            
            download_data = buffer.getvalue()
            
            st.download_button(
                label="📥 Download Results as Excel",
                data=download_data,
                file_name=f"Sales_Analysis_Export_{datetime.now().strftime('%Y-%m-%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )
