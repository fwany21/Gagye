import streamlit as st
from openai import OpenAI
import base64
import json
from pymongo.mongo_client import MongoClient
from PIL import Image
import io
from datetime import datetime
from pymongo.server_api import ServerApi
import pandas as pd

# 페이지 설정
st.set_page_config(
    page_title="제품 가격표 분석 및 검색",
    layout="centered",
    initial_sidebar_state="expanded",
)

# --- 사용자 인증: passcode 입력 ---
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

# passcode 입력 폼을 담을 placeholder 생성
passcode_placeholder = st.empty()

if not st.session_state["authenticated"]:
    with passcode_placeholder.form("passcode_form", clear_on_submit=True):
        passcode_input = st.text_input("Passcode 입력", type="password", placeholder="비밀번호를 입력하세요")
        submit_button = st.form_submit_button("제출")
        if submit_button:
            if passcode_input == st.secrets["PASSCODE"]:
                st.session_state["authenticated"] = True
            else:
                st.error("잘못된 passcode입니다.")
    if not st.session_state["authenticated"]:
        st.stop()
    else:
        # 인증 성공 시 passcode 폼 숨기기
        passcode_placeholder.empty()

# --- MongoDB 연결 및 설정 ---
MONGO_URI = st.secrets["MONGO_URI"]
client = MongoClient(MONGO_URI, server_api=ServerApi('1'))
try:
    client.admin.command('ping')
    st.info("MongoDB 연결 성공!")
except Exception as e:
    st.error(f"MongoDB 연결 오류: {e}")

db = client["price_db"]
collection = db["products"]

# 초기 인덱스 설정 (최초 실행 시)
if "product_name_text" not in collection.index_information():
    collection.create_index([("product_name", "text")])

# --- OpenAI Client 설정 ---
API_KEY = st.secrets["API_KEY"]
openai_client = OpenAI(api_key=API_KEY)

# --- 이미지 인코딩 함수 ---
def encode_image(image_bytes, target_size_kb=150):
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    quality = 95
    while True:
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=quality)
        compressed_image_bytes = output.getvalue()
        size_kb = len(compressed_image_bytes) / 1024
        if size_kb <= target_size_kb or quality <= 5:
            break
        quality -= 5
    return base64.b64encode(compressed_image_bytes).decode("utf-8")

# --- GPT-4 Vision을 통한 이미지 분석 함수 ---
def analyze_image(image_bytes):
    try:
        base64_image = encode_image(image_bytes)
        messages = [
            {
                "role": "system",
                "content": f"""
너는 이미지 분석 도우미야. 아래 가격표 이미지에서 
제품명, 가격, 할인 금액, 할인 조건, 할인 가격을 추출해줘. 
할인하지 않는 경우 할인 관련 값은 0으로 표시해.
다음 항목을 JSON 포맷으로 뽑아주세요:
- product_name: 제품명 (string)
- price: 정상가격 (number)
- discount_amount: 할인금액 (없으면 0)
- discount_condition: 할인조건 (없으면 "0")
- discounted_price: 할인적용 후 가격 (없으면 0)

출력 예시는 다음 형태여야 합니다:
{{
  "product_name": "예시상품",
  "price": 20000,
  "discount_amount": 2000,
  "discount_condition": "2+1행사",
  "discounted_price": 18000,
}}

반환하는 JSON은 오직 순수한 JSON 데이터만 포함하고, 어떠한 코드 블록 표시나 추가 텍스트 없이 바로 파싱 가능한 형식이어야 합니다.
할인 정보가 전혀 없다면 discount_amount, discount_condition, discounted_price를 전부 0 또는 "0"으로 처리해주세요.
제품명은 영어보다는 한글을 우선해서 적용해 주세요.
                """,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                    },
                ],
            },
        ]
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini", messages=messages
        )
        result_text = response.choices[0].message.content
        info = json.loads(result_text)
        info["date"] = datetime.today().strftime('%Y-%m-%d')
        return info
    except Exception as e:
        st.error(f"이미지 분석 중 오류 발생: {e}")
        return None

# --- 유사 제품 검색 함수 (텍스트 검색: 자동 검색용) ---
def find_similar_products(product_name):
    similar_docs = list(collection.find({"$text": {"$search": product_name}}))
    return similar_docs

# --- 검색 결과를 보기 좋게 표시하기 위한 함수 ---
def format_search_results(results):
    if not results:
        return None
    
    # 검색 결과를 DataFrame으로 변환
    df = pd.DataFrame(results)
    
    # ObjectId 컬럼 제거
    if '_id' in df.columns:
        df = df.drop('_id', axis=1)
    
    # 컬럼 순서 재정렬
    columns_order = ['date', 'product_name', 'price', 'discount_amount', 'discount_condition', 'discounted_price']
    df = df.reindex(columns=columns_order)
    
    # 컬럼명 한글로 변경
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

# --- 메인 콘텐츠 영역 ---
st.title("제품 가격표 분석")
st.write("카메라로 제품의 가격표를 촬영하여 업로드하세요.")

with st.container():
    uploaded_file = st.file_uploader(
        "가격표 이미지 선택 (jpg, jpeg, png)", type=["jpg", "jpeg", "png"]
    )
    if uploaded_file is not None:
        image = Image.open(uploaded_file)
        st.image(image, caption="업로드된 이미지", use_column_width=True)
        image_bytes_io = io.BytesIO()
        image.save(image_bytes_io, format="PNG")
        image_bytes = image_bytes_io.getvalue()

        with st.spinner("이미지 분석 중..."):
            info = analyze_image(image_bytes)

        if info:
            st.success("이미지 분석 완료!")
            st.subheader("분석 결과")
            with st.expander("분석된 JSON 데이터"):
                st.json(info)

            # 제품 정보 MongoDB 저장
            insert_result = collection.insert_one(info)
            st.info(f"제품 정보 저장 완료 (ID: {insert_result.inserted_id})")

            # 자동 유사 제품 검색 (분석 후 바로 결과 표시)
            similar = find_similar_products(info.get("product_name", ""))
            if similar:
                st.subheader("유사한 제품 이력 (자동 검색)")
                df_similar = format_search_results(similar)
                if df_similar is not None:
                    st.dataframe(df_similar, use_container_width=True)
            else:
                st.info("유사한 제품 이력이 없습니다.")