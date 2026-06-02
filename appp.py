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
        
        # FIX: Skip blank tables and system tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND TRIM(name) != '';")
        tables = cursor.fetchall()
        table_name = tables[0][0] if tables else "sales_records"
        
        cursor.execute(f"PRAGMA table_info([{table_name}])")
        columns = [col[1] for col in cursor.fetchall()]
        
        part_col = next((c for c in columns if c.lower() in ['partnumber', 'part number', 'material']), columns[0])
        date_col = next((c for c in columns if c.lower() in ['invoicedate', 'invoice date', 'invoice_date', 'date', 'posting date']), columns[0])
        
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

# --- 🔄 ADVANCED MULTI-FORMAT DATE PARSER ---
def safe_parse_mixed_dates(series):
    """Processes clean string dates and raw numerical Excel serial numbers at the same time."""
    str_series = series.astype(str).str.strip()
    is_numeric = str_series.str.match(r'^\d+(\.\d+)?$')
    parsed_datetimes = pd.Series(pd.NaT, index=series.index, dtype='datetime64[ns]')
    
    if is_numeric.any():
        numeric_vals = pd.to_numeric(str_series[is_numeric], errors='coerce')
        parsed_datetimes.loc[is_numeric] = pd.to_datetime(numeric_vals, origin='1899-12-30', unit='D')
        
    non_numeric_mask = ~is_numeric & (str_series != '') & (str_series != 'nan') & str_series.notna()
    if non_numeric_mask.any():
        parsed_datetimes.loc[non_numeric_mask] = pd.to_datetime(str_series[non_numeric_mask], dayfirst=True, errors='coerce')
        
    return parsed_datetimes

# --- ⚡ INSTANT METADATA FETCH ---
def get_db_metadata():
    conn = sqlite3.connect(DB_FILE_PATH)
    cursor = conn.cursor()
    # FIX: Exclude blank table names 
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND TRIM(name) != '';")
    tables = cursor.fetchall()
    table_name = tables[0][0] if tables else "sales_records"
    
    cursor.execute(f"PRAGMA table_info([{table_name}])")
    columns = [col[1] for col in cursor.fetchall()]
    
    date_col = next((c for c in columns if c.lower() in ['invoicedate', 'invoice date', 'invoice_date', 'date', 'posting date']), columns[0])
    
    parsed_min = None
    parsed_max = None
    
    if date_col:
        try:
            query = f"SELECT DISTINCT [{date_col}] FROM [{table_name}] WHERE [{date_col}] IS NOT NULL AND [{date_col}] != ''"
            unique_dates_df = pd.read_sql_query(query, conn)
            
            if not unique_dates_df.empty:
                converted_dates = safe_parse_mixed_dates(unique_dates_df[date_col]).dropna()
                if not converted_dates.empty:
                    parsed_min = converted_dates.min()
                    parsed_max = converted_dates.max()
        except Exception:
            pass
            
    conn.close()
    
    if parsed_min is None or pd.isnull(parsed_min): parsed_min = pd.Timestamp("2025-04-01")
    if parsed_max is None or pd.isnull(parsed_max): parsed_max = pd.Timestamp("2026-05-31")
    
    return table_name, date_col, parsed_min, parsed_max

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

