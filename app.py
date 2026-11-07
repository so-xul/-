
import re
import requests
import pandas as pd
import streamlit as st


# =========================================================
# 1. 기본 설정
# =========================================================

st.set_page_config(
    page_title="우리 동네 학원 찾기",
    page_icon="📚",
    layout="wide"
)

NEIS_ACADEMY_URL = (
    "https://open.neis.go.kr/hub/acaInsTiInfo"
)

REGIONS = {
    "서울특별시": "B10",
    "부산광역시": "C10",
    "대구광역시": "D10",
    "인천광역시": "E10",
    "광주광역시": "F10",
    "대전광역시": "G10",
    "울산광역시": "H10",
    "세종특별자치시": "I10",
    "경기도": "J10",
    "강원특별자치도": "K10",
    "충청북도": "M10",
    "충청남도": "N10",
    "전북특별자치도": "P10",
    "전라남도": "Q10",
    "경상북도": "R10",
    "경상남도": "S10",
    "제주특별자치도": "T10",
}

PAGE_SIZE = 1000
MAX_PAGES = 100

HEADERS = {
    "User-Agent": "AcademyFinder/1.0"
}


# =========================================================
# 2. API 키 확인
# =========================================================

def get_secret(name):

    try:
        return str(st.secrets[name]).strip()

    except Exception:
        return ""


NEIS_KEY = get_secret("NEIS_API_KEY")


# =========================================================
# 3. 공통 API 요청 함수
# =========================================================

def request_json(url, params=None):

    try:

        response = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=30
        )

        response.raise_for_status()

        return response.json()

    except requests.Timeout:

        raise RuntimeError(
            "나이스 API 응답 시간이 초과되었습니다."
        )

    except requests.HTTPError as e:

        detail = ""

        if e.response is not None:
            detail = e.response.text[:1000]

        raise RuntimeError(
            f"HTTP 오류: {e}\n{detail}"
        )

    except requests.RequestException as e:

        raise RuntimeError(
            f"네트워크 오류: {e}"
        )

    except ValueError:

        raise RuntimeError(
            "API 응답을 JSON으로 변환하지 못했습니다."
        )


# =========================================================
# 4. 나이스 학원 데이터 수집
# =========================================================

@st.cache_data(ttl=3600)
def fetch_academies(region_code):

    all_rows = []

    page = 1
    page_logs = []
    last_status = "응답 확인 중"
    reached_limit = False

    while page <= MAX_PAGES:

        params = {
            "KEY": NEIS_KEY,
            "Type": "json",
            "pIndex": page,
            "pSize": PAGE_SIZE,
            "ATPT_OFCDC_SC_CODE": region_code
        }

        data = request_json(
            NEIS_ACADEMY_URL,
            params=params
        )

        blocks = data.get("acaInsTiInfo", [])

        if not blocks:

            result = data.get("RESULT", {})

            code = result.get("CODE", "")
            message = result.get("MESSAGE", "")

            last_status = code or "응답 데이터 없음"

            if code == "INFO-200":
                page_logs.append(
                    "조회 결과 데이터가 없습니다."
                )
                break

            if result:
                raise RuntimeError(
                    f"나이스 API 오류: {code} / {message}"
                )

            break

        rows = []

        for block in blocks:

            if isinstance(block, dict):
                rows.extend(block.get("row", []))

        if not rows:
            break

        all_rows.extend(rows)

        page_logs.append(
            f"{page}페이지: {len(rows):,}건"
        )

        last_status = "정상 수집"

        if len(rows) < PAGE_SIZE:
            break

        page += 1

    else:
        reached_limit = True

    raw = pd.DataFrame(all_rows)

    diagnostics = {
        "API 상태": last_status,
        "수집 페이지": len(page_logs),
        "원본 수집 건수": len(raw),
        "페이지별 수집 내역": page_logs,
        "최대 페이지 도달": reached_limit,
        "원본 필드": list(raw.columns)
    }

    return raw, diagnostics


# =========================================================
# 5. 데이터 값 추출
# =========================================================

def get_value(row, keys):

    for key in keys:

        value = row.get(key)

        if value is None:
            continue

        if pd.notna(value):

            value = str(value).strip()

            if value and value.lower() != "nan":
                return value

    return ""


# =========================================================
# 6. 주소에서 시·군·구 추출
# =========================================================

