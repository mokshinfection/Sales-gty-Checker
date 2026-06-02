import streamlit as st
import pandas as pd
from datetime import datetime
import io
import zipfile

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Sales Quantity Checker", layout="wide")
st.title("Sales Quantity Checker")

# 🔴 GITHUB RAW URL 🔴
GITHUB_CSV_URL = "https://raw.githubusercontent.com/mokshinfection/Sales-gty-Checker/main/Sales.zip"

# --- DATA PROCESSING (NOW LOADS FULL DATA IN CACHE) ---
@st.cache_data(ttl=3600)
def load_raw_backend_data(url):
    """Fetches full historical data from GitHub and caches it."""
    df = pd.read_csv(url, compression='zip', low_memory=False, on_bad_lines='skip')
    df.columns = df.columns.str.strip()
    
    date_col = 'Invoice Date' if 'Invoice Date' in df.columns else 'Date'
    if date_col not in df.columns:
        raise KeyError(f"Could not find a date column. Columns found: {', '.join(df.columns)}")
        
    df[date_col] = pd.to_datetime(df[date_col], dayfirst=True, errors='coerce')
    df = df.dropna(subset=[date_col]) 
    
    return df, date_col

def generate_filtered_database(df, date_col, start_date, end_date):
    """Slices data by selected dates and pivots to find Quantities AND Frequencies per area."""
    mask = (df[date_col].dt.date >= start_date) & (df[date_col].dt.date <= end_date)
    filtered_df = df[mask].copy()
    
    target_areas = ["Hoskote", "Kothagudem", "Ramagundam", "Neyveli", "Nellore"]
    part_col = 'PartNumber' if 'PartNumber' in df.columns else 'Part Number'
    desc_col = 'Description'
    code_col = 'Product Code' if 'Product Code' in df.columns else 'Part Code'
    qty_col = 'qty' if 'qty' in df.columns else 'Quantity'
    
    # 1. Pivot for QUANTITY
    pivot_qty = filtered_df.pivot_table(
        index=[part_col, code_col, desc_col], columns='Area', values=qty_col, aggfunc='sum', fill_value=0
    ).reset_index()
    
    # 2. Pivot for FREQUENCY 
    pivot_freq = filtered_df.pivot_table(
        index=[part_col, code_col, desc_col], columns='Area', values=qty_col, aggfunc='count', fill_value=0
    ).reset_index()
    
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
    
    return final_db, target_areas

# --- EXCEL EXPORT HELPER ---
def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sales Report')
    return output.getvalue()


# --- SIDEBAR: SYSTEM STATUS & UPDATE ---
with st.sidebar:
    st.header("System Status")
    try:
        with st.spinner("Fetching full historical data from GitHub..."):
            raw_data, date_col_name = load_raw_backend_data(GITHUB_CSV_URL)
            db_min_date = raw_data[date_col_name].min().date()
            db_max_date = raw_data[date_col_name].max().date()
            
        st.success("Database Active & In-Memory")
        st.info(f"**Total History Available:**\n\n{db_min_date.strftime('%d %b %Y')} to {db_max_date.strftime('%d %b %Y')}")
        
        if st.button("Force Data Refresh"):
            st.cache_data.clear()
            st.rerun()
    except Exception as e:
        st.error(f"Failed to load data from GitHub.\n\nError: {e}")
        st.stop()
        
    st.divider()
    st.header("Update Master Database")
    st.write("Upload your new data files to merge them with the base file.")
    
    # 🔄 MULTI-FILE LOADING ENABLED HERE
    monthly_files = st.file_uploader("Upload New Month Data Files", type=["csv", "xlsx"], accept_multiple_files=True)
    
    if monthly_files:
        try:
            new_dataframes = []
            for file in monthly_files:
                if file.name.endswith('.csv'):
                    df_temp = pd.read_csv(file, low_memory=False)
                else:
                    df_temp = pd.read_excel(file)
                
                df_temp.columns = df_temp.columns.str.strip()
                new_dataframes.append(df_temp)
                
            with st.spinner("Merging all files with Master Database..."):
                raw_base_df = pd.read_csv(GITHUB_CSV_URL, compression='zip', low_memory=False, on_bad_lines='skip')
                raw_base_df.columns = raw_base_df.columns.str.strip()
                
                all_dfs = [raw_base_df] + new_dataframes
                updated_master_df = pd.concat(all_dfs, ignore_index=True).drop_duplicates()
                
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                    zip_file.writestr("Sales.csv", updated_master_df.to_csv(index=False)) 
                    
                st.success(f"Successfully Merged {len(monthly_files)} file(s)! Total Size: {len(updated_master_df)} rows.")
                st.download_button("Download New Master File (.zip)", data=zip_buffer.getvalue(), file_name="Sales.zip", mime="application/zip")
        except Exception as e:
            st.error(f"Error merging files: {e}")