# --- 💡 DEEP FUZZY COLUMN MATCHER ---
def normalize_columns(df, actual_part_col, actual_date_col):
    # Updated to strictly target the new SQL Schema
    exact_qty = ['qty', 'quantity', 'billed qty', 'invoice qty']
    exact_code = ['product_code', 'productcode', 'product code', 'part code', 'item code', 'material code']
    exact_desc = ['description', 'item description', 'part description', 'material description', 'desc']
    exact_area = ['area', 'branch', 'location', 'region', 'city']
    exact_rate = ['cost', 'net_sale', 'gross_sale', 'rate', 'unit cost', 'price', 'basic price', 'amount']

    mapped_targets = set()
    col_map = {}
    
    for col in df.columns:
        l_col = col.lower().strip()
        if l_col == actual_part_col.lower() and 'PartNumber' not in mapped_targets: 
            col_map[col] = 'PartNumber'
            mapped_targets.add('PartNumber')
        elif l_col == actual_date_col.lower() and 'InvoiceDate' not in mapped_targets: 
            col_map[col] = 'InvoiceDate'
            mapped_targets.add('InvoiceDate')
        elif l_col in exact_qty and 'qty' not in mapped_targets: 
            col_map[col] = 'qty'
            mapped_targets.add('qty')
        elif l_col in exact_code and 'Productcode' not in mapped_targets: 
            col_map[col] = 'Productcode'
            mapped_targets.add('Productcode')
        elif l_col in exact_desc and 'description' not in mapped_targets: 
            col_map[col] = 'description'
            mapped_targets.add('description')
        elif l_col in exact_area and 'area' not in mapped_targets: 
            col_map[col] = 'area'
            mapped_targets.add('area')
        elif l_col in exact_rate and 'rate' not in mapped_targets: 
            col_map[col] = 'rate'
            mapped_targets.add('rate')

    df.rename(columns=col_map, inplace=True)
    df = df.loc[:, ~df.columns.duplicated()].copy()
    
    current_mapped = list(col_map.values())
    fuzzy_map = {}
    for col in df.columns:
        if col in current_mapped: continue
        l_col = col.lower().strip()
        
        if 'qty' not in current_mapped and 'qty' not in fuzzy_map.values() and ('qty' in l_col or 'quant' in l_col): fuzzy_map[col] = 'qty'
        elif 'Productcode' not in current_mapped and 'Productcode' not in fuzzy_map.values() and ('code' in l_col or 'group' in l_col): fuzzy_map[col] = 'Productcode'
        elif 'description' not in current_mapped and 'description' not in fuzzy_map.values() and ('desc' in l_col): fuzzy_map[col] = 'description'
        elif 'area' not in current_mapped and 'area' not in fuzzy_map.values() and ('branch' in l_col or 'loc' in l_col or 'plant' in l_col): fuzzy_map[col] = 'area'
        elif 'rate' not in current_mapped and 'rate' not in fuzzy_map.values() and ('price' in l_col or 'cost' in l_col or 'rate' in l_col or 'sale' in l_col): fuzzy_map[col] = 'rate'
            
    df.rename(columns=fuzzy_map, inplace=True)
    df = df.loc[:, ~df.columns.duplicated()].copy()
    
    for req_col in ['PartNumber', 'InvoiceDate', 'qty', 'Productcode', 'description', 'area', 'rate']:
        if req_col not in df.columns:
            if req_col == 'qty': df[req_col] = 0
            elif req_col == 'rate': df[req_col] = 0.0
            else: df[req_col] = "N/A"
            
    return df


# --- ⚡ TARGETED QUERY ENGINE (BULLETPROOF MATCHER) ---
def query_targeted_data(part_numbers):
    if not part_numbers:
        return pd.DataFrame()
        
    conn = sqlite3.connect(DB_FILE_PATH)
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info([{table_name}])")
    columns = [col[1] for col in cursor.fetchall()]
    
    actual_part_col = next((c for c in columns if c.lower() in ['partnumber', 'part number', 'material']), columns[0])
    actual_date_col = next((c for c in columns if c.lower() in ['invoicedate', 'invoice date', 'invoice_date', 'date', 'posting date']), columns[0])
    
    params = []
    for p in part_numbers:
        p_str = str(p).strip().upper()
        params.extend([p_str, f"{p_str}.0"])
            
    placeholders = ', '.join(['?'] * len(params))
    
    query = f"""
        SELECT * FROM [{table_name}] 
        WHERE UPPER(TRIM(CAST([{actual_part_col}] AS TEXT))) IN ({placeholders})
    """
    
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    
    if not df.empty:
        df = normalize_columns(df, actual_part_col, actual_date_col)
        df['PartNumber'] = df['PartNumber'].astype(str).str.strip().str.upper().apply(lambda x: x[:-2] if x.endswith('.0') else x)
        df['InvoiceDate'] = safe_parse_mixed_dates(df['InvoiceDate'])
            
    return df