def extract_sigungu(address):

    if not address:
        return ""

    address = str(address).strip()

    patterns = [
        r"([가-힣]+시\s*[가-힣]+구)",
        r"([가-힣]+시)",
        r"([가-힣]+군)",
        r"([가-힣]+구)"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            address
        )

        if match:

            return re.sub(
                r"\s+",
                " ",
                match.group(1)
            ).strip()

    return ""


def normalize_text(value):

    if value is None:
        return ""

    return re.sub(
        r"\s+",
        "",
        str(value).strip()
    )


# =========================================================
# 7. 학원 데이터 정리
# =========================================================

def normalize_academies(raw):

    columns = [
        "학원명",
        "시군구",
        "주소",
        "전화번호",
        "교습분야",
        "교습과정"
    ]

    records = []

    for _, row in raw.iterrows():

        name = get_value(
            row,
            ["ACA_NM", "INST_NM"]
        )

        address = get_value(
            row,
            [
                "FA_RDNMA",
                "FA_ADDR",
                "ROAD_NM_ADDR",
                "ADDR",
                "FA_RDNDA"
            ]
        )

        detail_address = get_value(
            row,
            ["FA_RDNDA"]
        )

        admin_name = get_value(
            row,
            [
                "ADMST_ZONE_NM",
                "SIGNGU_NM",
                "SGG_NM"
            ]
        )

        # 주소를 기준으로 시군구 추출
        sigungu = extract_sigungu(address)

        if not sigungu:
            sigungu = extract_sigungu(
                detail_address
            )

        if not sigungu:
            sigungu = extract_sigungu(
                admin_name
            )

        if not sigungu and re.fullmatch(
            r"[가-힣]+(시|군|구)",
            admin_name
        ):
            sigungu = admin_name

        if not name or not address:
            continue

        records.append({

            "학원명": name,
            "시군구": sigungu,
            "주소": address,

            "전화번호": get_value(
                row,
                [
                    "FA_TELNO",
                    "TELNO",
                    "TEL_NO"
                ]
            ),

            "교습분야": get_value(
                row,
                [
                    "REALM_SC_NM",
                    "TRN_SC_NM",
                    "REALM_NM"
                ]
            ),

            "교습과정": get_value(
                row,
                [
                    "LE_CRSE_NM",
                    "CRSE_NM"
                ]
            )

        })

    df = pd.DataFrame(
        records,
        columns=columns
    )

    if df.empty:
        return df

    df = df.drop_duplicates(
        subset=["학원명", "주소"]
    )

    return df.reset_index(drop=True)


# =========================================================
# 8. 학원 데이터 불러오기
# =========================================================

@st.cache_data(ttl=3600)
def load_academies(region_code):

    raw, diagnostics = fetch_academies(
        region_code
    )

    academies = normalize_academies(raw)

    return raw, academies, diagnostics


# =========================================================
# 9. 과목 목록 추출
# =========================================================

def get_subjects(df):

    subjects = set()

    for column in [
        "교습분야",
        "교습과정"
    ]:

        for value in df[column].dropna():

            parts = re.split(
                r"[,/·ㆍ|]",
                str(value)
            )

            for part in parts:

                part = part.strip()

                if part:
                    subjects.add(part)

    return sorted(subjects)


# =========================================================
# 10. 시·군·구 목록 추출
# =========================================================

def get_districts(df):

    districts = set()

    for value in df["시군구"].dropna():

        value = str(value).strip()

        if value:
            districts.add(value)

    return sorted(districts)


# =========================================================
# 11. 화면 제목
# =========================================================

st.title("📚 우리 동네 학원 찾기")

st.caption(
    "원하는 지역과 과목을 선택하여 학원을 검색해 보세요."
)


# =========================================================
# 12. API 키 확인
# =========================================================

if not NEIS_KEY:

    st.error(
        "NEIS_API_KEY를 secrets.toml에서 확인해 주세요."
    )

    st.stop()


# =========================================================
# 13. 시·도 선택
# =========================================================

with st.sidebar:

    st.header("🔎 검색 조건")

    region_name = st.selectbox(
        "시·도",
        list(REGIONS.keys())
    )

region_code = REGIONS[region_name]


# =========================================================
# 14. 학원 데이터 수집
# =========================================================

try:

    with st.spinner(
        f"{region_name} 학원 데이터를 불러오는 중..."
    ):

        raw_academies, academies, api_diagnostics = (
            load_academies(region_code)
        )

except Exception as e:

    st.error(
        f"학원 데이터 수집 실패: {e}"
    )

    st.stop()