# --- DATE FILTERING UI ---
st.write("### Set Timeframe")

time_preset = st.radio("Quick Filters:", ["Last 3 Months", "Last 6 Months", "Last 12 Months", "Custom Range"], horizontal=True)

if time_preset == "Last 3 Months":
    start_date = (db_max_date - pd.DateOffset(months=3)).date()
    end_date = db_max_date
elif time_preset == "Last 6 Months":
    start_date = (db_max_date - pd.DateOffset(months=6)).date()
    end_date = db_max_date
elif time_preset == "Last 12 Months":
    start_date = (db_max_date - pd.DateOffset(months=12)).date()
    end_date = db_max_date
else:
    date_range = st.slider("Select Custom Date Range", min_value=db_min_date, max_value=db_max_date, value=(db_min_date, db_max_date), format="DD/MM/YY")
    start_date, end_date = date_range[0], date_range[1]

database, areas = generate_filtered_database(raw_data, date_col_name, start_date, end_date)


# --- MAIN INTERFACE: THE CHECKER ---
st.write("### Enter Part Numbers")

if 'editor_key' not in st.session_state: st.session_state['editor_key'] = 0
if 'input_df' not in st.session_state: st.session_state['input_df'] = pd.DataFrame({"PartNumber": ["", "", "", "", ""]})

if st.button("Clear List", key="clear_list_btn"):
    st.session_state['input_df'] = pd.DataFrame({"PartNumber": ["", "", "", "", ""]})
    st.session_state['editor_key'] += 1
    st.rerun()

edited_input = st.data_editor(
    st.session_state['input_df'],
    num_rows="dynamic",
    column_config={"PartNumber": st.column_config.TextColumn("Part Number (Editable)", required=True)},
    key=f"data_editor_{st.session_state['editor_key']}" 
)

if not edited_input.empty:
    valid_inputs = edited_input[edited_input["PartNumber"].astype(str).str.strip() != ""]
    if not valid_inputs.empty:
        valid_inputs['PartNumber'] = valid_inputs['PartNumber'].astype(str)
        database['PartNumber'] = database['PartNumber'].astype(str)
        
        result_df = pd.merge(valid_inputs, database, on="PartNumber", how="left")
        
        result_df['Description'] = result_df['Description'].fillna("Not Found")
        result_df['Product Code'] = result_df['Product Code'].fillna("N/A")
        
        all_numeric_cols = areas + [f"{a} Freq" for a in areas] + ['Total Qty', 'Total Freq']
        for col in all_numeric_cols:
            if col in result_df.columns:
                result_df[col] = result_df[col].fillna(0).astype(int)
        
        st.write("### Final Sales Report")
        
        st.info(f"**Data Range Selected:** Quantities and Frequencies below represent sales from **{start_date.strftime('%d %b %Y')}** to **{end_date.strftime('%d %B %Y')}**")
        
        view_mode = st.radio(
            "Select Display Format:", 
            ["Color-Coded Detailed View", "Compact View (Text Combined)"], 
            horizontal=True
        )
        
        if view_mode == "Compact View (Text Combined)":
            display_df = result_df[['PartNumber', 'Product Code', 'Description']].copy()
            for area in areas:
                display_df[area] = "Qty: " + result_df[area].astype(str) + " | Freq: " + result_df[f"{area} Freq"].astype(str)
            display_df['Total'] = "Qty: " + result_df['Total Qty'].astype(str) + " | Freq: " + result_df['Total Freq'].astype(str)
            
            # 💡 UPDATED: use_container_width=True changed to width='stretch' to match your logs' warning
            st.dataframe(display_df, width="stretch")
            
        else:
            display_cols = ['PartNumber', 'Product Code', 'Description']
            for area in areas:
                display_cols.extend([area, f"{area} Freq"])
            display_cols.extend(['Total Qty', 'Total Freq'])
            
            detailed_df = result_df[[c for c in display_cols if c in result_df.columns]]
            
            def color_columns(col):
                if "Freq" in col.name:
                    return ['background-color: rgba(41, 128, 185, 0.15); color: #2980B9; font-weight: bold'] * len(col)
                elif col.name in areas or col.name == "Total Qty":
                    return ['background-color: rgba(39, 174, 96, 0.15); color: #27AE60; font-weight: bold'] * len(col)
                else:
                    return [''] * len(col)

            styled_df = detailed_df.style.apply(color_columns, axis=0)
            
            # 💡 UPDATED: use_container_width=True changed to width='stretch'
            st.dataframe(styled_df, width="stretch")
        
        # --- EXCEL DOWNLOAD ---
        export_cols = ['PartNumber', 'Product Code', 'Description']
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
