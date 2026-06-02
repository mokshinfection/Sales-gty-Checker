import streamlit as st
import pandas as pd
from datetime import datetime
import io
import sqlite3
import os
import urllib.request
import py7zr

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Sales Quantity Checker", layout="wide")
st.title("Sales Quantity Checker")

# 🔴 LOCKED ABSOLUTE MASTER DATABASE URL 🔴
GITHUB_7Z_URL = "https://raw.githubusercontent.com/mokshinfection/Sales-gty-Checker/main/sales.7z"
DB_FILE_PATH = "Sales.db"

def extract_master_db():
    """Downloads sales.7z and extracts the internal .db file directly into the workspace."""
    try:
        with urllib.request.urlopen(GITHUB_7Z_URL) as response:
            archive_bytes = response.read()
            
        with py7zr.SevenZipFile(io.BytesIO(archive_bytes), mode='r') as archive:
            extracted_files = archive.getnames()
            db_filename = next((name for name in extracted_files if name.endswith('.db')), None)
            if not db_filename:
                raise FileNotFoundError("Could not locate a valid .db file inside the downloaded sales.7z archive.")
            
            archive.extractall(path=".")
            
            if db_filename != DB_FILE_PATH and os.path.exists(db_filename):
                if os.path.exists(DB_FILE_PATH):
                    os.remove(DB_FILE_PATH)
                os.rename(db_filename, DB_FILE_PATH)
        
        # ⚡ SPEED BOOST: Create indexes on the database to make lookups blindingly fast
        conn = sqlite3.connect(DB_FILE_PATH)
        cursor = conn.cursor()
        
        # Auto-detect table name
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        table_name = tables[0][0] if tables else "sales_records"
        
        cursor.execute(f"PRAGMA table_info([{table_name}])")
        columns = [col[1] for col in cursor.fetchall()]
        
        # Dynamic search for Part column variations
        part_col = 'PartNumber' if 'PartNumber' in columns else ('Part Number' if 'Part Number' in columns else columns[0])
        
        # Dynamic search for Date column variations
        date_col = 'Invoice Date' if 'Invoice Date' in columns else ('Date' if 'Date' in columns else None)
        if not date_col:
            date_col = next((col for col in columns if 'date' in col.lower()), columns[0])
        
        # Apply Indexes
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_part ON [{table_name}] ([{part_col}]);")
        cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_date ON [{table_name}] ([{date_col}]);")
        conn.commit()
        conn.close()
                
    except Exception as e:
        st.error(f"Failed to extract master database architecture from GitHub.\n\nError: {e}")
        st.stop()

# --- INITIALIZE DATABASE ONCE ---
if not os.path.exists(DB_FILE_PATH):
    with st.spinner("Downloading and indexing master database (Done only once on startup)..."):
        extract_master_db()

