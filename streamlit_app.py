import streamlit as st
from openai import OpenAI
import base64
import json
from pymongo import MongoClient
from PIL import Image
import io
from datetime import datetime
# --- MongoDB 연결 및 인덱스 설정 ---
MONGO_URI = st.secrets["MONGO_URI"]
client = MongoClient(MONGO_URI)
db = client["price_db"]
collection = db["products"]

# 제품명 필드에 대해 텍스트 인덱스 생성 (최초 실행 시)
if "product_name_text" not in collection.index_information():
    collection.create_index([("product_name", "text")])

# --- OpenAI Client 설정 ---
api_key=st.secrets["api_key"]
openai_client = OpenAI(
    api_key=api_key
)


# --- 이미지 인코딩 함수 ---
def encode_image(image_bytes, target_size_kb=150):
    image = Image.open(io.BytesIO(image_bytes)).convert(
        "RGB"
    )  # 이미지 모드를 RGB로 변환
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
        # 이미지 바이트를 Base64로 인코딩
        base64_image = encode_image(image_bytes)

        # API 요청 메시지 구성
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

반환하는 JSON은 오직 순수한 JSON 데이터만 포함하고, 어떠한 코드 블록 표시(예: ```json)나 추가 텍스트 없이 json.loads로 바로 파싱할 수 있는 형식이어야 합니다.
할인 정보가 전혀 없다면 discount_amount, discount_condition, discounted_price를 전부 0 또는 "0"으로 처리해주세요.
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

        # GPT-4 Vision API 호출
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini", messages=messages
        )

        # 응답에서 메시지 내용 추출
        result_text = response.choices[0].message.content
        # GPT가 JSON 형식의 결과를 반환한다고 가정
        info = json.loads(result_text)
        info["date"] = datetime.today().strftime('%Y-%m-%d')
        return info
    except Exception as e:
        st.error(f"이미지 분석 중 오류 발생: {e}")
        return None


# --- 유사 제품 검색 함수 ---
def find_similar_products(product_name):
    """
    MongoDB에서 제품명이 유사한 기록을 검색합니다.
    """
    similar_docs = list(collection.find({"$text": {"$search": product_name}}))
    return similar_docs


# --- Streamlit UI 구성 ---
st.title("제품 가격표 분석 및 이력 기록")
st.write("카메라로 제품의 가격표를 촬영하세요.")

# 이미지 업로드
uploaded_file = st.file_uploader(
    "제품의 가격표를 촬영하여 업로드하세요.", type=["jpg", "jpeg", "png"]
)

if uploaded_file is not None:
    # 이미지를 화면에 표시
    image = Image.open(uploaded_file)
    st.image(image, caption="업로드된 이미지", use_container_width=True)

    # 이미지를 바이트로 변환
    image_bytes = io.BytesIO()
    image.save(image_bytes, format="PNG")
    image_bytes = image_bytes.getvalue()

    with st.spinner("이미지 분석 중..."):
        info = analyze_image(image_bytes)

    if info:
        st.success("이미지 분석 완료!")
        st.subheader("분석 결과")

        with st.expander("분석된 JSON 데이터"):
            st.json(info)

        # MongoDB에 제품 정보 저장
        insert_result = collection.insert_one(info)
        st.write(f"제품 정보가 저장되었습니다. (ID: {insert_result.inserted_id})")

        # 기존 DB에서 유사한 제품 이력 검색
        similar = find_similar_products(info.get("product_name", ""))
        if similar:
            st.subheader("유사한 제품 이력")
            for doc in similar:
                st.write(doc)
        else:
            st.info("유사한 제품 이력이 없습니다.")