# =========================================================
# 15. 데이터 수집 현황
# =========================================================

st.subheader("📊 데이터 수집 현황")

col1, col2, col3 = st.columns(3)

col1.metric(
    "API 원본 수집",
    f"{api_diagnostics['원본 수집 건수']:,}건"
)

col2.metric(
    "정리된 학원",
    f"{len(academies):,}곳"
)

col3.metric(
    "지역 확인 가능",
    f"{(academies['시군구'] != '').sum():,}곳"
)


# =========================================================
# 16. 시·군·구 목록 만들기
# =========================================================

districts = get_districts(
    academies
)

if not districts:

    st.error(
        "학원 데이터에서 시·군·구를 추출하지 못했습니다."
    )

    st.info(
        "상세 데이터 진단에서 주소 필드와 실제 데이터를 확인해 주세요."
    )

    with st.expander("데이터 진단"):

        st.write(api_diagnostics)

        st.write(
            api_diagnostics["원본 필드"]
        )

        st.dataframe(
            raw_academies.head(20),
            use_container_width=True
        )

    st.stop()


# =========================================================
# 17. 과목 목록 만들기
# =========================================================

subjects = get_subjects(
    academies
)


# =========================================================
# 18. 검색 조건 입력
# =========================================================

with st.sidebar:

    selected_sigungu = st.selectbox(
        "시·군·구",
        districts
    )

    selected_subject = st.selectbox(
        "과목",
        ["전체"] + subjects
    )

    academy_name = st.text_input(
        "학원명",
        placeholder="학원 이름을 입력하세요 (선택)"
    )

    search_clicked = st.button(
        "🔍 학원 검색",
        use_container_width=True,
        type="primary"
    )


# =========================================================
# 19. 검색 조건 저장
# =========================================================

if "search_snapshot" not in st.session_state:

    st.session_state.search_snapshot = None


if search_clicked:

    st.session_state.search_snapshot = {

        "region": region_name,
        "sigungu": selected_sigungu,
        "subject": selected_subject,
        "academy_name": academy_name.strip()

    }


# =========================================================
# 20. 검색 전 안내
# =========================================================

search = st.session_state.search_snapshot

if search is None:

    st.info(
        "왼쪽에서 검색 조건을 선택하고 "
        "'학원 검색' 버튼을 눌러 주세요."
    )

    st.stop()


# =========================================================
# 21. 검색 조건 변경 확인
# =========================================================

current_conditions = (

    search["region"] == region_name

    and search["sigungu"] == selected_sigungu

    and search["subject"] == selected_subject

    and search["academy_name"] == academy_name.strip()

)

if not current_conditions:

    st.info(
        "검색 조건이 변경되었습니다. "
        "새로운 조건으로 다시 검색해 주세요."
    )

    st.stop()


# =========================================================
# 22. 단계별 데이터 필터링
# =========================================================

# ① 전체 데이터
step_all = academies.copy()


# ② 지역 필터
step_region = step_all[
    step_all["시군구"].apply(
        lambda x: (
            normalize_text(x)
            == normalize_text(search["sigungu"])
        )
    )
].copy()


# ③ 과목 필터
if search["subject"] == "전체":

    step_subject = step_region.copy()

else:

    subject_mask = (

        step_region["교습분야"].str.contains(
            search["subject"],
            case=False,
            na=False,
            regex=False
        )

        |

        step_region["교습과정"].str.contains(
            search["subject"],
            case=False,
            na=False,
            regex=False
        )

    )

    step_subject = step_region[
        subject_mask
    ].copy()


# ④ 학원명 필터
if search["academy_name"]:

    filtered = step_subject[
        step_subject["학원명"].str.contains(
            search["academy_name"],
            case=False,
            na=False,
            regex=False
        )
    ].copy()

else:

    filtered = step_subject.copy()


# =========================================================
# 23. 학원명 가나다순 정렬
# =========================================================

filtered = filtered.sort_values(
    by="학원명",
    ascending=True,
    kind="stable"
).reset_index(drop=True)


# =========================================================
# 24. 검색 조건 표시
# =========================================================

st.divider()

st.subheader("🔍 검색 결과")

st.write(
    f"**검색 지역:** {search['region']} {search['sigungu']}"
)

st.write(
    f"**과목:** {search['subject']}"
)

if search["academy_name"]:

    st.write(
        f"**학원명 검색어:** {search['academy_name']}"
    )


