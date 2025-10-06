import streamlit as st
import pandas as pd
from datetime import datetime
import matplotlib.pyplot as plt
import plotly.express as px
import matplotlib
import firebase_admin
from firebase_admin import credentials, firestore
import hashlib
import secrets

# ✅ ページ幅を広げる設定
st.set_page_config(page_title="スキルチェックアプリ", layout="wide")

# 日本語フォントを明示的に指定
matplotlib.rcParams['font.family'] = 'IPAPGothic'
matplotlib.rcParams['axes.unicode_minus'] = False

# ---- DB接続 ----
firebase_config = dict(st.secrets["firebase"])
cred = credentials.Certificate(firebase_config)

if not firebase_admin._apps:  # 既存アプリがなければ初期化
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ----パスワードをハッシュ化 ---
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# ---セッションステート初期化 ---
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user_id" not in st.session_state:
    st.session_state.user_id = ""
if "mode" not in st.session_state:
    st.session_state.mode = "save"  # 初期は保存モード
if "all_answers_cache" not in st.session_state:
    st.session_state.all_answers_cache = {}

# --- Excel 読み込みキャッシュ ---
file_path = "skillcheck_ver5.00_simple.xlsx"
sheets = ["ビジネス力","データサイエンス力", "データエンジニアリング力"]

def load_data(sheet_name):
    df = pd.read_excel(file_path, sheet_name=sheet_name, skiprows=2)
    df = df[["NO","スキルカテゴリ","サブカテゴリ","スキルレベル","チェック項目","必須"]]
    df = df.dropna(subset=["チェック項目"])
    df["必須"] = df["必須"].fillna(False).astype(bool)
    return df

sheet_data_cache = {sheet: load_data(sheet) for sheet in sheets}

# --- ページロード時にURLパラメータからトークンを取得して検証 ---
# --- ページロード時にURLパラメータからトークンを取得して検証 ---
query_params = st.query_params
if "token" in query_params and query_params["token"]:
    token = query_params["token"]
    # Firestoreでトークンを検証
    token_docs = db.collection("sessions").where("token", "==", token).get()
    if token_docs:
        st.session_state.logged_in = True
        st.session_state.user_id = token_docs[0].to_dict()["user_id"]
    else:
        st.session_state.logged_in = False
        st.session_state.user_id = ""

# --- ログイン画面 ---
if not st.session_state.get("logged_in", False):
    st.markdown("---")
    st.title("スキルチェックシート分析")
    st.subheader("👤 ログイン")

    username_input = st.text_input("ユーザーID", key="login_user")
    password_input = st.text_input("パスワード", type="password", key="login_pass")

    if st.button("ログイン", key="login_btn"):
        user_doc = db.collection("users").document(username_input).get()
        if user_doc.exists and user_doc.to_dict().get("password") == hash_password(password_input):
            # ログイン成功
            st.session_state.logged_in = True
            st.session_state.user_id = username_input

            # ランダムトークン生成
            token = secrets.token_hex(16)

            # Firestoreにトークン保存（有効期限を追加してもOK）
            db.collection("sessions").document(username_input).set({
                "user_id": username_input,
                "token": token,
                "created_at": datetime.now()
            })

            # URLパラメータにトークンを設定
            st.query_params.clear()
            st.query_params.update({"token": token})

            st.success(f"ログイン成功: {username_input}")
            st.rerun()
        else:
            st.error("ユーザーIDまたはパスワードが間違っています")

    st.markdown("---")