# --- ⚡ INSTANT METADATA FETCH (NO HEAVY LOADING) ---
def get_db_metadata():
    """Fetches min/max dates and table name safely without loading data into memory."""
    conn = sqlite3.connect(DB_FILE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    table_name = tables[0][0] if tables else "sales_records"
    
    cursor.execute(f"PRAGMA table_info([{table_name}])")
    columns = [col[1] for col in cursor.fetchall()]
    
    # 💡 FIXED: Flexible date column detection strategy to prevent "no such column" error
    date_col = 'Invoice Date' if 'Invoice Date' in columns else ('Date' if 'Date' in columns else None)
    if not date_col:
        date_col = next((col for col in columns if 'date' in col.lower()), None)
    
    # Absolute fallbacks if no date column can be matched or resolved
    parsed_min = pd.Timestamp("2025-05-02")
    parsed_max = pd.Timestamp("2026-04-30")
    
    if date_col:
        try:
            query = f"""
                SELECT MIN([{date_col}]), MAX([{date_col}]) 
                FROM [{table_name}] 
                WHERE [{date_col}] IS NOT NULL 
                  AND [{date_col}] != '' 
                  AND TRIM([{date_col}]) != ''
            """
            cursor.execute(query)
            min_d, max_d = cursor.fetchone()
            
            if min_d: 
                t_min = pd.to_datetime(min_d, dayfirst=True, errors='coerce')
                if not pd.isnull(t_min): parsed_min = t_min
            if max_d: 
                t_max = pd.to_datetime(max_d, dayfirst=True, errors='coerce')
                if not pd.isnull(t_max): parsed_max = t_max
        except Exception:
            pass # Use hardcoded fallback bounds if calculation encounters issues
            
    conn.close()
    return table_name, (date_col if date_col else "Invoice Date"), parsed_min, parsed_max

table_name, date_col_name, db_min_date, db_max_date = get_db_metadata()


# --- SIDEBAR: SYSTEM STATUS ---
with st.sidebar:
    st.header("System Status")
    st.success("Master SQL Database Active (Indexed)")
    st.info(f"**Total History Available:**\n\n{db_min_date.strftime('%d %b %Y')} to {db_max_date.strftime('%d %b %Y')}")
    
    if st.button("Force Synchronize with GitHub"):
        st.cache_data.clear()
        if os.path.exists(DB_FILE_PATH):
            os.remove(DB_FILE_PATH)
        st.rerun()


# --- DATE FILTERING UI ---
st.write("### Set Timeframe")
time_preset = st.radio("Quick Filters:", ["Last 3 Months", "Last 6 Months", "Last 12 Months", "Custom Range"], horizontal=True)

if time_preset == "Last 3 Months":
    start_date = (db_max_date - pd.DateOffset(months=3)).date()
    end_date = db_max_date.date()
elif time_preset == "Last 6 Months":
    start_date = (db_max_date - pd.DateOffset(months=6)).date()
    end_date = db_max_date.date()
elif time_preset == "Last 12 Months":
    start_date = (db_max_date - pd.DateOffset(months=12)).date()
    end_date = db_max_date.date()
else:
    date_range = st.slider("Select Custom Date Range", min_value=db_min_date.date(), max_value=db_max_date.date(), value=(db_min_date.date(), db_max_date.date()), format="DD/MM/YY")
    start_date, end_date = date_range[0], date_range[1]


# --- ⚡ TARGETED QUERY ENGINE ---
def query_targeted_data(part_numbers):
    """Queries ONLY the input part numbers from the database instead of loading everything."""
    if not part_numbers:
        return pd.DataFrame()
        
    conn = sqlite3.connect(DB_FILE_PATH)
    
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info([{table_name}])")
    columns = [col[1] for col in cursor.fetchall()]
    
    part_col = 'PartNumber' if 'PartNumber' in columns else ('Part Number' if 'Part Number' in columns else columns[0])
    
    placeholders = ', '.join(['?'] * len(part_numbers))
    query = f"SELECT * FROM [{table_name}] WHERE [{part_col}] IN ({placeholders})"
    
    df = pd.read_sql_query(query, conn, params=part_numbers)
    conn.close()
    
    if not df.empty and date_col_name in df.columns:
        df[date_col_name] = pd.to_datetime(df[date_col_name], dayfirst=True, errors='coerce')
    return df


def generate_filtered_database(df, start_date, end_date):
    """Processes trends and layouts ONLY for the targeted matches."""
    if df.empty:
        return pd.DataFrame(), ["Hoskote", "Kothagudem", "Ramagundam", "Neyveli", "Nellore"]

    part_col = 'PartNumber' if 'PartNumber' in df.columns else ('Part Number' if 'Part Number' in df.columns else 'PartNumber')
    qty_col = 'qty' if 'qty' in df.columns else ('Quantity' if 'Quantity' in df.columns else 'qty')
    code_col = 'Product Code' if 'Product Code' in df.columns else ('Part Code' if 'Part Code' in df.columns else 'Product Code')
    desc_col = 'Description'

    # Verify key structural items are assigned names
    if part_col not in df.columns: df.rename(columns={df.columns[0]: part_col}, inplace=True)

    max_db_date = df[date_col_name].max() if date_col_name in df.columns else pd.Timestamp(end_date)
    if pd.isnull(max_db_date): max_db_date = pd.Timestamp(end_date)
        
    three_months_ago = (max_db_date - pd.DateOffset(months=3)).date()
    twelve_months_ago = (max_db_date - pd.DateOffset(months=12)).date()
    max_date_conv = max_db_date.date()

    if date_col_name in df.columns:
        mask_3m = (df[date_col_name].dt.date >= three_months_ago) & (df[date_col_name].dt.date <= max_date_conv)
        mask_12m = (df[date_col_name].dt.date >= twelve_months_ago) & (df[date_col_name].dt.date <= max_date_conv)
        qty_3m = df[mask_3m].groupby(part_col)[qty_col].sum().reset_index(name='qty_3m')
        qty_12m = df[mask_12m].groupby(part_col)[qty_col].sum().reset_index(name='qty_12m')
    else:
        qty_3m = pd.DataFrame({part_col: df[part_col].unique(), 'qty_3m': 0})
        qty_12m = pd.DataFrame({part_col: df[part_col].unique(), 'qty_12m': 0})
    
    rate_col = 'Rate' if 'Rate' in df.columns else ('Unit Cost' if 'Unit Cost' in df.columns else None)
    unit_costs = df.groupby(part_col)[rate_col].mean().reset_index(name='Unit Cost') if rate_col else pd.DataFrame(columns=[part_col, 'Unit Cost'])

    if date_col_name in df.columns:
        mask = (df[date_col_name].dt.date >= start_date) & (df[date_col_name].dt.date <= end_date)
        filtered_df = df[mask].copy()
    else:
        filtered_df = df.copy()
    
    target_areas = ["Hoskote", "Kothagudem", "Ramagundam", "Neyveli", "Nellore"]
    
    for col in [part_col, code_col, desc_col]:
        if col not in filtered_df.columns: filtered_df[col] = "N/A"
    if 'Area' not in filtered_df.columns: filtered_df['Area'] = "Unknown"
    if qty_col not in filtered_df.columns: filtered_df[qty_col] = 0

    pivot_qty = filtered_df.pivot_table(index=[part_col, code_col, desc_col], columns='Area', values=qty_col, aggfunc='sum', fill_value=0).reset_index()
    pivot_freq = filtered_df.pivot_table(index=[part_col, code_col, desc_col], columns='Area', values=qty_col, aggfunc='count', fill_value=0).reset_index()
    
    pivot_qty.rename(columns={part_col: 'PartNumber', code_col: 'Product Code'}, inplace=True)
    pivot_freq.rename(columns={part_col: 'PartNumber', code_col: 'Product Code'}, inplace=True)
    
    for area in target_areas:
        if area not in pivot_qty.columns: pivot_qty[area] = 0
        if area not in pivot_freq.columns: pivot_freq[area] = 0
            
    pivot_qty['Total Qty'] = pivot_qty[target_areas].sum(axis=1)
    pivot_freq['Total Freq'] = pivot_freq[target_areas].sum(axis=1)
    
    freq_rename_map = {area: f"{area} Freq" for area in target_areas}
    pivot_freq.rename(columns=freq_rename_map, inplace=True)
    
    merge_cols = ['PartNumber', 'Product Code', 'Description', 'Total Freq'] + list(freq_rename_map.values())
    final_db = pd.merge(pivot_qty, pivot_freq[merge_cols], on=['PartNumber', 'Product Code', 'Description'], how='left')
    
    qty_3m.rename(columns={part_col: 'PartNumber'}, inplace=True)
    qty_12m.rename(columns={part_col: 'PartNumber'}, inplace=True)
    unit_costs.rename(columns={part_col: 'PartNumber'}, inplace=True)
    
    final_db = pd.merge(final_db, qty_3m, on='PartNumber', how='left').fillna({'qty_3m': 0})
    final_db = pd.merge(final_db, qty_12m, on='PartNumber', how='left').fillna({'qty_12m': 0})
    final_db = pd.merge(final_db, unit_costs, on='PartNumber', how='left').fillna({'Unit Cost': 0.0})
    
    def calculate_trend_row(row):
        q3, q12 = row['qty_3m'], row['qty_12m']
        if q12 <= 0: return "🟡 Moderate Trend" if q3 == 0 else "🟢 Upward Trend"
        ratio = q3 / q12
        if ratio < 0.70: return "🔴 Downward Trend"
        elif 0.70 <= ratio <= 1.14: return "🟡 Moderate Trend"
        else: return "🟢 Upward Trend"

    final_db['Trend'] = final_db.apply(calculate_trend_row, axis=1)
    return final_db, target_areas

def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sales Report')
    return output.getvalue()


# --- MAIN INTERFACE: THE CHECKER ---
st.write("### Enter Part Numbers")

if 'editor_key' not in st.session_state: st.session_state['editor_key'] = 0
if 'input_df' not in st.session_state: 
    st.session_state['input_df'] = pd.DataFrame({"PartNumber": ["", "", "", "", ""], "Order Qty": [0, 0, 0, 0, 0]})

if st.button("Clear List", key="clear_list_btn"):
    st.session_state['input_df'] = pd.DataFrame({"PartNumber": ["", "", "", "", ""], "Order Qty": [0, 0, 0, 0, 0]})
    st.session_state['editor_key'] += 1
    st.rerun()

edited_input = st.data_editor(
    st.session_state['input_df'],
    num_rows="dynamic",
    column_config={
        "PartNumber": st.column_config.TextColumn("Part Number (Editable)", required=True),
        "Order Qty": st.column_config.NumberColumn("Order Qty", min_value=0, default=0, step=1)
    },
    key=f"data_editor_{st.session_state['editor_key']}" 
)

if not edited_input.empty:
    valid_inputs = edited_input[edited_input["PartNumber"].astype(str).str.strip() != ""].copy()
    if not valid_inputs.empty:
        valid_inputs['PartNumber'] = valid_inputs['PartNumber'].astype(str).str.strip()
        
        unique_parts = valid_inputs['PartNumber'].unique().tolist()
        raw_targeted_df = query_targeted_data(unique_parts)
        
        database, areas = generate_filtered_database(raw_targeted_df, start_date, end_date)
        
        if not database.empty:
            result_df = pd.merge(valid_inputs, database, on="PartNumber", how="left")
        else:
            result_df = valid_inputs.copy()
            for col in ['Product Code', 'Description', 'Total Qty', 'Total Freq', 'Trend']:
                result_df[col] = "Not Found" if col in ['Description', 'Trend'] else 0
            result_df['Unit Cost'] = 0.0

        result_df['Description'] = result_df['Description'].fillna("Not Found")
        result_df['Product Code'] = result_df['Product Code'].fillna("N/A")
        result_df['Unit Cost'] = result_df['Unit Cost'].fillna(0.0)
        result_df['Trend'] = result_df['Trend'].fillna("🟡 Moderate Trend")
        result_df['Order Qty'] = result_df['Order Qty'].fillna(0).astype(int)
        result_df['Total Cost'] = result_df['Order Qty'] * result_df['Unit Cost']
        
        all_numeric_cols = areas + [f"{a} Freq" for a in areas] + ['Total Qty', 'Total Freq']
        for col in all_numeric_cols:
            if col in result_df.columns:
                result_df[col] = result_df[col].fillna(0).astype(int)
        
        st.write("### Final Sales Report")
        st.info(f"**Data Range Selected:** Quantities and Frequencies below represent sales from **{start_date.strftime('%d %b %Y')}** to **{end_date.strftime('%d %B %Y')}**")
        
        view_mode = st.radio("Select Display Format:", ["Color-Coded Detailed View", "Compact View (Text Combined)"], horizontal=True)
        leading_cols = ['PartNumber', 'Product Code', 'Description', 'Order Qty', 'Unit Cost', 'Total Cost', 'Trend']
        
        if view_mode == "Compact View (Text Combined)":
            display_df = result_df[[c for c in leading_cols if c in result_df.columns]].copy()
            for area in areas:
                if area in result_df.columns:
                    display_df[area] = "Qty: " + result_df[area].astype(str) + " | Freq: " + result_df[f"{area} Freq"].astype(str)
            if 'Total Qty' in result_df.columns:
                display_df['Total'] = "Qty: " + result_df['Total Qty'].astype(str) + " | Freq: " + result_df['Total Freq'].astype(str)
            st.dataframe(display_df, width="stretch")
            
        else:
            display_cols = list(leading_cols)
            for area in areas:
                display_cols.extend([area, f"{area} Freq"])
            display_cols.extend(['Total Qty', 'Total Freq'])
            
            detailed_df = result_df[[c for c in display_cols if c in result_df.columns]]
            
            def color_columns(col):
                if col.name == "Trend":
                    return [
                        'background-color: rgba(231, 76, 60, 0.15); color: #C0392B; font-weight: bold' if "🔴" in str(v)
                        else 'background-color: rgba(46, 204, 113, 0.15); color: #27AE60; font-weight: bold' if "🟢" in str(v)
                        else 'background-color: rgba(241, 196, 15, 0.15); color: #D35400; font-weight: bold' for v in col
                    ]
                elif "Freq" in col.name: return ['background-color: rgba(41, 128, 185, 0.15); color: #2980B9; font-weight: bold'] * len(col)
                elif col.name in areas or col.name in ["Total Qty", "Order Qty"]: return ['background-color: rgba(39, 174, 96, 0.15); color: #27AE60; font-weight: bold'] * len(col)
                elif col.name in ["Unit Cost", "Total Cost"]: return ['background-color: rgba(155, 89, 182, 0.11); color: #8E44AD; font-weight: bold'] * len(col)
                return [''] * len(col)

            styled_df = detailed_df.style.apply(color_columns, axis=0).format({
                'Unit Cost': '₹{:.2f}', 'Total Cost': '₹{:.2f}'
            })
            st.dataframe(styled_df, width="stretch")
        
        # --- EXCEL DOWNLOAD ---
        export_cols = list(leading_cols)
        for area in areas:
            export_cols.extend([area, f"{area} Freq"])
        export_cols.extend(['Total Qty', 'Total Freq'])
        export_df = result_df[[c for c in export_cols if c in result_df.columns]]
        
        st.download_button(
            label="Download Full Report (Excel)",
            data=convert_df_to_excel(export_df),
            file_name=f"VECV_Report_{start_date.strftime('%Y%m%d')}_to_{end_date.strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