# =========================================================
# 25. 단계별 데이터 개수
# =========================================================

st.markdown("### 📈 검색 데이터 분석")

diagnostic_data = pd.DataFrame({

    "필터 단계": [
        "전체 수집 데이터",
        "지역 필터 적용",
        "과목 필터 적용",
        "학원명 필터 적용"
    ],

    "학원 수": [
        len(step_all),
        len(step_region),
        len(step_subject),
        len(filtered)
    ]

})

st.dataframe(
    diagnostic_data,
    use_container_width=True,
    hide_index=True
)


# =========================================================
# 26. 최종 검색 결과
# =========================================================

st.markdown("### 🏫 학원 목록")

st.metric(
    "최종 검색 결과",
    f"{len(filtered):,}곳"
)

if filtered.empty:

    st.warning(
        "조건에 맞는 학원이 없습니다."
    )

    if step_region.empty:

        st.info(
            "지역 필터 단계에서 검색 결과가 없습니다. "
            "주소에서 시·군·구를 추출한 방식과 실제 주소를 확인해 주세요."
        )

    elif step_subject.empty:

        st.info(
            "선택한 지역에는 학원이 있지만 "
            "해당 과목과 일치하는 데이터가 없습니다."
        )

    elif not step_subject.empty:

        st.info(
            "지역과 과목에는 일치하는 학원이 있지만 "
            "입력한 학원명과 일치하는 결과가 없습니다."
        )

else:

    st.dataframe(
        filtered[
            [
                "학원명",
                "주소",
                "교습분야",
                "교습과정",
                "전화번호"
            ]
        ],
        use_container_width=True,
        hide_index=True
    )

    # CSV 다운로드
    csv_data = filtered[
        [
            "학원명",
            "주소",
            "교습분야",
            "교습과정",
            "전화번호"
        ]
    ].to_csv(
        index=False,
        encoding="utf-8-sig"
    )

    st.download_button(
        "📥 검색 결과 CSV 다운로드",
        data=csv_data,
        file_name="우리동네_학원검색.csv",
        mime="text/csv"
    )


# =========================================================
# 27. 상세 데이터 진단
# =========================================================

with st.expander("🛠️ 상세 데이터 진단"):

    st.markdown("#### API 수집 상태")

    st.write(
        f"API 상태: {api_diagnostics['API 상태']}"
    )

    st.write(
        f"수집 페이지: {api_diagnostics['수집 페이지']}"
    )

    st.write(
        f"원본 데이터: {api_diagnostics['원본 수집 건수']:,}건"
    )

    st.write(
        f"최대 페이지 도달 여부: {api_diagnostics['최대 페이지 도달']}"
    )

    if api_diagnostics["최대 페이지 도달"]:

        st.warning(
            "최대 페이지 수에 도달했습니다. "
            "데이터가 모두 수집되지 않았을 가능성이 있습니다."
        )

    st.markdown("#### 페이지별 수집 내역")

    st.write(
        api_diagnostics["페이지별 수집 내역"]
    )

    st.markdown("#### API 원본 필드")

    st.write(
        api_diagnostics["원본 필드"]
    )

    st.markdown("#### 원본 데이터 표본")

    if not raw_academies.empty:

        st.dataframe(
            raw_academies.head(20),
            use_container_width=True
        )

    st.markdown("#### 시·군·구 추출 실패 데이터")

    missing_region = academies[
        academies["시군구"] == ""
    ]

    st.write(
        f"지역 추출 실패: {len(missing_region)}건"
    )

    if not missing_region.empty:

        st.dataframe(
            missing_region[
                ["학원명", "주소"]
            ].head(30),
            use_container_width=True,
            hide_index=True
        )

    st.markdown("#### 교습분야 실제 값")

    realm_values = (
        academies["교습분야"]
        .value_counts(dropna=False)
        .head(50)
        .reset_index()
    )

    realm_values.columns = [
        "교습분야",
        "데이터 수"
    ]

    st.dataframe(
        realm_values,
        use_container_width=True,
        hide_index=True
    )

    st.markdown("#### 교습과정 실제 값")

    course_values = (
        academies["교습과정"]
        .value_counts(dropna=False)
        .head(50)
        .reset_index()
    )

    course_values.columns = [
        "교습과정",
        "데이터 수"
    ]

    st.dataframe(
        course_values,
        use_container_width=True,
        hide_index=True
    )
