import streamlit as st
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import pandas as pd
from datetime import datetime

# 페이지 설정
st.set_page_config(
    page_title="제품 검색",
    layout="centered",
    initial_sidebar_state="expanded",
)

# --- MongoDB 연결 ---
MONGO_URI = st.secrets["MONGO_URI"]
client = MongoClient(MONGO_URI, server_api=ServerApi('1'))
db = client["price_db"]
collection = db["products"]

# --- 제품 검색 함수 ---
def find_products_by_name_and_date(product_name, start_date=None, end_date=None):
    query = {}
    if product_name:
        pattern = f".*{product_name}.*"
        query["product_name"] = {"$regex": pattern, "$options": "i"}
    if start_date and end_date:
        query["date"] = {"$gte": start_date, "$lte": end_date}
    elif start_date:
        query["date"] = {"$gte": start_date}
    elif end_date:
        query["date"] = {"$lte": end_date}
    results = collection.find(query)
    return list(results)

# --- 검색 결과 포맷팅 함수 ---
def format_search_results(results):
    if not results:
        return None
    
    df = pd.DataFrame(results)
    
    if '_id' in df.columns:
        df = df.drop('_id', axis=1)
    
    columns_order = ['date', 'product_name', 'price', 'discount_amount', 'discount_condition', 'discounted_price']
    df = df.reindex(columns=columns_order)
    
    column_names = {
        'date': '날짜',
        'product_name': '제품명',
        'price': '정상가격',
        'discount_amount': '할인금액',
        'discount_condition': '할인조건',
        'discounted_price': '할인적용가'
    }
    df = df.rename(columns=column_names)
    
    return df

# --- 검색 실행 함수 ---
def do_search():
    search_term = st.session_state.search_input if 'search_input' in st.session_state else ""
    if 'apply_date_filter' in st.session_state and st.session_state.apply_date_filter:
        start_date_str = st.session_state.start_date.strftime('%Y-%m-%d')
        end_date_str = st.session_state.end_date.strftime('%Y-%m-%d')
    else:
        start_date_str = None
        end_date_str = None

    if search_term or (start_date_str and end_date_str):
        results = find_products_by_name_and_date(search_term, start_date_str, end_date_str)
        if results:
            df = format_search_results(results)
            if df is not None:
                # 검색 결과를 session_state에 저장
                st.session_state.search_results = df
                st.session_state.has_results = True
        else:
            st.session_state.has_results = False
            st.session_state.search_results = None
    else:
        st.session_state.has_results = False
        st.session_state.search_results = None

# --- 검색 UI ---
st.title("제품 검색")

with st.container():
    # Enter 키로 검색 가능한 text_input
    search_name = st.text_input(
        "제품 이름", 
        key="search_input",
        placeholder="예: 예시상품",
        on_change=do_search
    )
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        apply_date_filter = st.checkbox("날짜 필터 적용", key="apply_date_filter")
    
    if apply_date_filter:
        with col2:
            start_date = st.date_input("시작 날짜", value=datetime.today(), key="start_date")
        with col3:
            end_date = st.date_input("종료 날짜", value=datetime.today(), key="end_date")
    
    # 검색 버튼
    if st.button("검색", type="primary", use_container_width=True):
        do_search()

# 검색 결과를 표시할 placeholder 생성
results_placeholder = st.empty()

# 검색 결과 표시
with results_placeholder.container():
    if 'has_results' in st.session_state and st.session_state.has_results:
        st.subheader("검색 결과")
        st.dataframe(st.session_state.search_results, use_container_width=True)
        
        # CSV 다운로드 버튼
        csv = st.session_state.search_results.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="CSV 다운로드",
            data=csv,
            file_name=f"search_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )
    elif 'has_results' in st.session_state and not st.session_state.has_results:
        st.info("검색 결과가 없습니다.")