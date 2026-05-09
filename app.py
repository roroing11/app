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
    "1톤 윙바디 (까대기)": {"w": 1600, "h": 1600, "d": 2800, "max_w": 1200},
    "2.5톤 윙바디 (혼합)": {"w": 1900, "h": 2000, "d": 4300, "max_w": 2500},
    "5톤 윙바디 (파렛트)": {"w": 2350, "h": 2400, "d": 7400, "max_w": 5000},
    "11톤 윙바디 (파렛트)": {"w": 2400, "h": 2500, "d": 10200, "max_w": 11000},
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

def export_to_json(bin_data):
    items_data = []
    # 🚨 C, D, E형을 제거하고 A, B형만 남겼습니다.
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
        "truck": {"w": float(bin_data.width), "h": float(bin_data.height), "d": float(bin_data.depth)}, 
        "items": items_data,
        "textures": textures_base64,
        "truck_bg": truck_bg_b64
    })

# =========================================================================
# 🌟 [Streamlit 웹페이지 디자인] 🌟
# =========================================================================

st.set_page_config(layout="wide", page_title="화물차 물류 적재 시뮬레이터")
st.title("🚚 화물차 3D 적재 시뮬레이터")

with st.sidebar:
    st.header("⚙️ 1. 차량 제원")
    template_choice = st.selectbox("템플릿", list(TRUCK_SPECS.keys()), index=2) 
    custom_w = st.number_input("폭 (W, mm)", value=TRUCK_SPECS[template_choice]["w"])
    custom_h = st.number_input("높이 (H, mm)", value=TRUCK_SPECS[template_choice]["h"])
    custom_d = st.number_input("길이 (L, mm)", value=TRUCK_SPECS[template_choice]["d"])
    custom_max_w = st.number_input("최대하중 (kg)", value=TRUCK_SPECS[template_choice]["max_w"])
    use_pallet = st.toggle("🪵 파렛트 & 랩핑 사용", value=True)
    clearance = st.slider("지게차 유격", 0, 200, 100)
    
    st.markdown("---")
    st.header("📦 2. 화물 세팅")
    box_configs = {}
    
    # 🚨 C, D, E형을 제거하고 A, B형만 남겼습니다. B형 기본 수량은 0개로 설정했습니다.
    box_defaults = {
        'B형 ': {"w": 550, "h": 900, "d": 600, "wt": 30, "cnt": 0},
        'A형 ': {"w": 500, "h": 300, "d": 400, "wt": 15, "cnt": 30}
    }
    
    for k, v in box_defaults.items():
        with st.expander(f"{k} 설정"):
            cnt = st.number_input(f"수량", value=v["cnt"], key=f"c_{k}")
            w = st.number_input("W", value=v["w"], key=f"w_{k}")
            h = st.number_input("H", value=v["h"], key=f"h_{k}")
            d = st.number_input("L", value=v["d"], key=f"d_{k}")
            wt = st.number_input("kg", value=v["wt"], key=f"wt_{k}")
            box_configs[k.split(' ')[0]] = {"w": w, "h": h, "d": d, "wt": wt, "cnt": cnt}
            
    st.markdown("---")
    force_upright = st.toggle("⬆️ 세워서 적재 강제", value=True)
    min_support = st.slider("안전 지지율 (%)", 10, 100, 70)
    run_btn = st.button("🚀 시뮬레이션 가동", type="primary")

if run_btn:
    packer = Packer()
    actual_calc_h = custom_h - PALLET_H - clearance if use_pallet else custom_h
    packer.add_bin(Bin("차량", custom_w, actual_calc_h, custom_d, custom_max_w))
    
    # 🚨 패킹 루프도 A형, B형만 돌아가도록 수정했습니다.
    for bt in ['B형', 'A형']:
        cfg = box_configs[bt]
        # 수량이 0개면 range(0)이 되어 알아서 추가되지 않고 다음으로 넘어갑니다!
        for i in range(cfg["cnt"]):
            item = Item(f'{bt}_{i+1}', cfg["w"], cfg["h"], cfg["d"], cfg["wt"])
            item.force_upright = force_upright
            packer.add_item(item)
            
    packer.pack()
    b = packer.bins[0]
    rejected = apply_physics_engine(b, min_support_ratio=(min_support/100.0))
    cg_x, cg_y, cg_z, total_wt = calculate_center_of_gravity(b.items)
    
    st.subheader("📊 시뮬레이션 리포트")
    c1, c2, c3 = st.columns(3)
    c1.metric("📦 적재 상자", f"{len(b.items)} 개")
    c2.metric("📈 공간 활용률", f"{(sum([float(i.width)*float(i.height)*float(i.depth) for i in b.items]) / (custom_w*custom_h*custom_d)*100):.2f}%")
    c3.metric("⚖️ 하중 밸런스", f"{100 - abs(custom_d/2 - cg_z)/custom_d*100:.1f}점")
    
    st.markdown("### 🚛 3D 실사 시뮬레이션 (Three.js)")
    
    json_data = export_to_json(b)
    try:
        with open("viewer.html", "r", encoding="utf-8") as f:
            html_template = f.read()
        rendered_html = html_template.replace("{{INJECT_JSON_DATA}}", json_data)
        components.html(rendered_html, height=700)
    except FileNotFoundError:
        st.error("🚨 `viewer.html` 파일을 찾을 수 없습니다.")
