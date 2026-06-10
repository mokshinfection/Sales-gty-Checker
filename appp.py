import streamlit as st
import pandas as pd
import time
import io
import os
from datetime import datetime
from dateutil.relativedelta import relativedelta

# --- CONFIGURATION ---
st.set_page_config(layout="wide", page_title="Sales & Stock Qty Checker")

GITHUB_PARQUET_URL = "https://github.com/mokshinfection/Sales-gty-Checker/raw/main/sales.parquet"
LOCAL_STOCK_FILE = "stock.parquet"

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

# Initialize session states
if 'master_df' not in st.session_state:
    st.session_state.master_df = load_fast_data()

# --- AUTO-LOAD LOCAL STOCK PARQUET ---
if 'stock_df' not in st.session_state:
    if os.path.exists(LOCAL_STOCK_FILE):
        try:
            st.session_state.stock_df = pd.read_parquet(LOCAL_STOCK_FILE)
        except:
            st.session_state.stock_df = pd.DataFrame()
    else:
        st.session_state.stock_df = pd.DataFrame()

if 'input_grid' not in st.session_state:
    st.session_state.input_grid = pd.DataFrame(columns=["PartNumber", "Order Qty"], data=[["", 0] for _ in range(5)])
if 'editor_key' not in st.session_state:
    st.session_state.editor_key = 0

# --- HELPER FUNCTIONS ---
def clear_list():
    st.session_state.input_grid = pd.DataFrame(columns=["PartNumber", "Order Qty"], data=[["", 0] for _ in range(5)])
    st.session_state.editor_key += 1

def style_trend_text(val):
    val_str = str(val)
    if "Down" in val_str:
        return 'background-color: #ffcccc; color: black;'
    elif "Moderate" in val_str:
        return 'background-color: #ffffcc; color: black;'
    elif "Up" in val_str:
        return 'background-color: #ccffcc; color: black;'
    return ""

# --- UI LAYOUT ---
st.title("📦 Parts Order, Sales & Stock Analysis")