# --- メイン画面 ---
if st.session_state.get("logged_in", False):

    # ---- Firestore 保存処理（1ドキュメントにまとめる）----
    def save_user_sheet_answers(user_id, sheet, answers_dict):
        doc_id = f"{user_id}_{sheet}"
        db.collection("skill_answers").document(doc_id).set({
            "user_id": user_id,
            "sheet": sheet,
            "answers": answers_dict,  # { no: achieved }
            "updated_at": datetime.now()
        })
        # キャッシュを更新
        if user_id not in st.session_state.all_answers_cache:
            st.session_state.all_answers_cache[user_id] = {}
        st.session_state.all_answers_cache[user_id][sheet] = answers_dict

    # ---- Firestore 一括取得（キャッシュ付き） ----
    def get_user_sheet_answers_cached(user_id, sheet):
        if user_id not in st.session_state.all_answers_cache:
            st.session_state.all_answers_cache[user_id] = {}

        if sheet not in st.session_state.all_answers_cache[user_id]:
            doc_id = f"{user_id}_{sheet}"
            doc = db.collection("skill_answers").document(doc_id).get()
            if doc.exists:
                st.session_state.all_answers_cache[user_id][sheet] = doc.to_dict().get("answers", {})
            else:
                st.session_state.all_answers_cache[user_id][sheet] = {}
        return st.session_state.all_answers_cache[user_id][sheet]

    # --- ユーザー回答取得関数 ---
    def get_user_answers(user_id, sheet, filtered_ids):
        all_answers = get_user_sheet_answers_cached(user_id, sheet)
        return {no: all_answers.get(str(no), False) for no in filtered_ids}

    # --- サイドバー ---
    st.sidebar.title("ユーザー設定")
    st.sidebar.markdown(f"**ログイン中のユーザーID:** {st.session_state.user_id}")

    st.sidebar.title("チェックシート設定")
    check_sheet = st.sidebar.selectbox("シートを選択", sheets)

    temp_df = sheet_data_cache[check_sheet]
    categories = temp_df["スキルカテゴリ"].dropna().unique().tolist()

    level_filter = st.sidebar.multiselect("スキルレベルで絞り込み", ["★","★★","★★★"], default=["★"])
    categories_filter = st.sidebar.multiselect("スキルカテゴリで絞り込み", categories, default=[])
    if not categories_filter:
        categories_filter = categories
    required_only = st.sidebar.checkbox("必須項目のみ表示", value=False)

    # --- データフィルタリング ---
    df = temp_df.copy()
    df = df[df["スキルレベル"].isin(level_filter)]
    df = df[df["スキルカテゴリ"].isin(categories_filter)]
    if required_only:
        df = df[df["必須"] == True]

    # モード切替ボタン
    if st.session_state.mode == "save":
        if st.button("→ あなたの達成状況を確認する"):
            st.session_state.mode = "analyze"
            st.rerun()
    elif st.session_state.mode == "analyze":
        if st.button("← スキルチェックを保存する"):
            st.session_state.mode = "save"
            st.rerun()

    st.sidebar.markdown("---")
    if st.sidebar.button("🔓ログアウト", key="logout_btn"):
        st.session_state.logged_in = False
        st.session_state.user_id = ""
        st.query_params.clear()
        st.rerun()  # ✅ ここも変更！

    # --- 保存モード ---
    if st.session_state.mode == "save":
        st.title(f"スキルチェック : {check_sheet}")
        all_answers = get_user_sheet_answers_cached(st.session_state.user_id, check_sheet)

        answer = {}
        for _, row in df.iterrows():
            qid = str(row["NO"])
            default_value = all_answers.get(qid, False)
            label_prefix = "【必須】" if row["必須"] else ""
            label_text = f"{label_prefix}{row['チェック項目']}-{row['スキルレベル']}-"
            answer[qid] = st.checkbox(label_text, key=qid, value=default_value)

        if st.button("保存"):
            save_user_sheet_answers(st.session_state.user_id, check_sheet, answer)
            st.success("FireStoreに保存しました。")

    # --- 分析モード ---
    elif st.session_state.mode == "analyze":
        # 以下の分析コードは従来の get_user_answers 関数をそのまま利用可能
        st.header("📈 全体スキル達成度")

        skillevel_select = st.selectbox(
            "スキルレベルごとにデータを確認する場合は選択してください",
            ["★","★★","★★★","ALL"],
            index=3
        )

        # --- 全体達成度グラフ ---
        def draw_donut_chart(user_id, skillevel_select):
            achieved_count = 0
            total_count = 0
            remaining_required = {"★":0, "★★":0, "★★★":0}

            for sheet in sheets:
                df_sheet = sheet_data_cache[sheet].copy()
                if skillevel_select != "ALL":
                    df_sheet = df_sheet[df_sheet["スキルレベル"] == skillevel_select]

                if df_sheet.empty:
                    continue

                filtered_ids = df_sheet["NO"].tolist()
                result = get_user_answers(user_id, sheet, filtered_ids)
                df_sheet["achieved"] = df_sheet["NO"].map(result)

                achieved_count += df_sheet["achieved"].sum()
                total_count += len(df_sheet)

                for level in ["★","★★","★★★"]:
                    remaining_required[level] += df_sheet[(df_sheet["スキルレベル"]==level) & 
                                                          (~df_sheet["achieved"]) & 
                                                          (df_sheet["必須"])].shape[0]

            if total_count == 0:
                st.info("表示できるデータがありません。")
                return

            values = [achieved_count, total_count - achieved_count]
            fig, ax = plt.subplots()
            ax.pie(values, startangle=90, counterclock=False,
                   colors=["#99CCFF", "#D7D7D7"], wedgeprops=dict(width=0.35))
            ax.axis("equal")
            progress = (achieved_count / total_count) * 100
            ax.text(0, 0, f"進捗度\n{progress:.0f}%", ha="center", va="center", fontsize=16, fontweight="bold", color="black")
            st.markdown(f"###### スキル達成度（{skillevel_select}）")
            st.pyplot(fig)

            if skillevel_select == "ALL":
                total_remaining = sum(remaining_required.values())
                st.markdown(f"**未達成の必須項目数**:**{total_remaining}** 件")
            else:
                st.markdown(f"**未達成の必須項目数**:**{remaining_required[skillevel_select]}** 件")

        def draw_radar_chart_by_level(user_id, skillevel_select):
            radar_scores = {}
            for sheet in sheets:
                df_sheet = sheet_data_cache[sheet].copy()
                if skillevel_select != "ALL":
                    df_sheet = df_sheet[df_sheet["スキルレベル"] == skillevel_select]

                filtered_ids = df_sheet["NO"].tolist()
                if not filtered_ids:
                    radar_scores[sheet] = 0
                    continue

                result = get_user_answers(user_id, sheet, filtered_ids)
                df_sheet["achieved"] = df_sheet["NO"].map(result)

                achieved_count = df_sheet["achieved"].sum()
                total_count = len(df_sheet)
                rate = (achieved_count / total_count) * 100 if total_count > 0 else 0
                radar_scores[sheet] = rate

            if not radar_scores:
                st.info("レーダーチャートを表示できるデータがありません")
                return

            radar_df = pd.DataFrame({
                "category": list(radar_scores.keys()),
                "value": list(radar_scores.values())
            })

            fig = px.line_polar(radar_df, r="value", theta="category",
                                line_close=True, markers=True, range_r=[0,100])
            fig.update_traces(fill="toself")
            fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0,100])),
                              showlegend=False,
                              title=f"全体スキル達成度（{skillevel_select})")
            st.plotly_chart(fig, use_container_width=True)

        col1, col2 = st.columns([4,6])
        with col1:
            draw_donut_chart(st.session_state.user_id, skillevel_select)
        with col2:
            draw_radar_chart_by_level(st.session_state.user_id, skillevel_select)

        explanation = ""

        if skillevel_select == "★":
            explanation = f"Assistant Data Scientist (見習いレベル)：★達成度70％以上 + ★必須項目すべて達成"
        elif skillevel_select == "★★":
            explanation = f"Associate Data Scientist (独り立ちレベル)：★★達成度60％以上 + ★★必須項目すべて達成"
        elif skillevel_select == "★★★":
            explanation = f"Full Data Scientist (棟梁レベル)：★★★達成度50％以上 + ★★★必須項目すべて達成"

        # --- 円グラフの下に表示 ---
        if explanation:
            st.markdown(f"**{explanation}**")

        def draw_summary_table_all_levels(user_id):
            summary_data = {
                "スキルレベル": [],
                "達成/未達成": [],
                "必須(達成/未達成)": [],
                "点数": []
            }

            total_score = 0
            total_max_score = 0

            for level in ["★","★★","★★★"]:
                level_achieved = 0
                level_total = 0
                level_required_achieved = 0
                level_required_total = 0

                for sheet in sheets:
                    df_sheet = load_data(sheet)
                    df_sheet = df_sheet[df_sheet["スキルレベル"] == level]

                    if df_sheet.empty:
                        continue

                    filtered_ids = df_sheet["NO"].tolist()
                    result = get_user_answers(user_id, sheet, filtered_ids)
                    df_sheet["achieved"] = df_sheet["NO"].map(result)

                    # 全項目
                    level_total += len(df_sheet)
                    level_achieved += df_sheet["achieved"].sum()

                    # 必須項目
                    req_df = df_sheet[df_sheet["必須"]]
                    level_required_total += len(req_df)
                    level_required_achieved += req_df["achieved"].sum()

                # スコア計算（必須は+1点ボーナス）
                level_score = level_achieved + level_required_achieved
                level_max_score = level_total + level_required_total

                if level_total > 0:
                    summary_data["スキルレベル"].append(level)
                    summary_data["達成/未達成"].append(f"{level_achieved} / {level_total}")
                    summary_data["必須(達成/未達成)"].append(f"{level_required_achieved} / {level_required_total}")
                    summary_data["点数"].append(f"{level_score} / {level_max_score}")

                    total_score += level_score
                    total_max_score += level_max_score

            # --- 表にして表示 ---
            if summary_data["スキルレベル"]:
                df_summary = pd.DataFrame(summary_data)
                st.markdown("### 📝 スキルレベル別 達成状況")
                st.dataframe(df_summary, use_container_width=True)

                # ✅ 合計点数（必須加算後）
                st.markdown(f"#### ✅ 合計点数: **{total_score} / {total_max_score}**")
            else:
                st.info("表示できるデータがありません。")


        draw_summary_table_all_levels(st.session_state.user_id) # 👈 追加

        # --- スキルカテゴリ別分析 ---
        st.markdown("---")
        st.header("スキルカテゴリ別達成度チェック")
        selected_sheet = st.selectbox("スキルカテゴリを選択してください", sheets)
        level_select = st.selectbox("スキルレベルを選択してください", ["★","★★","★★★","ALL"])

        def load_filtered_sheet(user_id, sheet, level_select):
            df_sheet = sheet_data_cache[sheet].copy()
            if level_select != "ALL":
                df_sheet = df_sheet[df_sheet["スキルレベル"] == level_select]
            if df_sheet.empty:
                return pd.DataFrame()
            filtered_ids = df_sheet["NO"].tolist()
            result = get_user_answers(user_id, sheet, filtered_ids)
            df_sheet["achieved"] = df_sheet["NO"].map(result)
            return df_sheet

        def skill_pie_chart(df_sheet, sheet, level_select):
            if df_sheet.empty:
                st.info("対象データがありません")
                return
            achieved_count = df_sheet["achieved"].sum()
            unachieved_count = (~df_sheet["achieved"]).sum()
            values = [achieved_count, unachieved_count]
            fig, ax = plt.subplots()
            ax.pie(values, startangle=90, counterclock=False,
                   colors=["#99CCFF", "#D7D7D7"], wedgeprops=dict(width=0.35))
            ax.axis("equal")
            total_count = df_sheet.shape[0]
            progress = (achieved_count / total_count) * 100 if total_count > 0 else 0
            ax.text(0, 0, f"達成度\n{progress:.0f}%", ha="center", va="center", fontsize=16, fontweight="bold", color="black")
            st.markdown(f"###### {sheet} - {level_select} 達成度チェック分析")
            st.pyplot(fig)

        def skill_radar_chart(df_sheet, sheet, level_select):
            if df_sheet.empty:
                st.info("対象データがありません")
                return
            category_rates = {}
            for cat, group in df_sheet.groupby("スキルカテゴリ"):
                total = len(group)
                achieved = group["achieved"].sum()
                category_rates[cat] = (achieved / total) * 100 if total > 0 else 0
            radar_df = pd.DataFrame({"category": list(category_rates.keys()), "value": list(category_rates.values())})
            fig = px.line_polar(radar_df, r="value", theta="category", line_close=True, markers=True, range_r=[0,100])
            fig.update_traces(fill="toself")
            fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0,100])),
                              showlegend=False,
                              title=f"{sheet} - {level_select} スキルカテゴリ達成率（レーダーチャート）")
            st.plotly_chart(fig, use_container_width=True)

        def draw_summary_table(df_sheet, sheet, level_select):
            if df_sheet.empty:
                st.info("対象データがありません")
                return
            achieved_count = df_sheet[df_sheet["achieved"]==True]["スキルカテゴリ"].value_counts()
            total_count = df_sheet["スキルカテゴリ"].value_counts()
            summary_df = pd.DataFrame({"達成件数": achieved_count, "合計件数": total_count}).fillna(0).astype(int)
            summary_df["達成/合計"] = summary_df["達成件数"].astype(str) + "/" + summary_df["合計件数"].astype(str)
            st.markdown(f"##### {sheet} - {level_select} 達成状況")
            st.dataframe(summary_df[["達成/合計"]])

        # --- 実行 ---
        df_sheet = load_filtered_sheet(st.session_state.user_id, selected_sheet, level_select)
        col1, col2 = st.columns([4, 6])
        with col1:
            skill_pie_chart(df_sheet, selected_sheet, level_select)
        with col2:
            skill_radar_chart(df_sheet, selected_sheet, level_select)
        st.markdown("---")
        draw_summary_table(df_sheet, selected_sheet, level_select)

        st.markdown("---")
        st.markdown("""
            出典先：情報処理推進機構(IPA)「データサイエンティスト スキルチェックシート Ver5.00」
        """)
        st.markdown("""
         © IPA — 本アプリはIPAの公開資料をもとに作成したものであり、非営利・教育目的での利用のみを目的としています。
""")
