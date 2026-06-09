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
    edited_df = st.data_editor(
        st.session_state.input_grid, 
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"editor_{st.session_state.editor_key}"
    )
with col2:
    st.button("Clear List", on_click=clear_list, use_container_width=True)

# 3. Processing and Output
if st.button("Analyze Parts", type="primary"):
    # Create a copy so we don't permanently modify the master session state
    df = st.session_state.master_df.copy() 
    
    if df.empty:
        st.error("The base database is currently empty. Please verify your source file.")
    else:
        # =====================================================================
        # NEW LOGIC: Override Area to Neyveli for specific Dealer IDs
        # Automatically detect the Dealer column (e.g., 'Dealer ID', 'DealerCode')
        dealer_col = next((c for c in df.columns if 'dealer' in c.lower()), None)
        if dealer_col and 'Area' in df.columns:
            target_dealers = ['693605', '693606', '693608']
            # Safe matching: convert to string, strip spaces, remove ".0" if interpreted as float
            mask_dealers = df[dealer_col].astype(str).str.strip().str.replace('.0', '', regex=False).isin(target_dealers)
            df.loc[mask_dealers, 'Area'] = 'Neyveli'
        # =====================================================================

        query_parts = edited_df[edited_df["PartNumber"].astype(str).str.strip() != ""]
        
        if query_parts.empty:
            st.warning("Please enter at least one valid Part Number.")
        else:
            results = []
            # =====================================================================
            # UPDATED: Changed 'Kotagudem' to 'Kothagudem'
            target_areas = ["Hoskote", "Nellore", "Neyveli", "Ramagundam", "Kothagudem"] 
            # =====================================================================
            
            trend_12m_start = max_date - relativedelta(months=12)
            trend_3m_start = max_date - relativedelta(months=3)
            
            mask_global = (df['Invoice Date'] >= start_date) & (df['Invoice Date'] <= end_date)
            df_filtered = df.loc[mask_global]

            for index, row in query_parts.iterrows():
                p_num = str(row['PartNumber']).strip()
                
                # Safely convert user input Order Qty to an integer
                try:
                    order_qty = int(float(row['Order Qty'])) if str(row['Order Qty']).strip() else 0
                except:
                    order_qty = 0
                
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
                
                # --- UPDATED TREND ARROW LOGIC (AVERAGES) ---
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
                
                row_result = {
                    "Part Number": p_num,
                    "Description": desc,
                    "Product Code": prod_code,
                    "Order Qty": order_qty,
                    "Unit Cost": unit_cost,
                    "Trend": trend_display
                }
                
                # Force calculations to integers
                total_sales_qty = int(part_data_filtered['qty'].sum()) if 'qty' in part_data_filtered.columns else 0
                total_freq = int(part_data_filtered['InvoiceNumber'].nunique()) if 'InvoiceNumber' in part_data_filtered.columns else 0
                
                for area in target_areas:
                    if 'Area' in part_data_filtered.columns:
                        area_data = part_data_filtered[part_data_filtered['Area'] == area]
                        row_result[f"{area} Qty"] = int(area_data['qty'].sum()) if 'qty' in area_data.columns else 0
                        row_result[f"{area} Freq"] = int(area_data['InvoiceNumber'].nunique()) if 'InvoiceNumber' in area_data.columns else 0
                    else:
                        row_result[f"{area} Qty"] = 0
                        row_result[f"{area} Freq"] = 0
                
                row_result["Total Sales Qty"] = total_sales_qty
                row_result["Total Freq"] = total_freq
                
                results.append(row_result)
                
            final_df = pd.DataFrame(results)
            st.subheader("2. Analysis Results")
            
            # --- APPLY EXACT BACKGROUND COLORS & REMOVE DECIMALS ---
            styled_df = final_df.style.format(precision=0)
            
            # 1. Trend
            if "Trend" in final_df.columns:
                styled_df = styled_df.map(style_trend_text, subset=['Trend'])
                
            # 2. Unit Cost (Light Red)
            if "Unit Cost" in final_df.columns:
                styled_df = styled_df.map(lambda _: 'background-color: #ffcccc; color: black;', subset=['Unit Cost'])
                
            # 3. Totals (Light Green)
            total_cols = [c for c in final_df.columns if c in ["Total Sales Qty", "Total Freq"]]
            if total_cols:
                styled_df = styled_df.map(lambda _: 'background-color: #ccffcc; color: black;', subset=total_cols)
                
            # 4. Area Qty (Light Orange)
            qty_cols = [c for c in final_df.columns if "Qty" in c and c not in ["Order Qty", "Total Sales Qty"]]
            if qty_cols:
                styled_df = styled_df.map(lambda _: 'background-color: #ffe6cc; color: black;', subset=qty_cols)
                
            # 5. Area Freq (Light Blue)
            freq_cols = [c for c in final_df.columns if "Freq" in c and c not in ["Total Freq"]]
            if freq_cols:
                styled_df = styled_df.map(lambda _: 'background-color: #cce5ff; color: black;', subset=freq_cols)
                
            # Show styled dataframe in Streamlit (with hidden row numbers)
            st.dataframe(styled_df, use_container_width=True, hide_index=True)
            
            # --- DOWNLOAD AS EXCEL BUTTON ---
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                styled_df.to_excel(writer, index=False, sheet_name='Sales Analysis')
            
            download_data = buffer.getvalue()
            
            st.download_button(
                label="📥 Download Results as Excel",
                data=download_data,
                file_name=f"Sales_Analysis_Export_{datetime.now().strftime('%Y-%m-%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )
