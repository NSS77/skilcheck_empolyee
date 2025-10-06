import streamlit as st
import pandas as pd
from datetime import datetime
import matplotlib.pyplot as plt
import plotly.express as px
import plotly.graph_objects as go
import matplotlib
import firebase_admin
from firebase_admin import credentials, firestore
import hashlib

# ✅ ページ幅を広げる設定
st.set_page_config(page_title="スキルチェックアプリ", layout="wide")

# 日本語フォントを明示的に指定
matplotlib.rcParams['font.family'] = 'Meiryo'   # Windows
# matplotlib.rcParams['font.family'] = 'IPAexGothic' # Mac/Linuxならこちら

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
# セッションステートにモード保持
if "mode" not in st.session_state:
    st.session_state.mode = "save"  # 初期は保存モード


# --- ログイン画面 ---
if not st.session_state.get("logged_in", False):
    st.markdown("----")  # 上の線
    st.title("スキルチェックシート分析")
    st.subheader("👤 ログイン")

    username_input = st.text_input("ユーザーID", key="login_user")
    password_input = st.text_input("パスワード", type="password", key="login_pass")

    if st.button("ログイン", key="login_btn"):
        user_doc = db.collection("users").document(username_input).get()
        if user_doc.exists and user_doc.to_dict().get("password") == hash_password(password_input):
            st.session_state.logged_in = True
            st.session_state.user_id = username_input
            st.success(f"ログイン成功: {username_input}")
            st.rerun()
        else:
            st.error("ユーザーIDまたはパスワードが間違っています")
    st.markdown("----")  # 下の線

# --- メイン画面 ---
if st.session_state.get("logged_in", False):

    # ---- Firestore 保存処理 ---
    def save_answer(user_id, sheet, no, category, level, question, achieved):
        doc_id = f"{user_id}_{sheet}_{no}"
        db.collection("skill_answers").document(doc_id).set({
            "user_id": user_id,
            "sheet": sheet,
            "no": no,
            "category": category,
            "level": level,
            "question": question,
            "achieved": achieved,
            "updated_at": datetime.now()
        })


    # ---- テーブル作成 ----
    def load_answer(user_id, sheet, no):
        doc_id =  f"{user_id}_{sheet}_{no}"
        doc = db.collection("skill_answers").document(doc_id).get()
        return doc.to_dict() if doc.exists else None

    #  ----- Excel 読み込み  --
    file_path = "skillcheck_ver5.00_simple.xlsx"
    sheets = ["ビジネス力","データサイエンス力", "データエンジニアリング力"]

    def load_data(sheet_name):
        df = pd.read_excel(file_path, sheet_name=sheet_name, skiprows=2)
        # 必須列も読み込む
        df = df[["NO","スキルカテゴリ","サブカテゴリ","スキルレベル","チェック項目","必須"]]
        df = df.dropna(subset=["チェック項目"])
        # NaN を False に変換
        df["必須"] = df["必須"].fillna(False)
        # TRUE/FALSE を Python の bool に変換（Excelからは np.bool になる場合がある）
        df["必須"] = df["必須"].astype(bool)
        return df

   # --- サイドバー：　ユーザー設定 ---
    st.sidebar.title("ユーザー設定")
    st.sidebar.markdown(f"**ログイン中のユーザーID:** {st.session_state.user_id}")

    # --- サイドバー:  スキルチェック設定 ---
    st.sidebar.title("チェックシート設定")
    check_sheet = st.sidebar.selectbox("シートを選択",sheets)

    temp_df = load_data(check_sheet)
    categories = temp_df["スキルカテゴリ"].dropna().unique().tolist()

    level_filter = st.sidebar.multiselect(
        "スキルレベルで絞り込み",
        ["★","★★","★★★"],
        default=["★"]
    )

    default_category = categories[0] if categories else None #要素があれば、先頭の要素（categories[0])を代入。

    # ✅ 初期値は空（＝何も選択されていない）
    categories_filter = st.sidebar.multiselect(
        "スキルカテゴリで絞り込み",
        categories,
        default=[]
    )

    # ✅ もしユーザーが何も選ばなかったら「全カテゴリ」を適用
    if not categories_filter:
        categories_filter = categories

    required_only = st.sidebar.checkbox("必須項目のみ表示", value=False)

    # --- データフィルタリング ---
    df = temp_df #元データをコピー（作業用に使用）
    df = df[df["スキルレベル"].isin(level_filter)] #スキルレベルでフィルタリング（ユーザーが選択したレベルだけ残す）
    df = df[df["スキルカテゴリ"].isin(categories_filter)] #スキルカテゴリでフィルタリング(ユーザーが選択したカテゴリだけ残す)
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
        st.rerun()

    if st.session_state.mode == "save":
        # --- 回答フォーム ---
        st.title(f"スキルチェック : {check_sheet}")

        answer = {} #ユーザーの回答状況を格納する辞書
        for _, row in df.iterrows():
            qid = str(row["NO"]) #質問ID（DB上のNOを文字列化)
            existing = load_answer(st.session_state.user_id, check_sheet,row["NO"])
            default_value = existing["achieved"] if existing else False

            label_prefix = "【必須】" if row["必須"] else ""
            label_text = f"{label_prefix}{row['チェック項目']}"

            answer[qid] = st.checkbox(label_text, key=qid, value=default_value)

        if st.button("保存"):
            for no, achieved in answer.items():
                qrow = df[df["NO"] == int(no)].iloc[0]
                save_answer(
                    st.session_state.user_id,
                    check_sheet,
                    int(no),
                    qrow["スキルカテゴリ"],
                    qrow["スキルレベル"],
                    qrow["チェック項目"],
                    achieved
                )
            st.success("FireStoreに保存しました。")

    elif st.session_state.mode == "analyze":
        # ---- 全体スキル達成状況（表形式）表示
        st.header("📈 全体スキル達成度")

        #スキルレベル選択
        skillevel_select = st.selectbox(
            "スキルレベルごとにデータを確認する場合は選択してください",
            ["★","★★","★★★","ALL"],
            index = 3 )


        #ユーザーの回答取得部分
        def get_user_answers(user_id, sheet, filtered_ids):
            docs = db.collection("skill_answers") \
                    .where("user_id","==", user_id) \
                    .where("sheet","==",sheet) \
                    .stream()
            
            # FireStoreから取得したデータを辞書化
            result = {no: False for no in filtered_ids}
            for doc in docs:
                data = doc.to_dict()
                no = data.get("no")
                if no in filtered_ids:
                    result[no] = data.get("achieved",False)
            return result

        # ---全体達成度グラフ（円グラフ）関数 
        def draw_donut_chart(user_id, skillevel_select):
            achieved_count = 0
            total_count = 0
            remaining_required = {"★":0, "★★":0, "★★★":0}  # スキルレベルごとの残り必須数

            for sheet in sheets:
                df_sheet = load_data(sheet)
                
                # ALL以外はスキルレベルでフィルタ
                if skillevel_select != "ALL":
                    df_sheet = df_sheet[df_sheet["スキルレベル"] == skillevel_select]

                if df_sheet.empty:
                    continue

                filtered_ids = df_sheet["NO"].tolist()

                # FieStoreから達成状況を取得
                result = get_user_answers(user_id, sheet , filtered_ids)

                #DataFrameにマージ
                df_sheet["achieved"] = df_sheet["NO"].map(result)

                # 全体達成状況を加算
                achieved_count += df_sheet["achieved"].sum()
                total_count += len(df_sheet)

                # 必須項目で未達成の件数をスキルレベルごとにカウント
                for level in ["★","★★","★★★"]:
                    remaining_required[level] += df_sheet[(df_sheet["スキルレベル"]==level) & 
                                                        (~df_sheet["achieved"]) &
                                                        (df_sheet["必須"])
                                                        ].shape[0]

            if total_count == 0:
                st.info("表示できるデータがありません。")
                return

            # ドーナツグラフ
            values = [achieved_count, total_count - achieved_count]
            fig, ax = plt.subplots()
            ax.pie(
                values,
                startangle=90,
                counterclock=False,
                colors=["#99CCFF", "#D7D7D7"],
                wedgeprops=dict(width=0.35)
            )
            ax.axis("equal")
            progress = (achieved_count / total_count) * 100
            ax.text(0, 0, f"進捗度\n{progress:.0f}%", ha="center", va="center", fontsize=16, fontweight="bold", color="black")
            st.markdown(f"###### スキル達成度（{skillevel_select}）")
            st.pyplot(fig)

            # 必須項目残り件数を表示
            if skillevel_select == "ALL":
                total_remaining = sum(remaining_required.values())
                st.markdown(f"**未達成の必須項目数**:**{total_remaining}** 件")
            else:
                st.markdown(f"**未達成の必須項目数**:**{remaining_required[skillevel_select]}** 件")


        #　--- レーダーチャート描画関数 ---
        def draw_radar_chart_by_level(user_id , skillevel_select):
            radar_scores = {}
            for sheet in sheets:
                df_sheet = load_data(sheet)
                if skillevel_select !="ALL":
                    df_sheet = df_sheet[df_sheet["スキルレベル"] == skillevel_select]

                filtered_ids = df_sheet["NO"].tolist() #スキルNoをリスト化
                if not filtered_ids:
                    radar_scores[sheet] = 0 #データがなければ0%
                    continue

                result = get_user_answers(user_id,sheet, filtered_ids)
                df_sheet["achieved"] = df_sheet["NO"].map(result)

                achieved_count = df_sheet["achieved"].sum()
                total_count = len(df_sheet)
                rate = (achieved_count / total_count) * 100 if total_count > 0 else 0 
                radar_scores[sheet] = rate

            if not radar_scores:
                st.info("レーダーチャートを表示できるデータがありません")
                return
            
            # データフレームに変換
            rader_df = pd.DataFrame({
                "category": list(radar_scores.keys()),
                "value": list(radar_scores.values())
            })

            # Plotly Expressでレーダーチャート描画
            fig = px.line_polar(
                rader_df, r="value", theta="category",
                line_close=True, markers=True, range_r =[0,100]
            )
            fig.update_traces(fill="toself") #面を塗りつぶし
            fig.update_layout(
                polar=dict(
                    radialaxis=dict(visible=True, range=[0,100])
                ),
                showlegend = False,
                title=f"全体スキル達成度（{skillevel_select})"
            )

            #Streamlitに表示
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

        st.markdown("---")
        st.header("スキルカテゴリ別達成度チェック")
        selected_sheet = st.selectbox("スキルカテゴリを選択してください",sheets)
        level_select = st.selectbox("スキルレベルを選択してください",["★","★★","★★★","ALL"])

        def load_filtered_sheet(user_id,sheet,level_select):
            df_sheet = load_data(sheet)
            if level_select != "ALL":
                df_sheet = df_sheet[df_sheet["スキルレベル"] == level_select]
            if df_sheet.empty:
                return pd.DataFrame()
            filtered_ids = df_sheet["NO"].tolist()
            result = get_user_answers(user_id, sheet, filtered_ids)
            df_sheet["achieved"] = df_sheet["NO"].map(result)
            return df_sheet

        def skill_pie_cart(df_sheet, sheet, level_select):
            # データが存在しない場合は情報表示して終了
            if df_sheet.empty:
                st.info("対象データがありません")
                return

            # 達成・未達成件数を集計
            achieved_count = df_sheet["achieved"].sum()          # True の件数
            unachieved_count = (~df_sheet["achieved"]).sum()     # False の件数

            values = [achieved_count, unachieved_count]

            # matplotlibでドーナツ型円グラフ作成
            fig, ax = plt.subplots()
            ax.pie(
                values,
                startangle=90,
                counterclock=False,
                colors=["#99CCFF", "#D7D7D7"],  # ← color → colors に修正
                wedgeprops=dict(width=0.35)
            )
            ax.axis("equal")  # 円を正円にする

            # 円の中央に達成率を表示
            total_count = df_sheet.shape[0]
            progress = (achieved_count / total_count) * 100 if total_count > 0 else 0
            ax.text(
                0, 0, f"達成度\n{progress:.0f}%",
                ha="center", va="center", fontsize=16, fontweight="bold", color="black"
            )

            st.markdown(f"###### {sheet} - {level_select} 達成度チェック分析")
            st.pyplot(fig)


        # --- 2. レーダーチャート表示関数
        def skill_radar_chart(df_sheet ,sheet, level_select):
            # データが空の場合は処理せずにメッセージ表示
            if df_sheet.empty:
                st.info("対象データがありません")
                return
            
            # スキルカテゴリごとの達成率を計算
            category_rates = {}
            for cat, group in df_sheet.groupby("スキルカテゴリ"):
                total = len(group)
                achieved = group["achieved"].sum()
                category_rates[cat] = (achieved / total) * 100 if total > 0 else 0

            #DataFrameに変換
            radar_df = pd.DataFrame({
                "category" : list(category_rates.keys()),
                "value" : list(category_rates.values())
            })

            # Plotlyでレーダーチャート作成
            fig = px.line_polar(
                radar_df, r="value", theta="category",
                line_close=True, markers=True, range_r=[0,100]
            )
            fig.update_traces(fill="toself") # レーダーチャートの内部を塗りつぶす
            fig.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0,100])), # 軸を固定
                showlegend=False,                                          # 凡例非表示
                title=f"{sheet} - {level_select} スキルカテゴリ達成率（レーダーチャート）"
            )

            #streamlit上に表示
            st.plotly_chart(fig, use_container_width=True)




            # --- 3. 達成状況を表形式で表示する関数
        def draw_summary_table(df_sheet, sheet , level_select):
            #データが空の場合は処理せずにメッセージ表示
            if df_sheet.empty:
                st.info("対象データがありません")
                return
            
            #スキルカテゴリごとの達成件数と総件数を集計
            achieved_count = df_sheet[df_sheet["achieved"]==True]["スキルカテゴリ"].value_counts()
            total_count = df_sheet["スキルカテゴリ"].value_counts()

            #DataFram化して列を整形
            summary_df = pd.DataFrame({
                "達成件数" : achieved_count,
                "合計件数" : total_count
            }).fillna(0).astype(int) # NaNを0日間して整数型に

            #達成・合計の文字列を追加
            summary_df["達成/合計"] = summary_df["達成件数"].astype(str) + "/" + summary_df["合計件数"].astype(str)

            #Streamlitで表を表示
            st.markdown(f"##### {sheet} - {level_select} 達成状況")
            st.dataframe(summary_df[["達成/合計"]])


        # --- 実行 ---
        df_sheet = load_filtered_sheet(st.session_state.user_id, selected_sheet, level_select)
        col1, col2 = st.columns([4, 6])
        with col1:
            skill_pie_cart(df_sheet, selected_sheet, level_select)
        with col2:
            skill_radar_chart(df_sheet, selected_sheet, level_select)
        st.markdown("---")
        draw_summary_table(df_sheet, selected_sheet, level_select)

        st.markdown("---")
        st.markdown(
            """
        出典先：情報処理推進機構(IPA)「データサイエンティスト スキルチェックシート  Ver5.00」
        © IPA — 本アプリはIPAの公開資料をもとに作成したものであり、  非営利・教育目的での利用のみを目的としています。
"""
        )