# 1. Sidebar - Data Upload & Filters
with st.sidebar:
    # --- ROBUST LATEST SALES DATE DISPLAY ---
    if not st.session_state.master_df.empty and 'Invoice Date' in st.session_state.master_df.columns:
        safe_sales_dates = pd.to_datetime(st.session_state.master_df['Invoice Date'], errors='coerce')
        latest_date = safe_sales_dates.max()
        if pd.notna(latest_date):
            st.success(f"📅 Latest Sales Data: **{latest_date.strftime('%B %Y')}**")
    
    st.header("1. Upload Sales Data")
    uploaded_file = st.file_uploader("Upload CSV/Excel to append to sales database", type=['csv', 'xlsx', 'xls'])
    if uploaded_file:
        try:
            if uploaded_file.name.endswith('.csv'):
                new_data = pd.read_csv(uploaded_file, dtype=str) 
            else:
                new_data = pd.read_excel(uploaded_file, dtype=str) 
                
            new_data.columns = new_data.columns.astype(str).str.strip().str.replace('"', '', regex=False)
            
            for variant in ['Invoice_Date', 'InvoiceDate', 'INVOICE DATE']:
                if variant in new_data.columns and 'Invoice Date' not in new_data.columns:
                    new_data.rename(columns={variant: 'Invoice Date'}, inplace=True)
                    
            if 'Invoice Date' in new_data.columns:
                new_data['Invoice Date'] = pd.to_datetime(new_data['Invoice Date'], errors='coerce')
                
            if 'qty' in new_data.columns:
                new_data['qty'] = pd.to_numeric(new_data['qty'], errors='coerce').fillna(0)
            if 'Cost' in new_data.columns:
                new_data['Cost'] = pd.to_numeric(new_data['Cost'], errors='coerce').fillna(0)
                
            st.session_state.master_df = pd.concat([st.session_state.master_df, new_data], ignore_index=True)
            st.success("New sales data appended successfully!")
        except Exception as e:
            st.error(f"Error loading sales file: {e}")
    
    st.markdown("---")
    
    st.header("2. Upload Stock Data")
    
    if not st.session_state.stock_df.empty:
        st.info("✅ A cached Stock file is currently loaded in the system.")
        
        # --- ROBUST LATEST STOCK DATE DISPLAY ---
        stock_date_cols = [c for c in st.session_state.stock_df.columns if 'date' in c.lower()]
        max_stock_date = pd.NaT
        for c in stock_date_cols:
            valid_rows = st.session_state.stock_df[c].dropna()
            if not valid_rows.empty:
                parsed_dates = pd.to_datetime(valid_rows, errors='coerce', dayfirst=True)
                col_max = parsed_dates.max()
                if pd.notna(col_max):
                    if pd.isna(max_stock_date) or col_max > max_stock_date:
                        max_stock_date = col_max
                        
        if pd.notna(max_stock_date):
            st.success(f"📦 Latest Stock Date: **{max_stock_date.strftime('%B %Y')}**")
        
    stock_file = st.file_uploader("Upload NEW Stock List to replace old one (CSV/Excel)", type=['csv', 'xlsx'])
    if stock_file:
        try:
            header_idx = 0
            
            # --- THE FIX: BULLETPROOF TEXT SCANNER FOR CSVs ---
            if stock_file.name.endswith('.csv'):
                stock_file.seek(0)
                # Read first 25 lines as plain text to avoid pandas Tokenizing crashing
                lines = stock_file.readlines()[:25]
                for idx, line in enumerate(lines):
                    try:
                        decoded_row = line.decode('utf-8', errors='ignore').lower()
                    except:
                        decoded_row = str(line).lower()
                        
                    if 'part no' in decoded_row or 'stock' in decoded_row or 'main dealer' in decoded_row:
                        header_idx = idx
                        break
                
                # Now that we know exactly where the header is, safely pass it to pandas
                stock_file.seek(0)
                stock_data = pd.read_csv(stock_file, header=header_idx, dtype=str)
                
            else:
                # Excel handles weird grid sizes fine natively
                preview_df = pd.read_excel(stock_file, header=None, nrows=25)
                for idx, row in preview_df.iterrows():
                    row_str = [str(x).strip().lower() for x in row.values]
                    if 'part no' in row_str or 'stock' in row_str or 'main dealer-1' in row_str or 'main dealer' in row_str:
                        header_idx = idx
                        break
                stock_file.seek(0)
                stock_data = pd.read_excel(stock_file, header=header_idx, dtype=str)
                
            stock_data = stock_data.astype(str)
            stock_data.columns = stock_data.columns.astype(str).str.strip().str.replace('"', '', regex=False).str.replace('\n', '', regex=False)
            
            stock_data.to_parquet(LOCAL_STOCK_FILE, index=False)
            st.session_state.stock_df = stock_data
            
            st.success("New stock list loaded and cached as Parquet!")
            st.rerun()
                
        except Exception as e:
            st.error(f"Error loading stock file: {e}")

    st.markdown("---")
            
    st.header("3. Time Filter (Sales)")
    filter_option = st.selectbox("Select Date Range", ["Last 3 Months", "Last 6 Months", "Last 12 Months", "Custom Range"])
    
    if not st.session_state.master_df.empty and 'Invoice Date' in st.session_state.master_df.columns:
        max_date = pd.to_datetime(st.session_state.master_df['Invoice Date'], errors='coerce').max()
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
    edited_df = st.data_editor(
        st.session_state.input_grid, 
        num_rows="dynamic",
        width="stretch", # <-- SWAPPED
        hide_index=True,
        key=f"editor_{st.session_state.editor_key}"
    )
with col2:
    st.button("Clear List", on_click=clear_list, width="stretch") # <-- SWAPPED

