import streamlit as st
from py3dbp import Packer, Bin, Item
import plotly.graph_objects as go
import numpy as np
from decimal import Decimal
import json 
import streamlit.components.v1 as components
import base64
import os
import urllib.request
import math

# ---------------------------------------------------------
# 🚨 [몽키 패치] Decimal 타입 충돌 에러 해결
# ---------------------------------------------------------
if not hasattr(Item, 'original_get_dimension'):
    Item.original_get_dimension = Item.get_dimension

def custom_get_dimension(self):
    if getattr(self, 'force_upright', False):
        if self.rotation_type not in [0, 3]:
            return [Decimal('9999999.0'), Decimal('9999999.0'), Decimal('9999999.0')]
    return self.original_get_dimension()

Item.get_dimension = custom_get_dimension
# ---------------------------------------------------------

TRUCK_SPECS = {
    "1톤 윙바디": {"w": 1600, "h": 1600, "d": 2800, "max_w": 1000},
    "2.5톤 윙바디": {"w": 2000, "h": 2000, "d": 4300, "max_w": 2500},
    "5톤 윙바디 (축차/플러스)": {"w": 2400, "h": 2400, "d": 8500, "max_w": 5000},
    "11톤 윙바디": {"w": 2400, "h": 2500, "d": 10200, "max_w": 11000},
    "25톤 윙바디": {"w": 2400, "h": 2500, "d": 10200, "max_w": 25000},
}

PALLET_W = 1100; PALLET_D = 1100; PALLET_H = 150

def apply_physics_engine(bin_data, min_support_ratio=0.7):
    if not bin_data.items: return []
    sorted_items = sorted(bin_data.items, key=lambda i: float(i.position[1]))
    dropped_boxes = []; stable_items = []; rejected_items = []
    for item in sorted_items:
        x, y, z = map(float, item.position)
        w, h, d = map(float, item.get_dimension()) 
        max_floor_y = 0.0
        for dx, dy, dz, dw, dh, dd in dropped_boxes:
            overlap_x = not (x + w <= dx or x >= dx + dw)
            overlap_z = not (z + d <= dz or z >= dz + dd)
            if overlap_x and overlap_z:
                if dy + dh > max_floor_y: max_floor_y = dy + dh
        support_area = 0.0
        if max_floor_y == 0.0: support_area = w * d 
        else:
            for dx, dy, dz, dw, dh, dd in dropped_boxes:
                if abs((dy + dh) - max_floor_y) < 1.0:
                    ix_start = max(x, dx); ix_end = min(x + w, dx + dw)
                    iz_start = max(z, dz); iz_end = min(z + d, dz + dd)
                    if ix_start < ix_end and iz_start < iz_end:
                        support_area += (ix_end - ix_start) * (iz_end - iz_start)
        support_ratio = support_area / (w * d)
        if support_ratio >= min_support_ratio:
            item.position = [x, max_floor_y, z]
            dropped_boxes.append((x, max_floor_y, z, w, h, d))
            stable_items.append(item)
        else: rejected_items.append(item)
    bin_data.items = stable_items
    return rejected_items

def calculate_center_of_gravity(bin_items):
    total_weight = sum([float(item.weight) for item in bin_items])
    if total_weight == 0: return 0, 0, 0, 0
    cg_x = sum([float(item.weight) * (float(item.position[0]) + float(item.width)/2) for item in bin_items]) / total_weight
    cg_y = sum([float(item.weight) * (float(item.position[1]) + float(item.height)/2) for item in bin_items]) / total_weight
    cg_z = sum([float(item.weight) * (float(item.position[2]) + float(item.depth)/2) for item in bin_items]) / total_weight
    return cg_x, cg_y, cg_z, total_weight