def generate_filtered_database(df, start_date, end_date):
    if df.empty or 'InvoiceDate' not in df.columns:
        return pd.DataFrame(), ["Hoskote", "Kothagudem", "Ramagundam", "Neyveli", "Nellore"]

    part_col, qty_col, code_col, desc_col = 'PartNumber', 'qty', 'Productcode', 'description'
    rate_col = 'rate'
    area_col = 'area'
    
    # Format the areas to cleanly align with the requested targets
    df[area_col] = df[area_col].astype(str).str.strip().str.title()
    df[area_col] = df[area_col].replace({'Nelore': 'Nellore'})

    master_info = df.copy()
    master_info['desc_len'] = master_info[desc_col].astype(str).str.len()
    master_info = master_info.sort_values(by=[part_col, 'desc_len']).drop_duplicates(subset=[part_col], keep='last')
    master_info = master_info[[part_col, code_col, desc_col]].copy()
    master_info.rename(columns={code_col: 'Product Code', desc_col: 'Description'}, inplace=True)

    max_db_date = df['InvoiceDate'].max()
    if pd.isnull(max_db_date): max_db_date = pd.Timestamp(end_date)
        
    three_months_ago = max_db_date - pd.DateOffset(months=3)
    twelve_months_ago = max_db_date - pd.DateOffset(months=12)

    mask_3m = (df['InvoiceDate'] >= three_months_ago) & (df['InvoiceDate'] <= max_db_date)
    mask_12m = (df['InvoiceDate'] >= twelve_months_ago) & (df['InvoiceDate'] <= max_db_date)
    
    qty_3m = df[mask_3m].groupby(part_col)[qty_col].sum().reset_index(name='qty_3m')
    qty_12m = df[mask_12m].groupby(part_col)[qty_col].sum().reset_index(name='qty_12m')
    
    # 🟢 FIX: Unit Cost -> Total Cost / Total Quantity
    cost_agg = df.groupby(part_col).agg({rate_col: 'sum', qty_col: 'sum'}).reset_index()
    cost_agg['Unit Cost'] = cost_agg.apply(
        lambda x: (x[rate_col] / x[qty_col]) if x[qty_col] != 0 else 0.0, axis=1
    )
    unit_costs = cost_agg[[part_col, 'Unit Cost']]

    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date) + pd.Timedelta(hours=23, minutes=59, seconds=59)

    mask = (df['InvoiceDate'] >= start_ts) & (df['InvoiceDate'] <= end_ts)
    filtered_df = df[mask].copy()
    
    target_areas = ["Hoskote", "Kothagudem", "Ramagundam", "Neyveli", "Nellore"]

    pivot_qty = filtered_df.pivot_table(index=[part_col], columns=area_col, values=qty_col, aggfunc='sum', fill_value=0).reset_index()
    pivot_freq = filtered_df.pivot_table(index=[part_col], columns=area_col, values=qty_col, aggfunc='count', fill_value=0).reset_index()
    
    pivot_qty['Total Qty'] = pivot_qty.drop(columns=[part_col], errors='ignore').sum(axis=1)
    pivot_freq['Total Freq'] = pivot_freq.drop(columns=[part_col], errors='ignore').sum(axis=1)

    for area in target_areas:
        matched_col = next((c for c in pivot_qty.columns if c.lower() == area.lower()), None)
        if matched_col and matched_col != area:
            pivot_qty.rename(columns={matched_col: area}, inplace=True)
            pivot_freq.rename(columns={matched_col: area}, inplace=True)
            
        if area not in pivot_qty.columns: pivot_qty[area] = 0
        if area not in pivot_freq.columns: pivot_freq[area] = 0
            
    freq_rename_map = {area: f"{area} Freq" for area in target_areas}
    pivot_freq.rename(columns=freq_rename_map, inplace=True)
    
    final_db = master_info.copy()
    
    if not pivot_qty.empty:
        qty_merge_cols = [part_col] + target_areas + ['Total Qty']
        final_db = pd.merge(final_db, pivot_qty[qty_merge_cols], on=part_col, how='left').fillna(0)
    else:
        for area in target_areas + ['Total Qty']: final_db[area] = 0
        
    if not pivot_freq.empty:
        freq_merge_cols = [part_col] + list(freq_rename_map.values()) + ['Total Freq']
        final_db = pd.merge(final_db, pivot_freq[freq_merge_cols], on=part_col, how='left').fillna(0)
    else:
        for f_col in list(freq_rename_map.values()) + ['Total Freq']: final_db[f_col] = 0
        
    final_db = pd.merge(final_db, qty_3m, on=part_col, how='left').fillna({'qty_3m': 0})
    final_db = pd.merge(final_db, qty_12m, on=part_col, how='left').fillna({'qty_12m': 0})
    final_db = pd.merge(final_db, unit_costs, on=part_col, how='left').fillna({'Unit Cost': 0.0})
    
    def calculate_trend_row(row):
        q3, q12 = float(row['qty_3m']), float(row['qty_12m'])
        if q12 <= 0: return "🟡 Moderate Trend" if q3 <= 0 else "🟢 Upward Trend"
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
        valid_inputs['PartNumber'] = valid_inputs['PartNumber'].astype(str).str.strip().str.upper().apply(lambda x: x[:-2] if x.endswith('.0') else x)
        
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
        result_df['Product Code'] = result_df.get('Product Code', pd.Series("N/A", index=result_df.index)).fillna("N/A")
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