# 3. Processing and Output
if st.button("Analyze Parts", type="primary"):
    df = st.session_state.master_df.copy() 
    sdf = st.session_state.stock_df.copy()
    
    has_stock = not sdf.empty
    
    stock_part_col, stock_qty_col, stock_dealer_col = None, None, None
    if has_stock:
        stock_part_col = next((c for c in sdf.columns if c.strip().lower() in ['part no', 'codepart', 'partnumber']), None)
        if not stock_part_col:
            stock_part_col = next((c for c in sdf.columns if 'part' in c.lower()), None)
            
        stock_qty_col = next((c for c in sdf.columns if c.strip().lower() == 'stock'), None)
        if not stock_qty_col:
            stock_qty_col = next((c for c in sdf.columns if 'stock' in c.lower() or 'qty' in c.lower()), None)
            
        stock_dealer_col = next((c for c in sdf.columns if 'main dealer' in c.lower()), None)
        if not stock_dealer_col:
            stock_dealer_col = next((c for c in sdf.columns if ('dealer' in c.lower() and 'id' not in c.lower()) or 'location' in c.lower()), None)
        
        if not (stock_part_col and stock_qty_col and stock_dealer_col):
            st.warning("Stock File uploaded, but couldn't completely detect columns. Stock checks may be skipped.")
            has_stock = False
    
    if df.empty:
        st.error("The base sales database is currently empty. Please verify your source file.")
    else:
        with st.spinner("Optimizing and scanning database..."):
            df['SearchPart'] = df['PartNumber'].astype(str).str.strip().str.upper()
            
            dealer_col = next((c for c in df.columns if 'dealer' in c.lower()), None)
            if dealer_col and 'Area' in df.columns:
                target_dealers = ['693605', '693606', '693608']
                mask_dealers = df[dealer_col].astype(str).str.strip().str.replace('.0', '', regex=False).isin(target_dealers)
                df.loc[mask_dealers, 'Area'] = 'Neyveli'
            
            mask_global = (pd.to_datetime(df['Invoice Date'], errors='coerce') >= pd.to_datetime(start_date)) & \
                          (pd.to_datetime(df['Invoice Date'], errors='coerce') <= pd.to_datetime(end_date))
            df_filtered = df.loc[mask_global]

            if has_stock:
                sdf['SearchPart'] = sdf[stock_part_col].astype(str).str.strip().str.upper()
                sdf['SearchDealer'] = sdf[stock_dealer_col].astype(str).str.strip().str.lower()
                sdf['NumericQty'] = pd.to_numeric(sdf[stock_qty_col], errors='coerce').fillna(0)
            
            query_parts = edited_df[edited_df["PartNumber"].astype(str).str.strip() != ""]
            
            if query_parts.empty:
                st.warning("Please enter at least one valid Part Number.")
            else:
                results = []
                target_areas = ["Hoskote", "Nellore", "Neyveli", "Ramagundam", "Kothagudem"] 
                
                trend_12m_start = max_date - relativedelta(months=12)
                trend_3m_start = max_date - relativedelta(months=3)
                
                safe_base_dates = pd.to_datetime(df['Invoice Date'], errors='coerce')
                
                for index, row in query_parts.iterrows():
                    p_num = str(row['PartNumber']).strip()
                    p_num_clean = p_num.upper()
                    
                    try:
                        order_qty = int(float(row['Order Qty'])) if str(row['Order Qty']).strip() else 0
                    except:
                        order_qty = 0
                    
                    part_data = df[df['SearchPart'] == p_num_clean]
                    part_data_filtered = df_filtered[df_filtered['SearchPart'] == p_num_clean]
                    
                    if part_data.empty:
                        desc = "Not Found"
                        prod_code = "N/A"
                        unit_cost = 0
                        trend_display = "➖ No Data"
                        total_sales_qty = 0
                        total_freq = 0
                    else:
                        desc = part_data['Description'].iloc[0] if 'Description' in part_data.columns else "N/A"
                        prod_code = part_data['Product_Code'].iloc[0] if 'Product_Code' in part_data.columns else "N/A"
                        
                        total_part_cost = part_data['Cost'].sum() if 'Cost' in part_data.columns else 0
                        total_part_qty = part_data['qty'].sum() if 'qty' in part_data.columns else 0
                        unit_cost = int(total_part_cost / total_part_qty) if total_part_qty > 0 else 0
                        
                        part_dates = safe_base_dates[part_data.index]
                        mask_12m = (part_dates >= trend_12m_start) & (part_dates <= max_date)
                        mask_3m = (part_dates >= trend_3m_start) & (part_dates <= max_date)
                        
                        qty_12m = part_data.loc[mask_12m, 'qty'].sum() if 'qty' in part_data.columns else 0
                        qty_3m = part_data.loc[mask_3m, 'qty'].sum() if 'qty' in part_data.columns else 0
                        
                        avg_12m = qty_12m / 12
                        avg_3m = qty_3m / 3
                        trend_ratio = (avg_3m / avg_12m) if avg_12m > 0 else 0
                        
                        if avg_12m == 0:
                            trend_display = "➖ No Data"
                        elif trend_ratio < 0.7:
                            trend_display = "⬇️ Down"
                        elif trend_ratio <= 1.14:
                            trend_display = "➡️ Moderate"
                        else:
                            trend_display = "⬆️ Up"
                            
                        total_sales_qty = int(part_data_filtered['qty'].sum()) if 'qty' in part_data_filtered.columns else 0
                        total_freq = int(part_data_filtered['InvoiceNumber'].nunique()) if 'InvoiceNumber' in part_data_filtered.columns else 0

                    row_result = {
                        "Part Number": p_num,
                        "Description": desc,
                        "Product Code": prod_code,
                        "Order Qty": order_qty,
                        "Unit Cost": unit_cost,
                        "Trend": trend_display
                    }
                    
                    stock_matches = pd.DataFrame()
                    if has_stock:
                        stock_matches = sdf[sdf['SearchPart'].str.endswith(p_num_clean)]
                    
                    for area in target_areas:
                        if not part_data_filtered.empty and 'Area' in part_data_filtered.columns:
                            area_sales = part_data_filtered[part_data_filtered['Area'] == area]
                            row_result[f"{area} Sales Qty"] = int(area_sales['qty'].sum()) if 'qty' in area_sales.columns else 0
                            row_result[f"{area} Freq"] = int(area_sales['InvoiceNumber'].nunique()) if 'InvoiceNumber' in area_sales.columns else 0
                        else:
                            row_result[f"{area} Sales Qty"] = 0
                            row_result[f"{area} Freq"] = 0
                            
                        area_stock_val = 0
                        if has_stock and not stock_matches.empty:
                            if area.lower() == 'hoskote':
                                mask_stock_area = stock_matches['SearchDealer'].isin(['hoskote', 'bangalore'])
                            else:
                                mask_stock_area = stock_matches['SearchDealer'] == area.lower()
                                
                            area_stock_val = stock_matches.loc[mask_stock_area, 'NumericQty'].sum()
                            
                        row_result[f"{area} Stock"] = int(area_stock_val)
                    
                    row_result["Total Sales Qty"] = total_sales_qty
                    row_result["Total Freq"] = total_freq
                    
                    results.append(row_result)
                    
                final_df = pd.DataFrame(results)
                
                base_cols = ["Part Number", "Description", "Product Code", "Order Qty", "Unit Cost", "Trend", "Total Sales Qty", "Total Freq"]
                reordered_cols = base_cols.copy()
                for area in target_areas:
                    reordered_cols.extend([f"{area} Stock", f"{area} Sales Qty", f"{area} Freq"])
                    
                final_df = final_df[[c for c in reordered_cols if c in final_df.columns]]
                
                st.subheader("2. Analysis Results")
                
                styled_df = final_df.style.format(precision=0)
                
                if "Trend" in final_df.columns:
                    styled_df = styled_df.map(style_trend_text, subset=['Trend'])
                    
                if "Unit Cost" in final_df.columns:
                    styled_df = styled_df.map(lambda _: 'background-color: #ffcccc; color: black;', subset=['Unit Cost'])
                    
                total_cols = [c for c in final_df.columns if c in ["Total Sales Qty", "Total Freq"]]
                if total_cols:
                    styled_df = styled_df.map(lambda _: 'background-color: #ccffcc; color: black;', subset=total_cols)
                    
                sales_qty_cols = [c for c in final_df.columns if "Sales Qty" in c and c not in ["Total Sales Qty"]]
                if sales_qty_cols:
                    styled_df = styled_df.map(lambda _: 'background-color: #ffe6cc; color: black;', subset=sales_qty_cols)
                    
                stock_cols = [c for c in final_df.columns if "Stock" in c]
                if stock_cols:
                    styled_df = styled_df.map(lambda _: 'background-color: #e6ccff; color: black;', subset=stock_cols)
                    
                freq_cols = [c for c in final_df.columns if "Freq" in c and c not in ["Total Freq"]]
                if freq_cols:
                    styled_df = styled_df.map(lambda _: 'background-color: #cce5ff; color: black;', subset=freq_cols)
                    
                st.dataframe(styled_df, width="stretch", hide_index=True) # <-- SWAPPED
                
                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    styled_df.to_excel(writer, index=False, sheet_name='Sales & Stock Analysis')
                
                download_data = buffer.getvalue()
                
                st.download_button(
                    label="📥 Download Results as Excel",
                    data=download_data,
                    file_name=f"Sales_Stock_Analysis_{datetime.now().strftime('%Y-%m-%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary"
                )