def get_base64_image(image_path, fallback_url=None):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            encoded = base64.b64encode(img_file.read()).decode()
            ext = os.path.splitext(image_path)[1].lower()
            mime = "image/jpeg" if ext in ['.jpg', '.jpeg'] else "image/png"
            return f"data:{mime};base64,{encoded}"
    elif fallback_url:
        try:
            req = urllib.request.Request(fallback_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                encoded = base64.b64encode(response.read()).decode()
                return f"data:image/png;base64,{encoded}"
        except: pass
    return None

def export_to_json(bin_data, truck_w, truck_h, truck_d, use_pallet=False):
    items_data = []
    color_map = {'A형': '#FF4B4B', 'B형': '#FF9020'}
    color_hex = {'A형': 'FF4B4B', 'B형': 'FF9020'}
    
    textures_base64 = {}
    for bt in ['A형', 'B형']:
        ch = color_hex[bt]
        bt_eng = bt[:1]
        textures_base64[bt] = {
            'front': get_base64_image(f'textures/box_{bt_eng}_front.jpg', f'https://placehold.co/256x256/{ch}/FFF?text={bt_eng}-FRONT'),
            'side': get_base64_image(f'textures/box_{bt_eng}_side.jpg', f'https://placehold.co/256x256/{ch}/FFF?text={bt_eng}-SIDE'),
            'top': get_base64_image(f'textures/box_{bt_eng}_top.jpg', f'https://placehold.co/256x256/{ch}/FFF?text={bt_eng}-TOP')
        }
    
    truck_bg_b64 = get_base64_image('textures/truck_bg.jpg')

    for item in bin_data.items:
        if not item.position: continue
        w, h, d = map(float, item.get_dimension())
        x, y, z = map(float, item.position)
        item_type = item.name.split('_')[0]
        
        items_data.append({
            "name": item.name, "type": item_type,
            "w": w, "h": h, "d": d,
            "x": x, "y": y, "z": z,
            "color": color_map.get(item_type, '#00FFFF')
        })
        
    return json.dumps({
        "truck": {"w": float(truck_w), "h": float(truck_h), "d": float(truck_d)},
        "items": items_data,
        "textures": textures_base64,
        "truck_bg": truck_bg_b64,
        "use_pallet": use_pallet,
        "pallet_w": PALLET_W,
        "pallet_h": PALLET_H,
        "pallet_d": PALLET_D
    })

# =========================================================================
# 🌟 [UI 개편] Streamlit 웹페이지 디자인
# =========================================================================

st.set_page_config(layout="wide", page_title="3D 화물 적재 시뮬레이터", page_icon="🚛")

# 헤더 영역
st.title("🚛 3D 화물 적재 시뮬레이터")
st.markdown("효율적인 적재 방식의 3D 화물 적재 시뮬레이션 입니다.") 
st.divider()

# 사이드바 대신 메인 탭(Tabs)을 사용하여 넓고 쾌적한 입력창 구성
tab1, tab2, tab3 = st.tabs(["🚛 1. 차량 선택", "📦 2. 화물 입력", "⚙️ 3. 고급 옵션"])

with tab1:
    st.subheader("어떤 화물차에 짐을 싣나요?")
    col1, col2 = st.columns([1, 1])
    
    with col1:
        template_choice = st.selectbox("📌 자주 쓰는 차량 프리셋", list(TRUCK_SPECS.keys()), index=3)
        use_pallet = st.toggle("🪵 파렛트(1100x1100) 및 랩핑 사용", value=True)
        prevent_mixed = use_pallet # 현업 팔레타이징 로직 자동 연동

    with col2:
        st.markdown("**세부 제원 (mm)**")
        c1, c2 = st.columns(2)
        custom_w = c1.number_input("폭 (가로)", value=TRUCK_SPECS[template_choice]["w"])
        custom_h = c2.number_input("높이 (세로)", value=TRUCK_SPECS[template_choice]["h"])
        c3, c4 = st.columns(2)
        custom_d = c3.number_input("길이 (적재함 깊이)", value=TRUCK_SPECS[template_choice]["d"])
        custom_max_w = c4.number_input("최대 하중 (kg)", value=TRUCK_SPECS[template_choice]["max_w"])

box_configs = {}
with tab2:
    st.subheader("싣고자 하는 상자의 규격과 수량을 적어주세요.")
    
    # 🌟 추가된 설명 안내 문구
    st.info("💡 **안내:** 더 튼튼하고 큰 짐이 밑으로 깔려야 하므로, 보이지 않는 내부 계산 엔진은 큰 **B형 화물부터 먼저 싣도록 최적화**되어 있습니다. 따라서 시뮬레이션 결과에서는 **항상 B형 화물이 바닥에 깔리고, A형 화물은 그 위에 올라가게 됩니다.**")
    st.markdown("<br>", unsafe_allow_html=True)
    
    # 🌟 A형 먼저, 그다음 B형 출력 (UI 순서 변경 유지)
    box_defaults = {
        'A형': {"color": "🟥"},
        'B형': {"color": "🟧"}
    }
    
    for k, v in box_defaults.items():
        st.markdown(f"#### {v['color']} {k} 화물")
        col1, col2, col3, col4, col5 = st.columns(5)
        # 기본값을 0으로 깔끔하게 비워둠
        cnt = col1.number_input("📦 수량 (개)", min_value=0, value=0, key=f"cnt_{k}")
        w = col2.number_input("가로 (W)", min_value=0, value=0, key=f"w_{k}")
        d = col3.number_input("세로 (D)", min_value=0, value=0, key=f"d_{k}")
        h = col4.number_input("높이 (H)", min_value=0, value=0, key=f"h_{k}")
        wt = col5.number_input("무게 (kg)", min_value=0, value=0, key=f"wt_{k}")
        box_configs[k] = {"w": w, "h": h, "d": d, "wt": wt, "cnt": cnt}
        st.write("") # 간격 띄우기

with tab3:
    st.subheader("전문가용 상세 설정")
    # 🌟 높이 정렬 문제 해결: 토글을 위로 빼고 슬라이더 두 개를 나란히 배치
    force_upright = st.toggle("⬆️ 세워서 적재 강제 (박스 눕힘 방지)", value=True)
    st.markdown("<br>", unsafe_allow_html=True) # 약간의 여백 추가
    
    col1, col2 = st.columns(2)
    with col1:
        min_support = st.slider("⚖️ 안전 지지율 (%)", 10, 100, 70, help="아래 상자가 위 상자를 지탱하는 최소 면적 비율입니다. (너무 낮으면 무너짐)")
    with col2:
        clearance = st.slider("🚜 지게차 상하차 유격 (mm)", 0, 200, 100, help="파렛트 작업 시 지게차 발이 들어갈 여유 공간(천장 여백)을 뺍니다.")

st.divider()

# 시뮬레이션 가동 버튼을 눈에 띄게 큰 버튼으로 배치
col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
with col_btn2:
    run_btn = st.button("🚀 최적화 시뮬레이션 시작", type="primary", use_container_width=True)

# =========================================================================
# 🌟 물리 엔진 및 시뮬레이션 결과 렌더링
# =========================================================================

if run_btn:
    # 에러 방지: 화물 수량이 모두 0이면 경고창 띄우기
    if box_configs['A형']['cnt'] == 0 and box_configs['B형']['cnt'] == 0:
        st.warning("🚨 실을 화물이 없습니다! 화물 세팅 탭에서 상자의 수량을 1개 이상 입력해주세요.")
    else:
        with st.spinner('AI가 가장 효율적인 적재 방식을 계산하고 있습니다... ⏳'):
            packer = Packer()
            actual_calc_h = custom_h - PALLET_H - clearance if use_pallet else custom_h
            
            if use_pallet:
                usable_w = (custom_w // PALLET_W) * PALLET_W 
                usable_d = (custom_d // PALLET_D) * PALLET_D
                packer.add_bin(Bin("차량", usable_w, actual_calc_h, usable_d, custom_max_w))
            else:
                packer.add_bin(Bin("차량", custom_w, custom_h, custom_d, custom_max_w))
            
            virtual_items_meta = {}

            # 🚨 물리 엔진은 B형(큰 짐)을 먼저 쌓도록 순서 고정 (안전성 및 무게중심 최적화)
            for bt in ['B형', 'A형']:
                cfg = box_configs[bt]
                cnt = cfg["cnt"]
                if cnt == 0: continue
                
                w, h, d, wt = float(cfg["w"]), float(cfg["h"]), float(cfg["d"]), float(cfg["wt"])

                if use_pallet and prevent_mixed:
                    nx = int(PALLET_W // w)
                    nz = int(PALLET_D // d)
                    cap1 = nx * nz

                    nx_rot = int(PALLET_W // d)
                    nz_rot = int(PALLET_D // w)
                    cap2 = nx_rot * nz_rot

                    if cap2 > cap1:
                        nx, nz = nx_rot, nz_rot
                        w, d = d, w 

                    items_per_layer = nx * nz
                    if items_per_layer == 0: continue

                    max_layers = int(actual_calc_h // h)
                    if max_layers == 0: continue

                    max_items_per_pallet = items_per_layer * max_layers
                    remaining = cnt
                    block_id = 1

                    while remaining > 0:
                        current_items = min(remaining, max_items_per_pallet)
                        b_name = f"{bt}_PalletCol_{block_id}"

                        block_weight = wt * current_items
                        item = Item(b_name, PALLET_W, actual_calc_h, PALLET_D, block_weight)
                        item.force_upright = True 
                        packer.add_item(item)

                        virtual_items_meta[b_name] = {
                            "nx": nx, "nz": nz, "w": w, "h": h, "d": d,
                            "total_items": current_items, "base_name": bt
                        }

                        remaining -= current_items
                        block_id += 1

                else:
                    for i in range(cnt):
                        item = Item(f'{bt}_{i+1}', w, h, d, wt)
                        item.force_upright = force_upright
                        packer.add_item(item)
                    
            packer.pack()
            b = packer.bins[0]
            
            rejected = apply_physics_engine(b, min_support_ratio=(min_support/100.0))

            def unpack_virtual_blocks(bin_items, virtual_meta):
                unpacked_items = []
                for item in bin_items:
                    if item.name in virtual_meta:
                        meta = virtual_meta[item.name]
                        nx, nz = meta["nx"], meta["nz"]
                        orig_w, orig_h, orig_d = meta["w"], meta["h"], meta["d"]
                        total_items = meta["total_items"]
                        base_name = meta["base_name"]

                        bx, by, bz = map(float, item.position)
                        
                        offset_x = (PALLET_W - (nx * orig_w)) / 2.0
                        offset_z = (PALLET_D - (nz * orig_d)) / 2.0

                        count = 0
                        layer = 0

                        while count < total_items:
                            for ix in range(nx):
                                for iz in range(nz):
                                    if count >= total_items: break

                                    sub_x = bx + offset_x + (ix * orig_w)
                                    sub_y = by + (layer * orig_h)
                                    sub_z = bz + offset_z + (iz * orig_d)

                                    sub_item = Item(f"{base_name}_{item.name}_{count+1}", orig_w, orig_h, orig_d, float(item.weight) / total_items)
                                    sub_item.position = [sub_x, sub_y, sub_z]
                                    sub_item.rotation_type = 0 
                                    unpacked_items.append(sub_item)
                                    count += 1
                            layer += 1
                    else:
                        unpacked_items.append(item)
                return unpacked_items

            if use_pallet and prevent_mixed:
                b.items = unpack_virtual_blocks(b.items, virtual_items_meta)

            cg_x, cg_y, cg_z, total_wt = calculate_center_of_gravity(b.items)
            
            # --- 결과 표시 ---
            st.success("✅ 시뮬레이션 계산이 완료되었습니다!")
            st.subheader("📊 시뮬레이션 리포트")
            
            # 지표 디자인 개선
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("📦 적재된 상자", f"{len(b.items)} 개", f"{sum([cfg['cnt'] for cfg in box_configs.values()])}개 중")
            col2.metric("📉 공간 활용률", f"{(sum([float(i.width)*float(i.height)*float(i.depth) for i in b.items]) / (custom_w*custom_h*custom_d)*100):.1f} %")
            col3.metric("⚖️ 하중 밸런스 점수", f"{100 - abs(custom_d/2 - cg_z)/custom_d*100:.1f} 점")
            col4.metric("🏋️ 총 중량", f"{total_wt:,.0f} kg", f"최대 {custom_max_w:,.0f}kg")
            
            st.markdown("### 🚛 3D 시뮬레이션 화면")
            st.caption("마우스 좌클릭(회전), 우클릭(이동), 휠(확대/축소)을 통해 다각도에서 확인하세요.")
            
            json_data = export_to_json(b, custom_w, custom_h, custom_d, use_pallet)
            try:
                with open("viewer.html", "r", encoding="utf-8") as f:
                    html_template = f.read()
                rendered_html = html_template.replace("{{INJECT_JSON_DATA}}", json_data)
                components.html(rendered_html, height=750)
            except FileNotFoundError:
                st.error("🚨 `viewer.html` 파일을 찾을 수 없습니다.")