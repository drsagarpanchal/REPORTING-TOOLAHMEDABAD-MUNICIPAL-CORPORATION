import io
from datetime import datetime

import pandas as pd
import streamlit as st

st.set_page_config(page_title="AMC Reporting Assistant", page_icon="📊", layout="wide")

META_COLUMNS = ["_status", "_submitted_at", "_submitted_by"]


def initialize_state() -> None:
    defaults = {
        "raw_df": None,
        "working_df": None,
        "file_name": None,
        "id_col": None,
        "unit_col": None,
        "respondent_col": None,
        "deadline_col": None,
        "required_cols": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


initialize_state()


@st.cache_data(show_spinner=False)
def read_upload(uploaded_file) -> pd.DataFrame:
    file_name = uploaded_file.name.lower()
    if file_name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    return pd.read_excel(uploaded_file)


def ensure_tracking_columns(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()
    for col in META_COLUMNS:
        if col not in data.columns:
            data[col] = ""

    required_cols = st.session_state.get("required_cols", [])
    if required_cols:
        filled_mask = data[required_cols].notna().all(axis=1)
        non_blank_mask = data[required_cols].astype(str).apply(
            lambda x: x.str.strip() != ""
        ).all(axis=1)
        data["_status"] = [
            "Submitted" if filled and non_blank else "Pending"
            for filled, non_blank in zip(filled_mask, non_blank_mask)
        ]

        current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        for idx, is_filled in filled_mask.items():
            if is_filled and not data.at[idx, "_submitted_at"]:
                data.at[idx, "_submitted_at"] = current_time
    return data


def parse_deadline(value):
    if value in (None, ""):
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.to_pydatetime()


def compute_kpis(df: pd.DataFrame):
    total = len(df)
    submitted = (df["_status"] == "Submitted").sum()
    pending = (df["_status"] != "Submitted").sum()

    overdue = 0
    due_soon = 0
    deadline_col = st.session_state.deadline_col
    if deadline_col and deadline_col in df.columns:
        now = datetime.utcnow()
        for _, row in df.iterrows():
            deadline = parse_deadline(row.get(deadline_col))
            if not deadline or row.get("_status") == "Submitted":
                continue
            hours_left = (deadline - now).total_seconds() / 3600
            if hours_left < 0:
                overdue += 1
            elif hours_left <= 12:
                due_soon += 1

    return total, submitted, pending, overdue, due_soon


st.title("📊 AMC Daily Reporting Assistant")
st.caption(
    "Upload your Google Sheet export once, track pending units, and allow phone-friendly entry."
)

with st.sidebar:
    st.header("1) Upload Reporting Sheet")
    uploaded_file = st.file_uploader(
        "Upload CSV/Excel exported from Google Sheet",
        type=["csv", "xlsx", "xls"],
    )

    if uploaded_file is not None:
        incoming_df = read_upload(uploaded_file)
        st.session_state.raw_df = incoming_df
        st.session_state.file_name = uploaded_file.name

        options = list(incoming_df.columns)
        st.markdown("### 2) Configure Template")
        st.session_state.id_col = st.selectbox(
            "Unique Respondent ID column",
            options=options,
            index=options.index(st.session_state.id_col)
            if st.session_state.id_col in options
            else 0,
        )
        st.session_state.unit_col = st.selectbox(
            "Zone/UPHC column",
            options=options,
            index=options.index(st.session_state.unit_col)
            if st.session_state.unit_col in options
            else 0,
        )
        st.session_state.respondent_col = st.selectbox(
            "Respondent name column",
            options=options,
            index=options.index(st.session_state.respondent_col)
            if st.session_state.respondent_col in options
            else 0,
        )

        deadline_choices = ["(No deadline column)"] + options
        existing_deadline = (
            st.session_state.deadline_col
            if st.session_state.deadline_col in options
            else "(No deadline column)"
        )
        selected_deadline = st.selectbox(
            "Deadline column (optional)",
            options=deadline_choices,
            index=deadline_choices.index(existing_deadline),
        )
        st.session_state.deadline_col = (
            None
            if selected_deadline == "(No deadline column)"
            else selected_deadline
        )

        skip_cols = {
            st.session_state.id_col,
            st.session_state.unit_col,
            st.session_state.respondent_col,
        }
        if st.session_state.deadline_col:
            skip_cols.add(st.session_state.deadline_col)

        data_columns = [c for c in options if c not in skip_cols]

        st.session_state.required_cols = st.multiselect(
            "Columns respondents must fill",
            options=data_columns,
            default=data_columns[: min(3, len(data_columns))],
        )

        if st.button("Apply Template"):
            if not st.session_state.required_cols:
                st.error("Select at least one required reporting column.")
            else:
                st.session_state.working_df = ensure_tracking_columns(incoming_df)
                st.success("Template configured. Use tabs below.")

if st.session_state.working_df is None:
    st.info(
        "Please upload and configure your sheet from the sidebar to start data collection monitoring."
    )
    st.stop()

current_df = st.session_state.working_df
total, submitted, pending, overdue, due_soon = compute_kpis(current_df)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Respondents", total)
col2.metric("Submitted", submitted)
col3.metric("Pending", pending)
col4.metric("Overdue", overdue)
col5.metric("Due in 12h", due_soon)


tab1, tab2, tab3 = st.tabs(["📲 Respondent Entry", "🧭 Officer Dashboard", "🔔 Reminder Center"])

with tab1:
    st.subheader("Mobile-Friendly Form")
    st.write("Respondent can fill data by entering their unique ID.")

    lookup_value = st.text_input("Enter Respondent ID")
    if lookup_value:
        id_col = st.session_state.id_col
        match = current_df[current_df[id_col].astype(str) == str(lookup_value)]
        if match.empty:
            st.error("No matching Respondent ID found.")
        else:
            row_idx = match.index[0]
            row = match.iloc[0]
            st.success(
                f"Respondent: {row[st.session_state.respondent_col]} | Unit: {row[st.session_state.unit_col]}"
            )

            with st.form("respondent_form"):
                input_values = {}
                for field in st.session_state.required_cols:
                    existing = "" if pd.isna(row[field]) else str(row[field])
                    input_values[field] = st.text_input(field, value=existing)

                submitted_btn = st.form_submit_button("Submit Report")
                if submitted_btn:
                    for field, val in input_values.items():
                        current_df.at[row_idx, field] = val
                    current_df.at[row_idx, "_submitted_by"] = str(lookup_value)
                    current_df.at[row_idx, "_submitted_at"] = datetime.utcnow().strftime(
                        "%Y-%m-%d %H:%M UTC"
                    )
                    st.session_state.working_df = ensure_tracking_columns(current_df)
                    st.success("Report submitted successfully.")

with tab2:
    st.subheader("Live Monitoring Dashboard")

    unit_col = st.session_state.unit_col
    summary = (
        current_df.groupby([unit_col, "_status"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values([unit_col, "_status"])
    )
    st.dataframe(summary, use_container_width=True)

    st.markdown("### Pending Respondents")
    pending_df = current_df[current_df["_status"] != "Submitted"]
    show_cols = [
        st.session_state.id_col,
        st.session_state.respondent_col,
        st.session_state.unit_col,
    ]
    if st.session_state.deadline_col:
        show_cols.append(st.session_state.deadline_col)

    st.dataframe(pending_df[show_cols], use_container_width=True)

    st.markdown("### Submitted Respondents")
    submitted_df = current_df[current_df["_status"] == "Submitted"]
    st.dataframe(
        submitted_df[show_cols + ["_submitted_at"]],
        use_container_width=True,
    )

with tab3:
    st.subheader("Reminder Queue (Notification Ready)")
    st.write(
        "This section tells whom to notify now. Integrate SMS/WhatsApp API later if needed."
    )

    reminder_rows = []
    now = datetime.utcnow()

    for _, row in current_df.iterrows():
        if row["_status"] == "Submitted":
            continue

        deadline_note = "No deadline"
        urgency = "Normal"
        deadline_col = st.session_state.deadline_col

        if deadline_col and deadline_col in current_df.columns:
            deadline = parse_deadline(row.get(deadline_col))
            if deadline:
                diff_hrs = (deadline - now).total_seconds() / 3600
                if diff_hrs < 0:
                    urgency = "Overdue"
                elif diff_hrs <= 12:
                    urgency = "Due Soon"
                deadline_note = deadline.strftime("%Y-%m-%d %H:%M")

        reminder_rows.append(
            {
                "Respondent": row[st.session_state.respondent_col],
                "Unit": row[st.session_state.unit_col],
                "Status": row["_status"],
                "Deadline": deadline_note,
                "Priority": urgency,
            }
        )

    reminder_df = pd.DataFrame(reminder_rows)
    if reminder_df.empty:
        st.success("No pending reminders. Great job!")
    else:
        priority_order = {"Overdue": 0, "Due Soon": 1, "Normal": 2}
        reminder_df["_sort"] = reminder_df["Priority"].map(priority_order)
        reminder_df = reminder_df.sort_values(["_sort", "Unit"]).drop(columns=["_sort"])
        st.dataframe(reminder_df, use_container_width=True)

st.markdown("---")
output_buffer = io.BytesIO()
export_df = st.session_state.working_df.copy()
export_df.to_excel(output_buffer, index=False)
output_buffer.seek(0)

st.download_button(
    "⬇️ Download Updated Reporting File",
    data=output_buffer,
    file_name="amc_reporting_updated.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
